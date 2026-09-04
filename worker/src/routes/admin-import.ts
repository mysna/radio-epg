import { Hono } from "hono";

import { isAuthorized } from "../auth";
import type { Database, DatabaseStatement } from "../db";
import { errorResponse } from "../errors";
import {
  importBatchSchema,
  type ImportBatchInput,
  type ImportScheduleInput,
} from "../import-schema";
import type { AppEnv } from "../types";

const MAX_IMPORT_BYTES = 1_000_000;
const adminImport = new Hono<AppEnv>();

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function tupleAlias(channel: ImportBatchInput["channels"][number]): string {
  return `${channel.stn}/${channel.ch ?? "main"}/${channel.city ?? "main"}`;
}

async function eventIdentity(event: ImportScheduleInput): Promise<string> {
  const upstreamIdentity = event.source_event_id
    ? `${event.source_id}:${event.source_event_id}`
    : [
        event.source_id,
        event.channel_id,
        event.broadcast_date,
        event.starts_at,
        event.title,
      ].join("|");
  return sha256(upstreamIdentity);
}

export async function buildImportStatements(
  database: Database,
  batch: ImportBatchInput,
  payloadHash: string,
): Promise<DatabaseStatement[]> {
  const broadcasters = Array.from(
    new Set(batch.channels.map((channel) => channel.broadcaster_id)),
    (id) => ({ id, name: batch.source.name }),
  );
  const channels = batch.channels.map((channel) => ({
    id: channel.channel_id,
    broadcaster_id: channel.broadcaster_id,
    name: channel.name,
    region_id: channel.region_ids[0] ?? null,
    stn: channel.stn,
    ch: channel.ch ?? null,
    city: channel.city ?? null,
  }));
  const aliases = batch.channels.flatMap((channel) => [
    ...channel.radio_ids.map((value) => ({
      channel_id: channel.channel_id,
      alias_type: "radio_id",
      alias_value: value,
    })),
    {
      channel_id: channel.channel_id,
      alias_type: "tuple",
      alias_value: tupleAlias(channel),
    },
  ]);
  const programs = batch.programs.map((program) => ({
    id: program.program_id,
    source_id: program.source_id,
    upstream_id: program.program_id,
    title: program.title,
    description: program.description ?? null,
    hosts_json: JSON.stringify(program.hosts),
    genre: program.genre ?? null,
    homepage_url: program.homepage_url ?? null,
  }));
  const scopeKeys = new Set<string>();
  const scopes: Array<{ source_id: string; channel_id: string; broadcast_date: string }> = [];
  for (const event of batch.schedules) {
    const key = `${event.source_id}\u0000${event.channel_id}\u0000${event.broadcast_date}`;
    if (!scopeKeys.has(key)) {
      scopeKeys.add(key);
      scopes.push({
        source_id: event.source_id,
        channel_id: event.channel_id,
        broadcast_date: event.broadcast_date,
      });
    }
  }
  const events = await Promise.all(
    batch.schedules.map(async (event) => {
      const identity = await eventIdentity(event);
      return {
        id: identity,
        event_key: identity,
        channel_id: event.channel_id,
        program_id: event.program_id ?? null,
        source_id: event.source_id,
        source_event_id: event.source_event_id ?? null,
        broadcast_date: event.broadcast_date,
        starts_at: event.starts_at,
        ends_at: event.ends_at,
        title: event.title,
        subtitle: event.subtitle ?? null,
        is_live: event.is_live ? 1 : 0,
        is_rerun: event.is_rerun ? 1 : 0,
        confidence: event.confidence,
        source_url: event.source_url,
        source_kind: event.source_kind,
        fetched_at: event.fetched_at,
      };
    }),
  );

  return [
    database
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
        batch.source.source_id,
        batch.source.name,
        batch.source.source_kind,
        batch.source.source_url,
        batch.source.priority,
      ),
    database
      .prepare(
        `INSERT INTO broadcasters (id, name, updated_at)
         SELECT json_extract(value, '$.id'), json_extract(value, '$.name'), CURRENT_TIMESTAMP
         FROM json_each(?)
         WHERE true
         ON CONFLICT(id) DO UPDATE SET
           name = excluded.name,
           updated_at = CURRENT_TIMESTAMP`,
      )
      .bind(JSON.stringify(broadcasters)),
    database
      .prepare(
        `INSERT INTO channels (
           id, broadcaster_id, name, region_id, stn, ch, city, updated_at
         )
         SELECT
           json_extract(value, '$.id'),
           json_extract(value, '$.broadcaster_id'),
           json_extract(value, '$.name'),
           json_extract(value, '$.region_id'),
           json_extract(value, '$.stn'),
           json_extract(value, '$.ch'),
           json_extract(value, '$.city'),
           CURRENT_TIMESTAMP
         FROM json_each(?)
         WHERE true
         ON CONFLICT(id) DO UPDATE SET
           broadcaster_id = excluded.broadcaster_id,
           name = excluded.name,
           region_id = excluded.region_id,
           stn = excluded.stn,
           ch = excluded.ch,
           city = excluded.city,
           active = 1,
           updated_at = CURRENT_TIMESTAMP`,
      )
      .bind(JSON.stringify(channels)),
    database
      .prepare(
        `INSERT INTO channel_aliases (channel_id, alias_type, alias_value)
         SELECT
           json_extract(value, '$.channel_id'),
           json_extract(value, '$.alias_type'),
           json_extract(value, '$.alias_value')
         FROM json_each(?)
         WHERE true
         ON CONFLICT(alias_type, alias_value) DO NOTHING`,
      )
      .bind(JSON.stringify(aliases)),
    database
      .prepare(
        `INSERT INTO programs (
           id, source_id, upstream_id, title, description, hosts_json, genre, homepage_url, updated_at
         )
         SELECT
           json_extract(value, '$.id'),
           json_extract(value, '$.source_id'),
           json_extract(value, '$.upstream_id'),
           json_extract(value, '$.title'),
           json_extract(value, '$.description'),
           json_extract(value, '$.hosts_json'),
           json_extract(value, '$.genre'),
           json_extract(value, '$.homepage_url'),
           CURRENT_TIMESTAMP
         FROM json_each(?)
         WHERE true
         ON CONFLICT(id) DO UPDATE SET
           title = excluded.title,
           description = excluded.description,
           hosts_json = excluded.hosts_json,
           genre = excluded.genre,
           homepage_url = excluded.homepage_url,
           updated_at = CURRENT_TIMESTAMP`,
      )
      .bind(JSON.stringify(programs)),
    database
      .prepare(
        // json_each를 바깥 루프로 두어 scope 인덱스로만 대상 행을 찾고,
        // 이번 배치에 다시 등장하는 이벤트는 남겨 재삽입 쓰기를 피한다.
        `DELETE FROM schedule_events
         WHERE rowid IN (
           SELECT scoped.rowid
           FROM json_each(?1) AS scope
           JOIN schedule_events AS scoped
             ON scoped.source_id = json_extract(scope.value, '$.source_id')
             AND scoped.channel_id = json_extract(scope.value, '$.channel_id')
             AND scoped.broadcast_date = json_extract(scope.value, '$.broadcast_date')
           WHERE scoped.id NOT IN (SELECT value FROM json_each(?2))
         )`,
      )
      .bind(JSON.stringify(scopes), JSON.stringify(events.map((event) => event.id))),
    database
      .prepare(
        `INSERT INTO schedule_events (
           id, event_key, channel_id, program_id, source_id, source_event_id,
           broadcast_date, starts_at, ends_at, title, subtitle, is_live, is_rerun,
           confidence, source_url, source_kind, fetched_at
         )
         SELECT
           json_extract(value, '$.id'),
           json_extract(value, '$.event_key'),
           json_extract(value, '$.channel_id'),
           json_extract(value, '$.program_id'),
           json_extract(value, '$.source_id'),
           json_extract(value, '$.source_event_id'),
           json_extract(value, '$.broadcast_date'),
           json_extract(value, '$.starts_at'),
           json_extract(value, '$.ends_at'),
           json_extract(value, '$.title'),
           json_extract(value, '$.subtitle'),
           json_extract(value, '$.is_live'),
           json_extract(value, '$.is_rerun'),
           json_extract(value, '$.confidence'),
           json_extract(value, '$.source_url'),
           json_extract(value, '$.source_kind'),
           json_extract(value, '$.fetched_at')
         FROM json_each(?)
         WHERE true
         ON CONFLICT(id) DO UPDATE SET
           channel_id = excluded.channel_id,
           program_id = excluded.program_id,
           source_id = excluded.source_id,
           source_event_id = excluded.source_event_id,
           broadcast_date = excluded.broadcast_date,
           starts_at = excluded.starts_at,
           ends_at = excluded.ends_at,
           title = excluded.title,
           subtitle = excluded.subtitle,
           is_live = excluded.is_live,
           is_rerun = excluded.is_rerun,
           confidence = excluded.confidence,
           source_url = excluded.source_url,
           source_kind = excluded.source_kind,
           fetched_at = excluded.fetched_at,
           updated_at = CURRENT_TIMESTAMP
         WHERE
           schedule_events.starts_at IS NOT excluded.starts_at
           OR schedule_events.ends_at IS NOT excluded.ends_at
           OR schedule_events.title IS NOT excluded.title
           OR schedule_events.subtitle IS NOT excluded.subtitle
           OR schedule_events.program_id IS NOT excluded.program_id
           OR schedule_events.source_event_id IS NOT excluded.source_event_id
           OR schedule_events.is_live IS NOT excluded.is_live
           OR schedule_events.is_rerun IS NOT excluded.is_rerun
           OR schedule_events.confidence IS NOT excluded.confidence
           OR schedule_events.source_url IS NOT excluded.source_url
           OR schedule_events.source_kind IS NOT excluded.source_kind`,
      )
      .bind(JSON.stringify(events)),
    database
      .prepare(
        `INSERT INTO scrape_runs (
           id, source_id, idempotency_key, payload_hash, started_at, finished_at, status,
           channel_count, program_count, event_count
         ) VALUES (?, ?, ?, ?, ?, ?, 'succeeded', ?, ?, ?)`,
      )
      .bind(
        `import:${batch.idempotency_key}`,
        batch.source.source_id,
        batch.idempotency_key,
        payloadHash,
        batch.collected_at,
        batch.collected_at,
        batch.channels.length,
        batch.programs.length,
        batch.schedules.length,
      ),
  ];
}

async function findImport(
  database: Database,
  idempotencyKey: string,
): Promise<{ payload_hash: string | null } | null> {
  return database
    .prepare("SELECT payload_hash FROM scrape_runs WHERE idempotency_key = ?")
    .bind(idempotencyKey)
    .first<{ payload_hash: string | null }>();
}

adminImport.post("/", async (context) => {
  const token = context.env.INGEST_TOKEN;
  if (!token) {
    return errorResponse(context, 500, "ingest_not_configured", "Ingestion is not configured.");
  }
  if (!isAuthorized(context.req.header("Authorization"), token)) {
    return errorResponse(context, 401, "unauthorized", "A valid bearer token is required.");
  }

  const contentLength = Number(context.req.header("Content-Length") ?? 0);
  if (contentLength > MAX_IMPORT_BYTES) {
    return errorResponse(context, 413, "request_too_large", "Import body exceeds one megabyte.");
  }
  const rawBody = await context.req.text();
  if (new TextEncoder().encode(rawBody).byteLength > MAX_IMPORT_BYTES) {
    return errorResponse(context, 413, "request_too_large", "Import body exceeds one megabyte.");
  }

  let parsedJson: unknown;
  try {
    parsedJson = JSON.parse(rawBody);
  } catch {
    return errorResponse(context, 400, "invalid_import", "Import body must be valid JSON.");
  }
  const parsed = importBatchSchema.safeParse(parsedJson);
  if (!parsed.success) {
    return errorResponse(context, 400, "invalid_import", "Import body does not match the schema.");
  }

  const payloadHash = await sha256(JSON.stringify(parsed.data));
  const db = context.get("db");
  const existing = await findImport(db, parsed.data.idempotency_key);
  if (existing) {
    if (existing.payload_hash === payloadHash) {
      return context.json(
        { status: "already_applied", idempotency_key: parsed.data.idempotency_key },
        200,
      );
    }
    return errorResponse(
      context,
      409,
      "idempotency_conflict",
      "The idempotency key was already used for a different payload.",
    );
  }

  try {
    const statements = await buildImportStatements(db, parsed.data, payloadHash);
    await db.batch(statements);
  } catch {
    const concurrent = await findImport(db, parsed.data.idempotency_key);
    if (concurrent?.payload_hash === payloadHash) {
      return context.json(
        { status: "already_applied", idempotency_key: parsed.data.idempotency_key },
        200,
      );
    }
    return errorResponse(context, 500, "import_failed", "The import could not be applied.");
  }

  return context.json(
    {
      status: "applied",
      idempotency_key: parsed.data.idempotency_key,
      event_count: parsed.data.schedules.length,
    },
    201,
  );
});

export default adminImport;
