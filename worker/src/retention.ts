import { Hono } from "hono";

import { isAuthorized } from "./auth";
import type { Database } from "./db";
import { errorResponse } from "./errors";
import type { AppEnv } from "./types";

const RETENTION_DAYS = 30;
const DAY_MILLISECONDS = 24 * 60 * 60 * 1000;

export interface RetentionResult {
  cutoff: string;
  deleted: number;
}

/** 종료 후 30일이 지난 편성만 지우고 참조된 프로그램·이미지 메타데이터는 보존한다. */
export async function deleteExpiredScheduleEvents(
  database: Database,
  now: Date = new Date(),
): Promise<RetentionResult> {
  const cutoff = new Date(now.getTime() - RETENTION_DAYS * DAY_MILLISECONDS).toISOString();
  const result = await database
    .prepare("DELETE FROM schedule_events WHERE ends_at < ?")
    .bind(cutoff)
    .run();
  return { cutoff, deleted: result.meta.changes };
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
    const result = await deleteExpiredScheduleEvents(context.env.DB);
    return context.json({ status: "completed", ...result }, 200);
  } catch {
    return errorResponse(context, 500, "retention_failed", "Schedule retention could not run.");
  }
});

export default retention;
