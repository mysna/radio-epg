import { env } from "cloudflare:workers";
import { beforeAll, describe, expect, it } from "vitest";

import { createDatabase } from "../src/db";
import app from "../src/index";
import { deleteSupersededScheduleEvents } from "../src/retention";
import { applyMigrations, type MigrationFile } from "./helpers/migrations";

const TOKEN = "test-ingest-token";
const db = createDatabase({ url: "http://127.0.0.1:8094" });
const testEnv = env as typeof env & { TEST_MIGRATIONS: MigrationFile[] };
const bindings = {
  DB: db,
  INGEST_TOKEN: TOKEN,
};

// 2026-07-07과 2026-07-14는 같은 화요일 슬롯이다. 07-14가 최신이므로 07-07만 지운다.
const retentionEvents = [
  {
    id: "retention-last-tuesday",
    broadcastDate: "2026-07-07",
    startsAt: "2026-07-06T15:00:00Z",
    endsAt: "2026-07-06T16:00:00Z",
  },
  {
    id: "retention-tuesday",
    broadcastDate: "2026-07-14",
    startsAt: "2026-07-13T15:00:00Z",
    endsAt: "2026-07-13T16:00:00Z",
  },
  {
    id: "retention-old-wednesday",
    broadcastDate: "2026-06-10",
    startsAt: "2026-06-09T15:00:00Z",
    endsAt: "2026-06-09T16:00:00Z",
  },
  {
    id: "retention-monday",
    broadcastDate: "2026-07-13",
    startsAt: "2026-07-12T15:00:00Z",
    endsAt: "2026-07-12T16:00:00Z",
  },
];

async function seedRetentionData(): Promise<void> {
  await db.batch([
    db.prepare(
      "INSERT INTO sources (id, name, kind, base_url, priority) VALUES (?, ?, ?, ?, ?)",
    ).bind("retention", "Retention source", "official", "https://source.example.test/", 100),
    db.prepare("INSERT INTO broadcasters (id, name) VALUES (?, ?)").bind(
      "retention",
      "Retention broadcaster",
    ),
    db.prepare(
      "INSERT INTO channels (id, broadcaster_id, name, stn, ch) VALUES (?, ?, ?, ?, ?)",
    ).bind("retention.fm.main", "retention", "Retention FM", "retention", "fm"),
    db.prepare(
      "INSERT INTO programs (id, source_id, upstream_id, title) VALUES (?, ?, ?, ?)",
    ).bind(
      "retention.program",
      "retention",
      "retention.program",
      "Retention program",
    ),
  ]);
  await db.batch(
    retentionEvents.map((event) =>
      db
        .prepare(
          `INSERT INTO schedule_events (
             id, event_key, channel_id, program_id, source_id, source_event_id,
             broadcast_date, starts_at, ends_at, title, source_url, source_kind,
             fetched_at, confidence
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        )
        .bind(
          event.id,
          event.id,
          "retention.fm.main",
          "retention.program",
          "retention",
          event.id,
          event.broadcastDate,
          event.startsAt,
          event.endsAt,
          event.id,
          "https://source.example.test/",
          "official",
          "2026-07-13T00:00:00Z",
          1,
        ),
    ),
  );
}

beforeAll(async () => {
  await applyMigrations(db, testEnv.TEST_MIGRATIONS);
  await seedRetentionData();
});

describe("weekday slot retention", () => {
  it("finds superseded slot rows through the slot index", async () => {
    const plan = await db.prepare(
      `EXPLAIN QUERY PLAN
       SELECT source_id, channel_id, weekday, MAX(broadcast_date)
       FROM schedule_events GROUP BY source_id, channel_id, weekday`,
    ).all<{ detail: string }>();

    expect(plan.results.map(({ detail }) => detail).join(" ")).toContain(
      "idx_schedule_events_source_slot",
    );
  });

  it("keeps only the latest date per weekday slot regardless of age and is idempotent", async () => {
    const first = await deleteSupersededScheduleEvents(db);
    const second = await deleteSupersededScheduleEvents(db);
    const events = await db.prepare("SELECT id FROM schedule_events ORDER BY id").all<{
      id: string;
    }>();
    const programs = await db.prepare("SELECT COUNT(*) AS count FROM programs").first<{
      count: number;
    }>();

    expect(first).toEqual({ deleted: 1 });
    expect(second).toEqual({ deleted: 0 });
    expect(events.results.map(({ id }) => id)).toEqual([
      "retention-monday",
      "retention-old-wednesday",
      "retention-tuesday",
    ]);
    expect(programs?.count).toBe(1);
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
    await expect(authorized.json()).resolves.toEqual({ status: "completed", deleted: 0 });
  });
});
