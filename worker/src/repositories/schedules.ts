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
}

export interface CurrentAndNext {
  current: PublicScheduleEvent | null;
  next: PublicScheduleEvent | null;
}

const SCHEDULE_COLUMNS = `
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
    schedule_events.confidence
`;

const SCHEDULE_SELECT = `
  SELECT ${SCHEDULE_COLUMNS}
  FROM schedule_events
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
): Promise<CurrentAndNext> {
  const schedules = await currentAndNextForChannels(database, [channelId], now);
  return schedules.get(channelId) ?? { current: null, next: null };
}

/**
 * 여러 채널의 현재·다음 편성을 한 번의 질의로 조회한다. 채널마다 질의를
 * 반복하면 요청 하나가 채널 수만큼 D1 조회를 일으킨다.
 */
export async function currentAndNextForChannels(
  database: Database,
  channelIds: string[],
  now: Date,
): Promise<Map<string, CurrentAndNext>> {
  const schedules = new Map<string, CurrentAndNext>();
  if (channelIds.length === 0) {
    return schedules;
  }

  const timestamp = now.toISOString();
  const result = await database
    .prepare(
      `SELECT * FROM (
         SELECT
           schedule_events.channel_id,
           ${SCHEDULE_COLUMNS},
           ROW_NUMBER() OVER (
             PARTITION BY schedule_events.channel_id ORDER BY schedule_events.starts_at
           ) AS position
         FROM schedule_events
         WHERE schedule_events.channel_id IN (SELECT value FROM json_each(?1))
           AND schedule_events.ends_at > ?2
       )
       WHERE position <= 2`,
    )
    .bind(JSON.stringify(channelIds), timestamp)
    .all<ScheduleRow & { channel_id: string }>();

  const byChannel = new Map<string, PublicScheduleEvent[]>();
  for (const row of result.results) {
    const events = byChannel.get(row.channel_id) ?? [];
    events.push(toPublicEvent(row, now));
    byChannel.set(row.channel_id, events);
  }

  for (const [channelId, events] of byChannel) {
    schedules.set(channelId, {
      current: events.find((event) => event.starts_at <= timestamp && timestamp < event.ends_at) ?? null,
      next: events.find((event) => event.starts_at > timestamp) ?? null,
    });
  }
  return schedules;
}
