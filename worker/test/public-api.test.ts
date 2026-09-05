import { env } from "cloudflare:workers";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { createDatabase } from "../src/db";
import app from "../src/index";
import { applyMigrations, type MigrationFile } from "./helpers/migrations";

const NOW = new Date("2026-07-13T03:30:00Z");
const RADIO_ID = "busan-039-kbs-1radio-busan";
const EMPTY_RADIO_ID = "seoul-007-mbc-sfm-main";
const ALLOWED_ORIGIN = "https://radio.bsod.kr";
const db = createDatabase({ url: "http://127.0.0.1:8093" });
const testEnv = env as typeof env & { TEST_MIGRATIONS: MigrationFile[] };
const bindings = {
  DB: db,
  CORS_ORIGINS: `${ALLOWED_ORIGIN},http://localhost:8000`,
};

async function seedPublicApi(): Promise<void> {
  await db.batch([
    db.prepare(
      "INSERT INTO sources (id, name, kind, base_url, priority) VALUES (?, ?, ?, ?, ?)",
    ).bind("kbs", "KBS 편성표", "official", "https://schedule.kbs.co.kr/", 100),
    db.prepare("INSERT INTO broadcasters (id, name) VALUES (?, ?)").bind(
      "kbs",
      "KBS",
    ),
    db.prepare("INSERT INTO broadcasters (id, name) VALUES (?, ?)").bind(
      "mbc",
      "MBC",
    ),
    db.prepare(
      "INSERT INTO channels (id, broadcaster_id, name, region_id, stn, ch, city) VALUES (?, ?, ?, ?, ?, ?, ?)",
    ).bind("kbs.1radio.busan", "kbs", "KBS부산 1라디오", "busan", "kbs", "1radio", "busan"),
    db.prepare(
      "INSERT INTO channels (id, broadcaster_id, name, region_id, stn, ch) VALUES (?, ?, ?, ?, ?, ?)",
    ).bind("mbc.sfm.main", "mbc", "MBC 표준FM", "seoul", "mbc", "sfm"),
    db.prepare(
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
    db.prepare(
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
    db.prepare(
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
    db.prepare(
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
  await applyMigrations(db, testEnv.TEST_MIGRATIONS);
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

  it("caps the cache lifetime when the next boundary is far away", async () => {
    const response = await request(`/v1/now?radio_ids=${RADIO_ID}`);

    expect(response.headers.get("Cache-Control")).toBe("public, max-age=300");
  });

  it("ends the cache lifetime when the current program ends", async () => {
    vi.setSystemTime(new Date("2026-07-13T03:58:00Z"));
    try {
      const response = await request("/v1/now?radio_ids=kbs/1radio/busan");

      expect(response.headers.get("Cache-Control")).toBe("public, max-age=120");
    } finally {
      vi.setSystemTime(NOW);
    }
  });

  it("serves repeated identical requests from the edge cache", async () => {
    const path = `/v1/now?radio_ids=${EMPTY_RADIO_ID},${RADIO_ID}`;
    const readStatus = async () => {
      const body = (await (await request(path)).json()) as { results: Array<{ status: string }> };
      return body.results[0].status;
    };
    expect(await readStatus()).toBe("unavailable");

    await db.prepare(
      `INSERT INTO schedule_events (
        id, event_key, channel_id, source_id, broadcast_date, starts_at, ends_at,
        title, source_url, source_kind, fetched_at, confidence
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
      .bind(
        "event-cache-probe",
        "event-cache-probe",
        "mbc.sfm.main",
        "kbs",
        "2026-07-13",
        "2026-07-13T03:00:00Z",
        "2026-07-13T04:00:00Z",
        "캐시 확인용",
        "https://schedule.kbs.co.kr/",
        "official",
        "2026-07-11T03:00:00Z",
        1,
      )
      .run();

    try {
      // 새 편성이 들어와도 캐시가 살아 있는 동안에는 DB를 다시 읽지 않는다.
      expect(await readStatus()).toBe("unavailable");
    } finally {
      await db.prepare("DELETE FROM schedule_events WHERE id = ?")
        .bind("event-cache-probe")
        .run();
    }
  });

  it("serves large playlists without exceeding the per-request subrequest budget", async () => {
    // 채널마다 cache.match/put을 하나씩 날리면 채널 수만큼 subrequest가 생겨서,
    // 즐겨찾기를 전체 채널처럼 많이 선택한 요청은 Cloudflare Workers의 subrequest
    // 상한을 넘겨 500으로 죽는다. PER_CHANNEL_CACHE_LIMIT(30)보다 많은 채널을
    // 한 번에 조회해도 정상적으로 응답하는지 검증한다.
    const bulkChannelIds = Array.from({ length: 35 }, (_, index) => `bulk.channel.${index}`);
    await db.batch(
      bulkChannelIds.map((channelId, index) =>
        db.prepare(
          "INSERT INTO channels (id, broadcaster_id, name, region_id, stn, ch) VALUES (?, ?, ?, ?, ?, ?)",
        ).bind(channelId, "kbs", `벌크 채널 ${index}`, "seoul", "bulk", `ch${index}`),
      ),
    );

    try {
      const response = await request(`/v1/now?radio_ids=${bulkChannelIds.join(",")}`);
      const body = (await response.json()) as { results: Array<{ channel_id: string | null; status: string }> };

      expect(response.status).toBe(200);
      expect(body.results).toHaveLength(bulkChannelIds.length);
      expect(body.results.every((result) => result.status === "unavailable")).toBe(true);
      expect(body.results.map((result) => result.channel_id)).toEqual(bulkChannelIds);
    } finally {
      await db.batch(
        bulkChannelIds.map((channelId) =>
          db.prepare("DELETE FROM channels WHERE id = ?").bind(channelId),
        ),
      );
    }
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
