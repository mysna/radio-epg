import { Hono } from "hono";

import { isAuthorized } from "./auth";
import type { Database } from "./db";
import { errorResponse } from "./errors";
import type { AppEnv } from "./types";

export interface RetentionResult {
  deleted: number;
}

/**
 * 요일 슬롯마다 가장 최근 방송일 편성만 남긴다. import가 같은 요일을 통째로
 * 교체하므로 평소에는 지울 것이 없고, 교체가 중간에 끊긴 경우를 정리하는
 * 안전장치다. 슬롯은 기간과 무관하게 새 편성이 올 때까지 유지한다.
 */
export async function deleteSupersededScheduleEvents(database: Database): Promise<RetentionResult> {
  // (source_id, channel_id, weekday, broadcast_date) 인덱스만으로 슬롯별 최신 날짜를 구한다.
  const result = await database
    .prepare(
      `DELETE FROM schedule_events
       WHERE rowid IN (
         SELECT stale.rowid
         FROM (
           SELECT source_id, channel_id, weekday, MAX(broadcast_date) AS latest_date
           FROM schedule_events
           GROUP BY source_id, channel_id, weekday
         ) AS slot
         JOIN schedule_events AS stale
           ON stale.source_id = slot.source_id
           AND stale.channel_id = slot.channel_id
           AND stale.weekday = slot.weekday
           AND stale.broadcast_date < slot.latest_date
       )`,
    )
    .run();
  return { deleted: result.meta.changes };
}

const retention = new Hono<AppEnv>();

retention.post("/", async (context) => {
  const token = context.env.INGEST_TOKEN;
  if (!token) {
    return errorResponse(context, 500, "ingest_not_configured", "Ingestion is not configured.");
  }
  if (!isAuthorized(context.req.header("Authorization"), token)) {
    return errorResponse(context, 401, "unauthorized", "A valid bearer token is required.");
  }

  try {
    const result = await deleteSupersededScheduleEvents(context.get("db"));
    return context.json({ status: "completed", ...result }, 200);
  } catch {
    return errorResponse(context, 500, "retention_failed", "Schedule retention could not run.");
  }
});

export default retention;
