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
  broadcast_date: string;
}

// 진행 중 편성은 아무리 길어도 12시간 안에 시작했고, 다음 편성은 하루를 넘겨
// 비어 있지 않다. 이 두 경계로 조회 구간(start_offset 인덱스 범위)을 제한한다.
const LOOKBEHIND_SECONDS = 12 * 60 * 60;
const LOOKAHEAD_SECONDS = 24 * 60 * 60;
const DAY_MILLISECONDS = 24 * 60 * 60 * 1000;
const KST_OFFSET_MILLISECONDS = 9 * 60 * 60 * 1000;

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
    schedule_events.confidence,
    schedule_events.broadcast_date
`;

/** source fetch 시각이 freshness 허용 시간을 넘었는지 판단한다. */
export function isStale(fetchedAt: string, now: Date): boolean {
  const staleAfterMilliseconds = 24 * 60 * 60 * 1000;
  return now.getTime() - new Date(fetchedAt).getTime() > staleAfterMilliseconds;
}

function dateMilliseconds(date: string): number {
  return Date.parse(`${date}T00:00:00Z`);
}

/** YYYY-MM-DD의 요일. 0=일요일, schedule_events.weekday와 같은 규칙. */
export function weekdayOfDate(date: string): number {
  return new Date(dateMilliseconds(date)).getUTCDay();
}

function addDays(date: string, days: number): string {
  return new Date(dateMilliseconds(date) + days * DAY_MILLISECONDS).toISOString().slice(0, 10);
}

/** now가 속한 KST 달력 날짜. */
export function koreanDate(now: Date): string {
  return new Date(now.getTime() + KST_OFFSET_MILLISECONDS).toISOString().slice(0, 10);
}

/** 저장 형식(YYYY-MM-DDTHH:MM:SSZ)을 유지한 채 days일만큼 옮긴다. */
function shiftTimestamp(value: string, days: number): string {
  if (days === 0) {
    return value;
  }
  const shifted = new Date(Date.parse(value) + days * DAY_MILLISECONDS);
  return `${shifted.toISOString().slice(0, 19)}Z`;
}

/**
 * 요일 슬롯 편성을 요청한 날짜로 옮겨 공개 이벤트로 만든다. source.broadcast_date는
 * 실제로 수집한 방송일이라, 요청 날짜와 다르면 지난 같은 요일 편성을 재사용한 것이다.
 */
function toPublicEvent(row: ScheduleRow, targetDate: string, now: Date): PublicScheduleEvent {
  const days = Math.round(
    (dateMilliseconds(targetDate) - dateMilliseconds(row.broadcast_date)) / DAY_MILLISECONDS,
  );
  return {
    event_id: row.event_id,
    program_id: row.program_id,
    title: row.title,
    subtitle: row.subtitle,
    starts_at: shiftTimestamp(row.starts_at, days),
    ends_at: shiftTimestamp(row.ends_at, days),
    is_live: row.is_live === 1,
    is_rerun: row.is_rerun === 1,
    source: {
      id: row.source_id,
      url: row.source_url,
      kind: row.source_kind,
      fetched_at: row.fetched_at,
      confidence: row.confidence,
      stale: isStale(row.fetched_at, now),
      broadcast_date: row.broadcast_date,
    },
  };
}

/** 채널의 해당 요일 슬롯 편성을 요청 날짜로 옮겨 시작 시각 순서로 조회한다. */
export async function schedulesForDate(
  database: Database,
  channelId: string,
  broadcastDate: string,
  now: Date,
): Promise<PublicScheduleEvent[]> {
  const result = await database
    .prepare(
      `SELECT ${SCHEDULE_COLUMNS}
       FROM schedule_events
       WHERE schedule_events.channel_id = ? AND schedule_events.weekday = ?
       ORDER BY schedule_events.start_offset`,
    )
    .bind(channelId, weekdayOfDate(broadcastDate))
    .all<ScheduleRow>();
  return result.results.map((row) => toPublicEvent(row, broadcastDate, now));
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
 * 반복하면 요청 하나가 채널 수만큼 DB 조회를 일으킨다.
 *
 * 편성은 요일 슬롯이라, KST 어제·오늘·내일 각각의 요일 슬롯을 그 날짜로 옮겨
 * 본다(어제 방송일 편성이 자정을 넘겨 이어지기도 한다). 슬롯 안 위치는 방송일
 * 0시 기준 초(start_offset/end_offset)라서 날짜와 무관하게 인덱스 범위로 찾는다.
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

  const today = koreanDate(now);
  const targets = [-1, 0, 1].map((days, dayIndex) => {
    const date = addDays(today, days);
    const nowOffset = Math.floor(
      (now.getTime() - (dateMilliseconds(date) - KST_OFFSET_MILLISECONDS)) / 1000,
    );
    return {
      date,
      day_index: dayIndex,
      weekday: weekdayOfDate(date),
      now_offset: nowOffset,
      lower: nowOffset - LOOKBEHIND_SECONDS,
      upper: nowOffset + LOOKAHEAD_SECONDS,
    };
  });
  const result = await database
    .prepare(
      // target을 바깥 루프로 고정해 (channel_id, weekday, start_offset) 인덱스를
      // 구간 탐색으로 쓴다. 범위가 없으면 요일 슬롯 사흘치를 채널마다 전부 읽는다.
      `SELECT * FROM (
         SELECT
           schedule_events.channel_id,
           ${SCHEDULE_COLUMNS},
           json_extract(target.value, '$.date') AS target_date,
           ROW_NUMBER() OVER (
             PARTITION BY schedule_events.channel_id
             ORDER BY json_extract(target.value, '$.day_index') * 86400 + schedule_events.start_offset
           ) AS position
         FROM json_each(?2) AS target
         CROSS JOIN schedule_events
         WHERE schedule_events.channel_id IN (SELECT value FROM json_each(?1))
           AND schedule_events.weekday = json_extract(target.value, '$.weekday')
           AND schedule_events.start_offset >= json_extract(target.value, '$.lower')
           AND schedule_events.start_offset < json_extract(target.value, '$.upper')
           AND schedule_events.end_offset > json_extract(target.value, '$.now_offset')
       )
       WHERE position <= 2`,
    )
    .bind(JSON.stringify(channelIds), JSON.stringify(targets))
    .all<ScheduleRow & { channel_id: string; target_date: string }>();

  const timestamp = `${now.toISOString().slice(0, 19)}Z`;
  const byChannel = new Map<string, PublicScheduleEvent[]>();
  for (const row of result.results) {
    const events = byChannel.get(row.channel_id) ?? [];
    events.push(toPublicEvent(row, row.target_date, now));
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
