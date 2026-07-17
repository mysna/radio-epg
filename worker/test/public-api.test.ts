import { env } from "cloudflare:workers";
import { applyD1Migrations, type D1Migration } from "cloudflare:test";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import app from "../src/index";

const NOW = new Date("2026-07-13T03:30:00Z");
const RADIO_ID = "busan-039-kbs-1radio-busan";
const EMPTY_RADIO_ID = "seoul-007-mbc-sfm-main";
const ALLOWED_ORIGIN = "https://radio.bsod.kr";
const testEnv = env as typeof env & {
  DB: D1Database;
  IMAGES: R2Bucket;
  TEST_MIGRATIONS: D1Migration[];
};
const bindings = {
  DB: testEnv.DB,
  IMAGES: testEnv.IMAGES,
  CORS_ORIGINS: `${ALLOWED_ORIGIN},http://localhost:8000`,
};

async function seedPublicApi(): Promise<void> {
  await testEnv.DB.batch([
    testEnv.DB.prepare(
      "INSERT INTO sources (id, name, kind, base_url, priority) VALUES (?, ?, ?, ?, ?)",
    ).bind("kbs", "KBS 편성표", "official", "https://schedule.kbs.co.kr/", 100),
    testEnv.DB.prepare("INSERT INTO broadcasters (id, name) VALUES (?, ?)").bind(
      "kbs",
      "KBS",
    ),
    testEnv.DB.prepare("INSERT INTO broadcasters (id, name) VALUES (?, ?)").bind(
      "mbc",
      "MBC",
    ),
    testEnv.DB.prepare(
      "INSERT INTO channels (id, broadcaster_id, name, region_id, stn, ch, city) VALUES (?, ?, ?, ?, ?, ?, ?)",
    ).bind("kbs.1radio.busan", "kbs", "KBS부산 1라디오", "busan", "kbs", "1radio", "busan"),
    testEnv.DB.prepare(
      "INSERT INTO channels (id, broadcaster_id, name, region_id, stn, ch) VALUES (?, ?, ?, ?, ?, ?)",
    ).bind("mbc.sfm.main", "mbc", "MBC 표준FM", "seoul", "mbc", "sfm"),
    testEnv.DB.prepare(
      "INSERT INTO channel_aliases (channel_id, alias_type, alias_value) VALUES (?, ?, ?), (?, ?, ?), (?, ?, ?)",
    ).bind(
      "kbs.1radio.busan",
      "radio_id",
      RADIO_ID,
      "kbs.1radio.busan",
      "tuple",
      "kbs/1radio/busan",
      "mbc.sfm.main",
      "radio_id",
      EMPTY_RADIO_ID,
    ),
    testEnv.DB.prepare(
      "INSERT INTO programs (id, source_id, upstream_id, title) VALUES (?, ?, ?, ?), (?, ?, ?, ?)",
    ).bind(
      "kbs.news",
      "kbs",
      "news",
      "KBS 뉴스",
      "kbs.next",
      "kbs",
      "next",
      "다음 프로그램",
    ),
    testEnv.DB.prepare(
      `INSERT INTO schedule_events (
        id, event_key, channel_id, program_id, source_id, source_event_id,
        broadcast_date, starts_at, ends_at, title, source_url, source_kind,
        fetched_at, confidence
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?),
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    ).bind(
      "event-current",
      "event-current",
      "kbs.1radio.busan",
      "kbs.news",
      "kbs",
      "current",
      "2026-07-13",
      "2026-07-13T03:00:00Z",
      "2026-07-13T04:00:00Z",
      "KBS 뉴스",
      "https://schedule.kbs.co.kr/",
      "official",
      "2026-07-11T03:00:00Z",
      1,
      "event-next",
      "event-next",
      "kbs.1radio.busan",
      "kbs.next",
      "kbs",
      "next",
      "2026-07-13",
      "2026-07-13T04:00:00Z",
      "2026-07-13T05:00:00Z",
      "다음 프로그램",
      "https://schedule.kbs.co.kr/",
      "official",
      "2026-07-11T03:00:00Z",
      1,
    ),
    testEnv.DB.prepare(
      "INSERT INTO scrape_runs (id, source_id, idempotency_key, started_at, finished_at, status, event_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
    ).bind(
      "run-kbs",
      "kbs",
      "kbs-2026-07-13",
      "2026-07-13T01:00:00Z",
      "2026-07-13T01:01:00Z",
      "succeeded",
      2,
    ),
  ]);
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  return app.request(`https://api.example.test${path}`, init, bindings);
}

beforeAll(async () => {
  await applyD1Migrations(testEnv.DB, testEnv.TEST_MIGRATIONS);
  await seedPublicApi();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterAll(() => {
  vi.useRealTimers();
});

describe("public channel API", () => {
  it("lists active channels", async () => {
    const response = await request("/v1/channels");
    const body = (await response.json()) as { channels: Array<{ channel_id: string }> };

    expect(response.status).toBe(200);
    expect(body.channels.map(({ channel_id }) => channel_id)).toEqual([
      "kbs.1radio.busan",
      "mbc.sfm.main",
    ]);
    expect(body.channels[0]).not.toHaveProperty("image_url");
  });

  it("looks up a channel by canonical ID", async () => {
    const response = await request("/v1/channels/kbs.1radio.busan");

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      channel_id: "kbs.1radio.busan",
      name: "KBS부산 1라디오",
      broadcaster: { id: "kbs", name: "KBS" },
    });
  });

  it("looks up a channel by current radio ID", async () => {
    const response = await request(`/v1/channels/${RADIO_ID}`);

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ channel_id: "kbs.1radio.busan" });
  });

  it("looks up a channel by encoded tuple alias", async () => {
    const response = await request(`/v1/channels/${encodeURIComponent("kbs/1radio/busan")}`);

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ channel_id: "kbs.1radio.busan" });
  });
});

describe("public schedule API", () => {
  it("returns a requested broadcast date with source freshness", async () => {
    const response = await request(`/v1/schedules?radio_id=${RADIO_ID}&date=2026-07-13`);

    expect(response.status).toBe(200);
    const body = (await response.json()) as {
      channel_id: string;
      broadcast_date: string;
      status: string;
      stale: boolean;
      events: unknown[];
    };

    expect(body).toMatchObject({
      channel_id: "kbs.1radio.busan",
      broadcast_date: "2026-07-13",
      status: "available",
      stale: true,
    });
    expect(body.events[0]).toMatchObject({
      title: "KBS 뉴스",
      source: { id: "kbs", kind: "official", confidence: 1, stale: true },
    });
    expect(body.events[0]).not.toHaveProperty("program_image_url");
  });

  it("rejects invalid calendar dates with a stable error", async () => {
    const response = await request(`/v1/schedules?radio_id=${RADIO_ID}&date=2026-02-30`);

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      error: { code: "invalid_date", message: "date must be a valid YYYY-MM-DD value." },
    });
  });

  it("returns unavailable for a known channel without schedule data", async () => {
    const response = await request(`/v1/schedules?radio_id=${EMPTY_RADIO_ID}&date=2026-07-13`);

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      channel_id: "mbc.sfm.main",
      status: "unavailable",
      events: [],
    });
  });

  it("returns a stable not-found error for an unknown alias", async () => {
    const response = await request("/v1/schedules?radio_id=missing&date=2026-07-13");

    expect(response.status).toBe(404);
    await expect(response.json()).resolves.toEqual({
      error: {
        code: "channel_not_found",
        message: "The requested channel alias is not registered.",
      },
    });
  });

  it("supports ETag revalidation", async () => {
    const first = await request(`/v1/schedules?radio_id=${RADIO_ID}&date=2026-07-13`);
    const etag = first.headers.get("ETag");

    expect(etag).toBeTruthy();

    const second = await request(`/v1/schedules?radio_id=${RADIO_ID}&date=2026-07-13`, {
      headers: { "If-None-Match": etag ?? "" },
    });

    expect(second.status).toBe(304);
    expect(await second.text()).toBe("");
  });
});

describe("current schedule API", () => {
  it("returns current and next programs for one radio ID", async () => {
    const response = await request(`/v1/now?radio_ids=${RADIO_ID}`);
    const body = (await response.json()) as { results: unknown[] };

    expect(response.status).toBe(200);
    expect(body.results[0]).toMatchObject({
      radio_id: RADIO_ID,
      channel_id: "kbs.1radio.busan",
      status: "available",
      current: { title: "KBS 뉴스" },
      next: { title: "다음 프로그램" },
    });
  });

  it("returns multiple radio IDs and marks missing data unavailable", async () => {
    const response = await request(`/v1/now?radio_ids=${RADIO_ID},${EMPTY_RADIO_ID}`);
    const body = (await response.json()) as { results: unknown[] };

    expect(response.status).toBe(200);
    expect(body.results).toHaveLength(2);
    expect(body.results[1]).toMatchObject({
      radio_id: EMPTY_RADIO_ID,
      channel_id: "mbc.sfm.main",
      status: "unavailable",
      current: null,
      next: null,
    });
  });

  it("keeps valid results when a radio ID is not registered", async () => {
    const response = await request(`/v1/now?radio_ids=${RADIO_ID},missing`);
    const body = (await response.json()) as { results: unknown[] };

    expect(response.status).toBe(200);
    expect(body.results).toHaveLength(2);
    expect(body.results[0]).toMatchObject({
      radio_id: RADIO_ID,
      channel_id: "kbs.1radio.busan",
      status: "available",
    });
    expect(body.results[1]).toEqual({
      radio_id: "missing",
      channel_id: null,
      status: "not_found",
      current: null,
      next: null,
    });
  });

  it("limits radio ID batches to 100", async () => {
    const ids = Array.from({ length: 101 }, (_, index) => `radio-${index}`).join(",");
    const response = await request(`/v1/now?radio_ids=${ids}`);

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toMatchObject({
      error: { code: "too_many_radio_ids" },
    });
  });
});

describe("public API HTTP behavior", () => {
  it("varies cached responses by origin even without an Origin header", async () => {
    const response = await request("/v1/channels/kbs.1radio.busan");

    expect(response.headers.get("Vary")).toContain("Origin");
  });

  it("answers preflight requests for configured origins", async () => {
    const response = await request("/v1/channels", {
      method: "OPTIONS",
      headers: {
        Origin: ALLOWED_ORIGIN,
        "Access-Control-Request-Method": "GET",
      },
    });

    expect(response.status).toBe(204);
    expect(response.headers.get("Access-Control-Allow-Methods")).toContain("GET");
  });

  it("allows configured CORS origins", async () => {
    const response = await request("/v1/channels/kbs.1radio.busan", {
      headers: { Origin: ALLOWED_ORIGIN },
    });

    expect(response.status).toBe(200);
    expect(response.headers.get("Access-Control-Allow-Origin")).toBe(ALLOWED_ORIGIN);
  });

  it("denies unconfigured CORS origins", async () => {
    const response = await request("/v1/channels/kbs.1radio.busan", {
      headers: { Origin: "https://attacker.example" },
    });

    expect(response.status).toBe(403);
    await expect(response.json()).resolves.toMatchObject({
      error: { code: "origin_not_allowed" },
    });
  });

  it("reports source coverage", async () => {
    const response = await request("/v1/coverage");

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      sources: [{ source_id: "kbs", status: "available", event_count: 2 }],
    });
  });
});
