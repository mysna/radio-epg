import { env } from "cloudflare:workers";
import { applyD1Migrations, type D1Migration } from "cloudflare:test";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import app from "../src/index";
import { deleteExpiredScheduleEvents } from "../src/retention";

const TOKEN = "test-ingest-token";
const NOW = new Date("2026-07-13T12:00:00Z");
const CUTOFF = "2026-06-13T12:00:00.000Z";
const testEnv = env as typeof env & {
  DB: D1Database;
  IMAGES: R2Bucket;
  TEST_MIGRATIONS: D1Migration[];
};
const bindings = {
  DB: testEnv.DB,
  IMAGES: testEnv.IMAGES,
  INGEST_TOKEN: TOKEN,
};

async function seedRetentionData(): Promise<void> {
  await testEnv.DB.batch([
    testEnv.DB.prepare(
      "INSERT INTO sources (id, name, kind, base_url, priority) VALUES (?, ?, ?, ?, ?)",
    ).bind("retention", "Retention source", "official", "https://source.example.test/", 100),
    testEnv.DB.prepare("INSERT INTO broadcasters (id, name) VALUES (?, ?)").bind(
      "retention",
      "Retention broadcaster",
    ),
    testEnv.DB.prepare(
      "INSERT INTO channels (id, broadcaster_id, name, stn, ch) VALUES (?, ?, ?, ?, ?)",
    ).bind("retention.fm.main", "retention", "Retention FM", "retention", "fm"),
    testEnv.DB.prepare(
      `INSERT INTO image_assets (
        id, source_id, entity_type, entity_id, content_hash, rights_status,
        source_url, source_page_url, first_verified_at, last_verified_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    ).bind(
      "c".repeat(64),
      "retention",
      "program",
      "retention.program",
      "c".repeat(64),
      "fixture",
      "https://images.example.test/program.png",
      "https://images.example.test/program",
      "2026-06-01T00:00:00Z",
      "2026-07-13T00:00:00Z",
    ),
    testEnv.DB.prepare(
      "INSERT INTO image_variants (asset_id, variant_name, mime_type, width, height, byte_size, r2_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
    ).bind("c".repeat(64), "medium", "image/png", 1, 1, 68, "images/retention/medium.png"),
    testEnv.DB.prepare(
      "INSERT INTO programs (id, source_id, upstream_id, title, image_asset_id) VALUES (?, ?, ?, ?, ?)",
    ).bind(
      "retention.program",
      "retention",
      "retention.program",
      "Retention program",
      "c".repeat(64),
    ),
    testEnv.DB.prepare(
      `INSERT INTO schedule_events (
        id, event_key, channel_id, program_id, source_id, source_event_id,
        broadcast_date, starts_at, ends_at, title, source_url, source_kind,
        fetched_at, confidence
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?),
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?),
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    ).bind(
      "retention-old",
      "retention-old",
      "retention.fm.main",
      "retention.program",
      "retention",
      "old",
      "2026-06-12",
      "2026-06-12T10:00:00Z",
      "2026-06-12T11:00:00Z",
      "Old event",
      "https://source.example.test/",
      "official",
      "2026-06-12T00:00:00Z",
      1,
      "retention-boundary",
      "retention-boundary",
      "retention.fm.main",
      "retention.program",
      "retention",
      "boundary",
      "2026-06-13",
      "2026-06-13T11:00:00Z",
      CUTOFF,
      "Boundary event",
      "https://source.example.test/",
      "official",
      "2026-06-13T00:00:00Z",
      1,
      "retention-active",
      "retention-active",
      "retention.fm.main",
      "retention.program",
      "retention",
      "active",
      "2026-07-13",
      "2026-07-13T11:00:00Z",
      "2026-07-13T13:00:00Z",
      "Active event",
      "https://source.example.test/",
      "official",
      "2026-07-13T10:00:00Z",
      1,
    ),
  ]);
}

beforeAll(async () => {
  await applyD1Migrations(testEnv.DB, testEnv.TEST_MIGRATIONS);
  await seedRetentionData();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterAll(() => {
  vi.useRealTimers();
});

describe("30-day schedule retention", () => {
  it("uses an end-time index for bounded cleanup", async () => {
    const plan = await testEnv.DB.prepare(
      "EXPLAIN QUERY PLAN DELETE FROM schedule_events WHERE ends_at < ?",
    )
      .bind(CUTOFF)
      .all<{ detail: string }>();

    expect(plan.results.map(({ detail }) => detail).join(" ")).toContain(
      "idx_schedule_events_ends_at",
    );
  });

  it("deletes only expired events and is idempotent", async () => {
    const first = await deleteExpiredScheduleEvents(testEnv.DB, NOW);
    const second = await deleteExpiredScheduleEvents(testEnv.DB, NOW);
    const events = await testEnv.DB.prepare("SELECT id FROM schedule_events ORDER BY id").all<{
      id: string;
    }>();
    const programs = await testEnv.DB.prepare("SELECT COUNT(*) AS count FROM programs").first<{
      count: number;
    }>();
    const assets = await testEnv.DB.prepare("SELECT COUNT(*) AS count FROM image_assets").first<{
      count: number;
    }>();
    const variants = await testEnv.DB.prepare("SELECT COUNT(*) AS count FROM image_variants").first<{
      count: number;
    }>();

    expect(first).toEqual({ cutoff: CUTOFF, deleted: 1 });
    expect(second).toEqual({ cutoff: CUTOFF, deleted: 0 });
    expect(events.results.map(({ id }) => id)).toEqual([
      "retention-active",
      "retention-boundary",
    ]);
    expect(programs?.count).toBe(1);
    expect(assets?.count).toBe(1);
    expect(variants?.count).toBe(1);
  });

  it("requires authentication and exposes an idempotent maintenance endpoint", async () => {
    const unauthorized = await app.request(
      "https://api.example.test/v1/admin/retention",
      { method: "POST" },
      bindings,
    );
    const authorized = await app.request(
      "https://api.example.test/v1/admin/retention",
      { method: "POST", headers: { Authorization: `Bearer ${TOKEN}` } },
      bindings,
    );

    expect(unauthorized.status).toBe(401);
    expect(authorized.status).toBe(200);
    await expect(authorized.json()).resolves.toMatchObject({ status: "completed", deleted: 0 });
  });
});
