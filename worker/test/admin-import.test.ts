import { env } from "cloudflare:workers";
import { applyD1Migrations, type D1Migration } from "cloudflare:test";
import { beforeAll, describe, expect, it } from "vitest";

import app from "../src/index";

const TOKEN = "test-ingest-token";
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

function importBatch(suffix: string) {
  const channelId = `kbs.1radio.${suffix}`;
  return {
    idempotency_key: `kbs-${suffix}`,
    source: {
      source_id: "kbs",
      name: "KBS 편성표",
      source_kind: "official",
      source_url: "https://schedule.kbs.co.kr/",
      priority: 100,
      fetched_at: "2026-07-13T01:00:00Z",
    },
    channels: [
      {
        channel_id: channelId,
        broadcaster_id: "kbs",
        name: `KBS ${suffix}`,
        stn: "kbs",
        ch: "1radio",
        city: suffix,
        region_ids: ["seoul"],
        radio_ids: [`seoul-${suffix}-kbs-1radio-${suffix}`],
      },
    ],
    programs: [
      {
        source_id: "kbs",
        program_id: `kbs.news.${suffix}`,
        title: "KBS 뉴스",
        hosts: [],
      },
    ],
    schedules: [
      {
        source_id: "kbs",
        source_url: "https://schedule.kbs.co.kr/",
        source_kind: "official",
        fetched_at: "2026-07-13T01:00:00Z",
        confidence: 1,
        channel_id: channelId,
        program_id: `kbs.news.${suffix}`,
        source_event_id: `event-${suffix}`,
        broadcast_date: "2026-07-13",
        starts_at: "2026-07-13T03:00:00Z",
        ends_at: "2026-07-13T04:00:00Z",
        title: "KBS 뉴스",
        is_live: false,
        is_rerun: false,
      },
    ],
    images: [],
    collected_at: "2026-07-13T01:01:00Z",
  };
}

async function adminRequest(
  body: unknown,
  options: { token?: string | null; raw?: boolean } = {},
): Promise<Response> {
  const token = options.token === undefined ? TOKEN : options.token;
  const headers = new Headers({ "Content-Type": "application/json" });
  if (token !== null) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return app.request(
    "https://api.example.test/v1/admin/import",
    {
      method: "POST",
      headers,
      body: options.raw ? String(body) : JSON.stringify(body),
    },
    bindings,
  );
}

beforeAll(async () => {
  await applyD1Migrations(testEnv.DB, testEnv.TEST_MIGRATIONS);
});

describe("authenticated schedule ingestion", () => {
  it("rejects a missing bearer token", async () => {
    const response = await adminRequest(importBatch("missing-token"), { token: null });

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toMatchObject({ error: { code: "unauthorized" } });
  });

  it("rejects a wrong bearer token", async () => {
    const response = await adminRequest(importBatch("wrong-token"), { token: "wrong-token-value" });

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toMatchObject({ error: { code: "unauthorized" } });
  });

  it("rejects requests larger than one megabyte", async () => {
    const response = await adminRequest(`{"padding":"${"x".repeat(1_000_001)}"}`, { raw: true });

    expect(response.status).toBe(413);
    await expect(response.json()).resolves.toMatchObject({ error: { code: "request_too_large" } });
  });

  it("rejects an invalid import schema", async () => {
    const response = await adminRequest({ idempotency_key: "invalid" });

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toMatchObject({ error: { code: "invalid_import" } });
  });

  it("applies the first valid import", async () => {
    const batch = importBatch("first");
    const response = await adminRequest(batch);
    const event = await testEnv.DB.prepare(
      "SELECT title FROM schedule_events WHERE channel_id = ?",
    )
      .bind("kbs.1radio.first")
      .first<{ title: string }>();

    expect(response.status).toBe(201);
    await expect(response.json()).resolves.toMatchObject({
      status: "applied",
      idempotency_key: "kbs-first",
      event_count: 1,
    });
    expect(event?.title).toBe("KBS 뉴스");
  });

  it("returns the stored result for an identical re-import", async () => {
    const batch = importBatch("identical");

    expect((await adminRequest(batch)).status).toBe(201);
    const response = await adminRequest(batch);

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ status: "already_applied" });
  });

  it("treats JSON formatting differences as the same idempotent payload", async () => {
    const batch = importBatch("formatted-identical");
    expect((await adminRequest(batch)).status).toBe(201);

    const response = await adminRequest(JSON.stringify(batch, null, 2), { raw: true });

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ status: "already_applied" });
  });

  it("rejects non-UTC schedule timestamps", async () => {
    const batch = importBatch("offset-time");
    batch.schedules[0].starts_at = "2026-07-13T12:00:00+09:00";
    batch.schedules[0].ends_at = "2026-07-13T13:00:00+09:00";

    const response = await adminRequest(batch);

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toMatchObject({ error: { code: "invalid_import" } });
  });

  it("rejects an impossible broadcast date", async () => {
    const batch = importBatch("invalid-date");
    batch.schedules[0].broadcast_date = "2026-99-99";

    const response = await adminRequest(batch);

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toMatchObject({ error: { code: "invalid_import" } });
  });

  it("rejects a changed payload that reuses an idempotency key", async () => {
    const batch = importBatch("changed");
    expect((await adminRequest(batch)).status).toBe(201);

    batch.schedules[0].title = "변경된 뉴스";
    const response = await adminRequest(batch);

    expect(response.status).toBe(409);
    await expect(response.json()).resolves.toMatchObject({ error: { code: "idempotency_conflict" } });
  });

  it("rolls back a partial database failure", async () => {
    const original = importBatch("rollback");
    expect((await adminRequest(original)).status).toBe(201);

    const changed = importBatch("rollback");
    changed.idempotency_key = "kbs-rollback-changed";
    changed.schedules[0].title = "교체되면 안 되는 뉴스";
    changed.schedules.push({
      ...changed.schedules[0],
      source_event_id: "event-rollback-invalid",
      starts_at: "2026-07-13T04:00:00Z",
      ends_at: "2026-07-13T05:00:00Z",
      program_id: "missing-program",
    });

    const response = await adminRequest(changed);
    const events = await testEnv.DB.prepare(
      "SELECT title FROM schedule_events WHERE channel_id = ? ORDER BY starts_at",
    )
      .bind("kbs.1radio.rollback")
      .all<{ title: string }>();

    expect(response.status).toBe(500);
    await expect(response.json()).resolves.toMatchObject({ error: { code: "import_failed" } });
    expect(events.results.map(({ title }) => title)).toEqual(["KBS 뉴스"]);
  });

  it("does not erase valid events with an empty batch", async () => {
    const original = importBatch("empty");
    expect((await adminRequest(original)).status).toBe(201);

    const empty = { ...importBatch("empty"), idempotency_key: "kbs-empty-invalid", schedules: [] };
    const response = await adminRequest(empty);
    const count = await testEnv.DB.prepare(
      "SELECT COUNT(*) AS count FROM schedule_events WHERE channel_id = ?",
    )
      .bind("kbs.1radio.empty")
      .first<{ count: number }>();

    expect(response.status).toBe(400);
    expect(count?.count).toBe(1);
  });
});
