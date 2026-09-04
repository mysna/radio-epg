import { env } from "cloudflare:workers";
import { beforeAll, describe, expect, it } from "vitest";

import { createDatabase } from "../src/db";
import type { MigrationFile } from "./helpers/migrations";
import { applyMigrations } from "./helpers/migrations";

const EXPECTED_TABLES = [
  "broadcasters",
  "channel_aliases",
  "channels",
  "programs",
  "schedule_events",
  "scrape_runs",
  "sources",
];

const db = createDatabase({ url: "http://127.0.0.1:8091" });
const testEnv = env as typeof env & { TEST_MIGRATIONS: MigrationFile[] };

async function seedChannel(suffix: string): Promise<void> {
  await db.batch([
    db.prepare(
      "INSERT OR IGNORE INTO sources (id, name, kind, base_url, priority) VALUES (?, ?, ?, ?, ?)",
    ).bind("kbs", "KBS", "official", "https://schedule.kbs.co.kr/", 100),
    db.prepare(
      "INSERT OR IGNORE INTO broadcasters (id, name) VALUES (?, ?)",
    ).bind("kbs", "KBS"),
    db.prepare(
      "INSERT OR IGNORE INTO channels (id, broadcaster_id, name, stn, ch) VALUES (?, ?, ?, ?, ?)",
    ).bind(`kbs.1radio.${suffix}`, "kbs", `KBS ${suffix}`, "kbs", "1radio"),
  ]);
}

beforeAll(async () => {
  const removeImagesIndex = testEnv.TEST_MIGRATIONS.findIndex((migration) =>
    migration.name.includes("remove_images"),
  );
  const previous = testEnv.TEST_MIGRATIONS.slice(0, removeImagesIndex);
  const removeImages = testEnv.TEST_MIGRATIONS.slice(removeImagesIndex);
  await applyMigrations(db, previous);
  await db.batch([
    db.prepare(
      "INSERT INTO sources (id, name, kind, base_url) VALUES (?, ?, ?, ?)",
    ).bind("legacy", "Legacy", "official", "https://legacy.example.test/"),
    db.prepare(
      `INSERT INTO image_assets (
         id, entity_type, entity_id, content_hash, source_url, source_page_url,
         first_verified_at, last_verified_at
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    ).bind(
      "a".repeat(64),
      "program",
      "legacy.program",
      "a".repeat(64),
      "https://legacy.example.test/image.png",
      "https://legacy.example.test/program",
      "2026-07-13T00:00:00Z",
      "2026-07-13T00:00:00Z",
    ),
    db.prepare(
      "INSERT INTO broadcasters (id, name, image_asset_id) VALUES (?, ?, ?)",
    ).bind("legacy", "Legacy", "a".repeat(64)),
    db.prepare(
      "INSERT INTO channels (id, broadcaster_id, name, stn, image_asset_id) VALUES (?, ?, ?, ?, ?)",
    ).bind("legacy.fm", "legacy", "Legacy FM", "legacy", "a".repeat(64)),
    db.prepare(
      "INSERT INTO programs (id, source_id, upstream_id, title, image_asset_id) VALUES (?, ?, ?, ?, ?)",
    ).bind("legacy.program", "legacy", "program", "Legacy Program", "a".repeat(64)),
    db.prepare(
      `INSERT INTO scrape_runs (
         id, source_id, idempotency_key, started_at, status, image_count
       ) VALUES (?, ?, ?, ?, ?, ?)`,
    ).bind("legacy-run", "legacy", "legacy-run", "2026-07-13T00:00:00Z", "succeeded", 1),
  ]);
  await applyMigrations(db, removeImages);
});

describe("schema migration", () => {
  it("creates only the core EPG tables and no image schema", async () => {
    const result = await db.prepare(
      "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
    ).all<{ name: string }>();

    expect(result.results.map(({ name }) => name)).toEqual(expect.arrayContaining(EXPECTED_TABLES));
    expect(result.results.map(({ name }) => name)).not.toEqual(
      expect.arrayContaining(["image_assets", "image_takedowns", "image_variants"]),
    );

    for (const table of ["broadcasters", "channels", "programs"]) {
      const columns = await db.prepare(`PRAGMA table_info(${table})`).all<{ name: string }>();
      expect(columns.results.map(({ name }) => name)).not.toContain("image_asset_id");
    }
    const runColumns = await db.prepare("PRAGMA table_info(scrape_runs)").all<{
      name: string;
    }>();
    expect(runColumns.results.map(({ name }) => name)).not.toContain("image_count");

    const preserved = await db.prepare(
      `SELECT
         (SELECT COUNT(*) FROM broadcasters WHERE id = 'legacy') AS broadcasters,
         (SELECT COUNT(*) FROM channels WHERE id = 'legacy.fm') AS channels,
         (SELECT COUNT(*) FROM programs WHERE id = 'legacy.program') AS programs,
         (SELECT COUNT(*) FROM scrape_runs WHERE id = 'legacy-run') AS runs`,
    ).first<{ broadcasters: number; channels: number; programs: number; runs: number }>();
    expect(preserved).toEqual({ broadcasters: 1, channels: 1, programs: 1, runs: 1 });
    const foreignKeys = await db.prepare("PRAGMA foreign_key_check").all();
    expect(foreignKeys.results).toEqual([]);
  });

  it("rejects duplicate aliases", async () => {
    await seedChannel("alias");
    const statement = db.prepare(
      "INSERT INTO channel_aliases (channel_id, alias_type, alias_value) VALUES (?, ?, ?)",
    ).bind("kbs.1radio.alias", "radio_id", "seoul-001-kbs-1radio-main");

    await statement.run();

    await expect(statement.run()).rejects.toThrow();
  });

  it("rejects schedules whose end does not follow their start", async () => {
    await seedChannel("duration");
    const statement = db.prepare(
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
    const statement = db.prepare(
      "INSERT INTO scrape_runs (id, source_id, idempotency_key, started_at, status) VALUES (?, ?, ?, ?, ?)",
    );
    await statement.bind("run-1", "kbs", "kbs-2026-07-13", "2026-07-13T01:00:00Z", "running").run();

    await expect(
      statement.bind("run-2", "kbs", "kbs-2026-07-13", "2026-07-13T02:00:00Z", "running").run(),
    ).rejects.toThrow();
  });

  it("uses the channel and start-time index for schedule lookup", async () => {
    const result = await db.prepare(
      "EXPLAIN QUERY PLAN SELECT * FROM schedule_events WHERE channel_id = ? AND starts_at >= ? ORDER BY starts_at",
    )
      .bind("kbs.1radio.main", "2026-07-13T00:00:00Z")
      .all<{ detail: string }>();

    expect(result.results.map(({ detail }) => detail).join(" ")).toContain(
      "idx_schedule_events_channel_starts",
    );
  });
});
