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

const COVERAGE_MAX_AGE = 300;
const COVERAGE_CACHE_CONTROL = `public, max-age=${COVERAGE_MAX_AGE}`;

const coverage = new Hono<AppEnv>();

/** WebWorker lib의 CacheStorage 타입에는 없는 Cloudflare 기본 캐시를 가져온다. */
function edgeCache(): Cache {
  return (caches as unknown as { default: Cache }).default;
}

/** 질의 문자열과 무관하게 하나의 캐시 항목만 쓰도록 키를 정규화한다. */
function coverageCacheKey(requestUrl: string): Request {
  const url = new URL(requestUrl);
  url.search = "";
  return new Request(url.toString(), { method: "GET" });
}

function notModified(response: Response, ifNoneMatch: string | undefined): Response | null {
  const etag = response.headers.get("ETag");
  if (!etag || ifNoneMatch !== etag) {
    return null;
  }
  return new Response(null, { status: 304, headers: response.headers });
}

coverage.get("/", async (context) => {
  const cache = edgeCache();
  const cacheKey = coverageCacheKey(context.req.url);
  const ifNoneMatch = context.req.header("If-None-Match");

  // 집계는 schedule_events 전체를 훑으므로 요청마다 반복하지 않고 edge cache에 담는다.
  const cached = await cache.match(cacheKey);
  if (cached) {
    return notModified(cached, ifNoneMatch) ?? cached;
  }

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

  const response = await cachedJson(context, { sources }, COVERAGE_CACHE_CONTROL);
  if (response.status === 200) {
    await cache.put(cacheKey, response.clone());
  }
  return response;
});

export default coverage;
