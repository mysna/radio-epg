import { env } from "cloudflare:workers";
import { applyD1Migrations, type D1Migration } from "cloudflare:test";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import app from "../src/index";
import { deleteExpiredScheduleEvents } from "../src/retention";

const TOKEN = "test-ingest-token";
const NOW = new Date("2026-07-13T15:30:00Z");
const START_DATE = "2026-07-14";
const END_DATE = "2026-07-15";
const testEnv = env as typeof env & {
  DB: D1Database;
  TEST_MIGRATIONS: D1Migration[];
};
const bindings = {
  DB: testEnv.DB,
  INGEST_TOKEN: TOKEN,
};

const retentionEvents = [
  {
    id: "retention-yesterday",
    broadcastDate: "2026-07-13",
    startsAt: "2026-07-13T10:00:00Z",
    endsAt: "2026-07-13T11:00:00Z",
  },
  {
    id: "retention-today",
    broadcastDate: START_DATE,
    startsAt: "2026-07-13T15:00:00Z",
    endsAt: "2026-07-13T15:15:00Z",
  },
  {
    id: "retention-tomorrow",
    broadcastDate: END_DATE,
    startsAt: "2026-07-14T15:00:00Z",
    endsAt: "2026-07-14T16:00:00Z",
  },
  {
    id: "retention-day-after-tomorrow",
    broadcastDate: "2026-07-16",
    startsAt: "2026-07-15T15:00:00Z",
    endsAt: "2026-07-15T16:00:00Z",
  },
];

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
      "INSERT INTO programs (id, source_id, upstream_id, title) VALUES (?, ?, ?, ?)",
    ).bind(
      "retention.program",
      "retention",
      "retention.program",
      "Retention program",
    ),
  ]);
  await testEnv.DB.batch(
    retentionEvents.map((event) =>
      testEnv.DB
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
  await applyD1Migrations(testEnv.DB, testEnv.TEST_MIGRATIONS);
  await seedRetentionData();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterAll(() => {
  vi.useRealTimers();
});

describe("KST today-and-tomorrow schedule retention", () => {
  it("uses a broadcast-date index for bounded cleanup", async () => {
    const plan = await testEnv.DB.prepare(
      "EXPLAIN QUERY PLAN DELETE FROM schedule_events WHERE broadcast_date < ? OR broadcast_date > ?",
    )
      .bind(START_DATE, END_DATE)
      .all<{ detail: string }>();

    expect(plan.results.map(({ detail }) => detail).join(" ")).toContain(
      "idx_schedule_events_broadcast_date",
    );
  });

  it("keeps only today and tomorrow and is idempotent", async () => {
    const first = await deleteExpiredScheduleEvents(testEnv.DB, NOW);
    const second = await deleteExpiredScheduleEvents(testEnv.DB, NOW);
    const events = await testEnv.DB.prepare("SELECT id FROM schedule_events ORDER BY id").all<{
      id: string;
    }>();
    const programs = await testEnv.DB.prepare("SELECT COUNT(*) AS count FROM programs").first<{
      count: number;
    }>();

    expect(first).toEqual({ start_date: START_DATE, end_date: END_DATE, deleted: 2 });
    expect(second).toEqual({ start_date: START_DATE, end_date: END_DATE, deleted: 0 });
    expect(events.results.map(({ id }) => id)).toEqual([
      "retention-today",
      "retention-tomorrow",
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
    await expect(authorized.json()).resolves.toMatchObject({
      status: "completed",
      start_date: START_DATE,
      end_date: END_DATE,
      deleted: 0,
    });
  });

  it("can retain the collection run's date across a KST midnight boundary", async () => {
    const invalid = await app.request(
      "https://api.example.test/v1/admin/retention?start_date=2026-02-30",
      { method: "POST", headers: { Authorization: `Bearer ${TOKEN}` } },
      bindings,
    );
    expect(invalid.status).toBe(400);
    const stale = await app.request(
      "https://api.example.test/v1/admin/retention?start_date=2025-01-01",
      { method: "POST", headers: { Authorization: `Bearer ${TOKEN}` } },
      bindings,
    );
    expect(stale.status).toBe(400);

    await testEnv.DB.prepare("DELETE FROM schedule_events").run();
    await testEnv.DB.batch(
      retentionEvents.map((event) =>
        testEnv.DB
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

    const response = await app.request(
      "https://api.example.test/v1/admin/retention?start_date=2026-07-13",
      { method: "POST", headers: { Authorization: `Bearer ${TOKEN}` } },
      bindings,
    );
    const events = await testEnv.DB.prepare("SELECT id FROM schedule_events ORDER BY id").all<{
      id: string;
    }>();

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      start_date: "2026-07-13",
      end_date: "2026-07-14",
      deleted: 2,
    });
    expect(events.results.map(({ id }) => id)).toEqual([
      "retention-today",
      "retention-yesterday",
    ]);
  });
});
