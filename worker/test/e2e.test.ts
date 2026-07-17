import { env } from "cloudflare:workers";
import { applyD1Migrations, type D1Migration } from "cloudflare:test";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import batch from "../../tests/fixtures/e2e/kbs-import.json";
import app from "../src/index";

const TOKEN = "test-ingest-token";
const RADIO_ID = "busan-039-kbs-1radio-busan";
const NOW = new Date("2026-07-12T20:30:00Z");
const testEnv = env as typeof env & {
  DB: D1Database;
  TEST_MIGRATIONS: D1Migration[];
};
const bindings = {
  DB: testEnv.DB,
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

beforeAll(async () => {
  await applyD1Migrations(testEnv.DB, testEnv.TEST_MIGRATIONS);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);

  expect((await post("/v1/admin/import", batch)).status).toBe(201);
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
      aliases: [
        { type: "radio_id", value: RADIO_ID },
        { type: "tuple", value: "kbs/1radio/busan" },
      ],
    });
    await expect(byRadioId.json()).resolves.toMatchObject({
      channel_id: "kbs.1radio.busan",
    });
  });

  it("returns current, next, and fresh official source metadata", async () => {
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

  it("queries the imported broadcast date", async () => {
    const schedule = await app.request(
      `https://api.example.test/v1/schedules?radio_id=${RADIO_ID}&date=2026-07-13`,
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
