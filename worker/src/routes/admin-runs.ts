import { Hono } from "hono";

import { isAuthorized } from "../auth";
import { errorResponse } from "../errors";
import { runNoteSchema } from "../import-schema";
import type { AppEnv } from "../types";

const MAX_RUN_NOTE_BYTES = 10_000;
const adminRuns = new Hono<AppEnv>();

// 편성이 없어 import를 건너뛴 실행도 scrape_runs에 성공(event_count=0)으로 남긴다.
// error_summary에 메모를 담아 두면 /v1/coverage가 "편성표 없음"이 언제부터
// 이어졌는지 계산할 수 있다. 기존 편성은 건드리지 않는다.
adminRuns.post("/", async (context) => {
  const token = context.env.INGEST_TOKEN;
  if (!token) {
    return errorResponse(context, 500, "ingest_not_configured", "Ingestion is not configured.");
  }
  if (!isAuthorized(context.req.header("Authorization"), token)) {
    return errorResponse(context, 401, "unauthorized", "A valid bearer token is required.");
  }

  const rawBody = await context.req.text();
  if (new TextEncoder().encode(rawBody).byteLength > MAX_RUN_NOTE_BYTES) {
    return errorResponse(context, 413, "request_too_large", "Run note body is too large.");
  }
  let parsedJson: unknown;
  try {
    parsedJson = JSON.parse(rawBody);
  } catch {
    return errorResponse(context, 400, "invalid_run_note", "Run note body must be valid JSON.");
  }
  const parsed = runNoteSchema.safeParse(parsedJson);
  if (!parsed.success) {
    return errorResponse(context, 400, "invalid_run_note", "Run note does not match the schema.");
  }

  const note = parsed.data;
  const db = context.get("db");
  const [, inserted] = await db.batch([
    db
      .prepare(
        `INSERT INTO sources (id, name, kind, base_url, priority, updated_at)
         VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
         ON CONFLICT(id) DO UPDATE SET
           name = excluded.name,
           kind = excluded.kind,
           base_url = excluded.base_url,
           priority = excluded.priority,
           updated_at = CURRENT_TIMESTAMP`,
      )
      .bind(
        note.source.source_id,
        note.source.name,
        note.source.source_kind,
        note.source.source_url,
        note.source.priority,
      ),
    db
      .prepare(
        `INSERT INTO scrape_runs (
           id, source_id, idempotency_key, started_at, finished_at, status,
           channel_count, program_count, event_count, error_summary
         ) VALUES (?, ?, ?, ?, ?, 'succeeded', 0, 0, 0, ?)
         ON CONFLICT(idempotency_key) DO NOTHING`,
      )
      .bind(
        `note:${note.idempotency_key}`,
        note.source.source_id,
        note.idempotency_key,
        note.started_at,
        note.finished_at,
        note.note,
      ),
  ]);

  const applied = (inserted?.meta?.changes ?? 0) > 0;
  return context.json(
    { status: applied ? "applied" : "already_applied", idempotency_key: note.idempotency_key },
    applied ? 201 : 200,
  );
});

export default adminRuns;
