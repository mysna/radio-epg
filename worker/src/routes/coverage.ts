import { Hono } from "hono";

import { cachedJson } from "../errors";
import { isStale } from "../repositories/schedules";
import type { AppEnv } from "../types";

interface CoverageRow {
  source_id: string;
  name: string;
  kind: string;
  enabled: number;
  event_count: number;
  last_fetched_at: string | null;
}

const coverage = new Hono<AppEnv>();

coverage.get("/", async (context) => {
  const result = await context.env.DB.prepare(
    `SELECT
       sources.id AS source_id,
       sources.name,
       sources.kind,
       sources.enabled,
       COUNT(schedule_events.id) AS event_count,
       MAX(schedule_events.fetched_at) AS last_fetched_at
     FROM sources
     LEFT JOIN schedule_events ON schedule_events.source_id = sources.id
     GROUP BY sources.id, sources.name, sources.kind, sources.enabled
     ORDER BY sources.id`,
  ).all<CoverageRow>();
  const now = new Date();
  const sources = result.results.map((row) => ({
    source_id: row.source_id,
    name: row.name,
    kind: row.kind,
    enabled: row.enabled === 1,
    event_count: row.event_count,
    status: row.event_count > 0 ? "available" : "unavailable",
    last_fetched_at: row.last_fetched_at,
    stale: row.last_fetched_at ? isStale(row.last_fetched_at, now) : true,
  }));

  return cachedJson(context, { sources }, "public, max-age=300");
});

export default coverage;
