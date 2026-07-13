import { env } from "cloudflare:workers";
import { applyD1Migrations, type D1Migration } from "cloudflare:test";
import { beforeAll, describe, expect, it } from "vitest";

const EXPECTED_TABLES = [
  "broadcasters",
  "channel_aliases",
  "channels",
  "image_assets",
  "image_takedowns",
  "image_variants",
  "programs",
  "schedule_events",
  "scrape_runs",
  "sources",
];

const testEnv = env as typeof env & {
  DB: D1Database;
  TEST_MIGRATIONS?: D1Migration[];
};

async function seedChannel(suffix: string): Promise<void> {
  await testEnv.DB.batch([
    testEnv.DB.prepare(
      "INSERT OR IGNORE INTO sources (id, name, kind, base_url, priority) VALUES (?, ?, ?, ?, ?)",
    ).bind("kbs", "KBS", "official", "https://schedule.kbs.co.kr/", 100),
    testEnv.DB.prepare(
      "INSERT OR IGNORE INTO broadcasters (id, name) VALUES (?, ?)",
    ).bind("kbs", "KBS"),
    testEnv.DB.prepare(
      "INSERT OR IGNORE INTO channels (id, broadcaster_id, name, stn, ch) VALUES (?, ?, ?, ?, ?)",
    ).bind(`kbs.1radio.${suffix}`, "kbs", `KBS ${suffix}`, "kbs", "1radio"),
  ]);
}

beforeAll(async () => {
  if (testEnv.TEST_MIGRATIONS) {
    await applyD1Migrations(testEnv.DB, testEnv.TEST_MIGRATIONS);
  }
});

describe("D1 migration", () => {
  it("creates every core and image table", async () => {
    const result = await testEnv.DB.prepare(
      "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name != 'd1_migrations' ORDER BY name",
    ).all<{ name: string }>();

    expect(result.results.map(({ name }) => name)).toEqual(expect.arrayContaining(EXPECTED_TABLES));
  });

  it("rejects duplicate aliases", async () => {
    await seedChannel("alias");
    const statement = testEnv.DB.prepare(
      "INSERT INTO channel_aliases (channel_id, alias_type, alias_value) VALUES (?, ?, ?)",
    ).bind("kbs.1radio.alias", "radio_id", "seoul-001-kbs-1radio-main");

    await statement.run();

    await expect(statement.run()).rejects.toThrow();
  });

  it("rejects schedules whose end does not follow their start", async () => {
    await seedChannel("duration");
    const statement = testEnv.DB.prepare(
      `INSERT INTO schedule_events (
        id, event_key, channel_id, source_id, broadcast_date, starts_at, ends_at,
        title, source_url, source_kind, fetched_at, confidence
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    ).bind(
      "invalid-duration",
      "invalid-duration",
      "kbs.1radio.duration",
      "kbs",
      "2026-07-13",
      "2026-07-13T03:00:00Z",
      "2026-07-13T03:00:00Z",
      "KBS 뉴스",
      "https://schedule.kbs.co.kr/",
      "official",
      "2026-07-13T01:00:00Z",
      1,
    );

    await expect(statement.run()).rejects.toThrow();
  });

  it("rejects repeated import idempotency keys", async () => {
    const statement = testEnv.DB.prepare(
      "INSERT INTO scrape_runs (id, source_id, idempotency_key, started_at, status) VALUES (?, ?, ?, ?, ?)",
    );
    await statement.bind("run-1", "kbs", "kbs-2026-07-13", "2026-07-13T01:00:00Z", "running").run();

    await expect(
      statement.bind("run-2", "kbs", "kbs-2026-07-13", "2026-07-13T02:00:00Z", "running").run(),
    ).rejects.toThrow();
  });

  it("uses the channel and start-time index for schedule lookup", async () => {
    const result = await testEnv.DB.prepare(
      "EXPLAIN QUERY PLAN SELECT * FROM schedule_events WHERE channel_id = ? AND starts_at >= ? ORDER BY starts_at",
    )
      .bind("kbs.1radio.main", "2026-07-13T00:00:00Z")
      .all<{ detail: string }>();

    expect(result.results.map(({ detail }) => detail).join(" ")).toContain(
      "idx_schedule_events_channel_starts",
    );
  });
});
