import { env } from "cloudflare:workers";
import { applyD1Migrations, type D1Migration } from "cloudflare:test";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import batch from "../../tests/fixtures/e2e/kbs-import.json";
import app from "../src/index";

const TOKEN = "test-ingest-token";
const RADIO_ID = "busan-039-kbs-1radio-busan";
const NOW = new Date("2026-07-12T20:30:00Z");
const PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgQIAKfWfWQAAAABJRU5ErkJggg==";
const CHANNEL_HASH = "a".repeat(64);
const PROGRAM_HASH = "b".repeat(64);
const testEnv = env as typeof env & {
  DB: D1Database;
  IMAGES: R2Bucket;
  TEST_MIGRATIONS: D1Migration[];
};
const bindings = {
  DB: testEnv.DB,
  IMAGES: testEnv.IMAGES,
  CORS_ORIGINS: "https://radio.bsod.kr",
  INGEST_TOKEN: TOKEN,
};

async function post(path: string, body: unknown): Promise<Response> {
  return app.request(
    `https://api.example.test${path}`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${TOKEN}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    },
    bindings,
  );
}

function imagePayload(
  entityType: "channel" | "program",
  entityId: string,
  contentHash: string,
) {
  return {
    asset: {
      source_id: "kbs",
      entity_type: entityType,
      entity_id: entityId,
      content_hash: contentHash,
      rights_status: "fixture",
      source_url: `https://images.example.test/${entityType}.png`,
      source_page_url: `https://images.example.test/${entityType}`,
      author: "E2E fixture",
      license: "test-only",
      attribution: "E2E fixture",
      verified_at: "2026-07-12T20:15:00Z",
    },
    variant: {
      name: "medium",
      mime_type: "image/png",
      width: 1,
      height: 1,
      byte_size: Uint8Array.from(atob(PNG_BASE64), (character) => character.charCodeAt(0))
        .byteLength,
      content_base64: PNG_BASE64,
    },
  };
}

beforeAll(async () => {
  await applyD1Migrations(testEnv.DB, testEnv.TEST_MIGRATIONS);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);

  expect((await post("/v1/admin/import", batch)).status).toBe(201);
  expect(
    (
      await post(
        "/v1/admin/images",
        imagePayload("channel", "kbs.1radio.busan", CHANNEL_HASH),
      )
    ).status,
  ).toBe(201);
  expect(
    (
      await post(
        "/v1/admin/images",
        imagePayload("program", "kbs:R-E2E-CURRENT", PROGRAM_HASH),
      )
    ).status,
  ).toBe(201);
});

afterAll(() => {
  vi.useRealTimers();
});

describe("collector to public API compatibility", () => {
  it("resolves the same channel by canonical and current radio IDs with stable aliases", async () => {
    const canonical = await app.request(
      "https://api.example.test/v1/channels/kbs.1radio.busan",
      {},
      bindings,
    );
    const byRadioId = await app.request(
      `https://api.example.test/v1/channels/${RADIO_ID}`,
      {},
      bindings,
    );

    expect(canonical.status).toBe(200);
    expect(byRadioId.status).toBe(200);
    await expect(canonical.json()).resolves.toMatchObject({
      channel_id: "kbs.1radio.busan",
      image_url: `/v1/images/${CHANNEL_HASH}/medium`,
      aliases: [
        { type: "radio_id", value: RADIO_ID },
        { type: "tuple", value: "kbs/1radio/busan" },
      ],
    });
    await expect(byRadioId.json()).resolves.toMatchObject({
      channel_id: "kbs.1radio.busan",
    });
  });

  it("returns current, next, program image, and fresh official source metadata", async () => {
    const response = await app.request(
      `https://api.example.test/v1/now?radio_ids=${RADIO_ID}`,
      {},
      bindings,
    );

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      results: [
        {
          radio_id: RADIO_ID,
          channel_id: "kbs.1radio.busan",
          status: "available",
          current: {
            title: "부산 아침",
            program_image_url: `/v1/images/${PROGRAM_HASH}/medium`,
            source: {
              id: "kbs",
              kind: "official",
              fetched_at: "2026-07-12T20:15:00Z",
              confidence: 1,
              stale: false,
            },
          },
          next: { title: "부산 다음" },
        },
      ],
    });
  });

  it("queries the imported broadcast date and serves non-empty image bytes with its MIME", async () => {
    const schedule = await app.request(
      `https://api.example.test/v1/schedules?radio_id=${RADIO_ID}&date=2026-07-13`,
      {},
      bindings,
    );
    const image = await app.request(
      `https://api.example.test/v1/images/${PROGRAM_HASH}/medium`,
      {},
      bindings,
    );

    expect(schedule.status).toBe(200);
    await expect(schedule.json()).resolves.toMatchObject({
      channel_id: "kbs.1radio.busan",
      status: "available",
      stale: false,
      events: [{ title: "부산 아침" }, { title: "부산 다음" }],
    });
    expect(image.status).toBe(200);
    expect(image.headers.get("Content-Type")).toBe("image/png");
    expect((await image.arrayBuffer()).byteLength).toBeGreaterThan(0);
  });

  it("reports the imported source as available and fresh", async () => {
    const response = await app.request("https://api.example.test/v1/coverage", {}, bindings);

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      sources: [
        {
          source_id: "kbs",
          status: "available",
          event_count: 2,
          last_fetched_at: "2026-07-12T20:15:00Z",
          stale: false,
        },
      ],
    });
  });
});
