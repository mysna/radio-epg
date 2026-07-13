import { Hono } from "hono";

import { isAuthorized } from "./auth";
import type { Database } from "./db";
import { errorResponse } from "./errors";
import type { AppEnv } from "./types";

const KST_DATE_FORMATTER = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

export interface RetentionResult {
  start_date: string;
  end_date: string;
  deleted: number;
}

function koreanCalendarDate(now: Date): string {
  const parts = new Map(
    KST_DATE_FORMATTER.formatToParts(now).map((part) => [part.type, part.value]),
  );
  return `${parts.get("year")}-${parts.get("month")}-${parts.get("day")}`;
}

function nextCalendarDate(value: string): string {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

/** KST 오늘·내일 편성만 남기고 프로그램·이미지 메타데이터는 보존한다. */
export async function deleteExpiredScheduleEvents(
  database: Database,
  now: Date = new Date(),
): Promise<RetentionResult> {
  const startDate = koreanCalendarDate(now);
  const endDate = nextCalendarDate(startDate);
  const result = await database
    .prepare("DELETE FROM schedule_events WHERE broadcast_date < ? OR broadcast_date > ?")
    .bind(startDate, endDate)
    .run();
  return { start_date: startDate, end_date: endDate, deleted: result.meta.changes };
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
