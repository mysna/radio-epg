import type { Database } from "../db";
import type { PublicScheduleEvent } from "../types";

interface ScheduleRow {
  event_id: string;
  program_id: string | null;
  title: string;
  subtitle: string | null;
  starts_at: string;
  ends_at: string;
  is_live: number;
  is_rerun: number;
  source_id: string;
  source_url: string;
  source_kind: string;
  fetched_at: string;
  confidence: number;
  program_image_asset_id: string | null;
}

const SCHEDULE_SELECT = `
  SELECT
    schedule_events.id AS event_id,
    schedule_events.program_id,
    schedule_events.title,
    schedule_events.subtitle,
    schedule_events.starts_at,
    schedule_events.ends_at,
    schedule_events.is_live,
    schedule_events.is_rerun,
    schedule_events.source_id,
    schedule_events.source_url,
    schedule_events.source_kind,
    schedule_events.fetched_at,
    schedule_events.confidence,
    programs.image_asset_id AS program_image_asset_id
  FROM schedule_events
  LEFT JOIN programs ON programs.id = schedule_events.program_id
`;

/** source fetch 시각이 freshness 허용 시간을 넘었는지 판단한다. */
export function isStale(fetchedAt: string, now: Date): boolean {
  const staleAfterMilliseconds = 24 * 60 * 60 * 1000;
  return now.getTime() - new Date(fetchedAt).getTime() > staleAfterMilliseconds;
}

function toPublicEvent(row: ScheduleRow, now: Date): PublicScheduleEvent {
  return {
    event_id: row.event_id,
    program_id: row.program_id,
    title: row.title,
    subtitle: row.subtitle,
    starts_at: row.starts_at,
    ends_at: row.ends_at,
    is_live: row.is_live === 1,
    is_rerun: row.is_rerun === 1,
    program_image_url: row.program_image_asset_id
      ? `/v1/images/${row.program_image_asset_id}/medium`
      : null,
    source: {
      id: row.source_id,
      url: row.source_url,
      kind: row.source_kind,
      fetched_at: row.fetched_at,
      confidence: row.confidence,
      stale: isStale(row.fetched_at, now),
    },
  };
}

/** 채널과 방송일에 해당하는 편성을 시작 시각 순서로 조회한다. */
export async function schedulesForDate(
  database: Database,
  channelId: string,
  broadcastDate: string,
  now: Date,
): Promise<PublicScheduleEvent[]> {
  const result = await database
    .prepare(
      `${SCHEDULE_SELECT}
       WHERE schedule_events.channel_id = ? AND schedule_events.broadcast_date = ?
       ORDER BY schedule_events.starts_at`,
    )
    .bind(channelId, broadcastDate)
    .all<ScheduleRow>();
  return result.results.map((row) => toPublicEvent(row, now));
}

/** 현재 진행 중인 이벤트와 다음 이벤트를 index 기반으로 조회한다. */
export async function currentAndNext(
  database: Database,
  channelId: string,
  now: Date,
): Promise<{ current: PublicScheduleEvent | null; next: PublicScheduleEvent | null }> {
  const timestamp = now.toISOString();
  const result = await database
    .prepare(
      `${SCHEDULE_SELECT}
       WHERE schedule_events.channel_id = ? AND schedule_events.ends_at > ?
       ORDER BY schedule_events.starts_at
       LIMIT 2`,
    )
    .bind(channelId, timestamp)
    .all<ScheduleRow>();
  const events = result.results.map((row) => toPublicEvent(row, now));
  const current = events.find((event) => event.starts_at <= timestamp && timestamp < event.ends_at) ?? null;
  const next = events.find((event) => event.starts_at > timestamp) ?? null;
  return { current, next };
}
