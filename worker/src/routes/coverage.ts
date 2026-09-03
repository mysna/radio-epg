import { Hono } from "hono";

import { edgeCachedJson } from "../cache";
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

coverage.get("/", async (context) =>
  // 집계는 schedule_events 전체를 훑는다. 수집은 하루 두 번뿐이라 5분마다 다시
  // 세면 같은 값을 얻으려고 전체 테이블을 수백 번 더 읽는다.
  edgeCachedJson(context, "public, max-age=3600", async () => {
    const result = await context.env.DB.prepare(
      `SELECT
         sources.id AS source_id,
         sources.name,
         sources.kind,
         sources.enabled,
         COALESCE(aggregate.event_count, 0) AS event_count,
         aggregate.last_fetched_at
       FROM sources
       LEFT JOIN (
         SELECT
           source_id,
           COUNT(*) AS event_count,
           MAX(fetched_at) AS last_fetched_at
         FROM schedule_events
         GROUP BY source_id
       ) AS aggregate ON aggregate.source_id = sources.id
       ORDER BY sources.id`,
    ).all<CoverageRow>();
    const now = new Date();

    return {
      sources: result.results.map((row) => ({
        source_id: row.source_id,
        name: row.name,
        kind: row.kind,
        enabled: row.enabled === 1,
        event_count: row.event_count,
        status: row.event_count > 0 ? "available" : "unavailable",
        last_fetched_at: row.last_fetched_at,
        stale: row.last_fetched_at ? isStale(row.last_fetched_at, now) : true,
      })),
    };
  }),
);

export default coverage;
