-- 편성을 날짜가 아니라 요일 슬롯으로 보관한다. 같은 요일 편성을 새로 받으면
-- 그 요일의 기존 편성을 교체하고, 날짜로 조회하면 해당 요일 슬롯을 그 날짜로
-- 옮겨 돌려준다. 파생 값은 VIRTUAL 생성 컬럼이라 기존 행 backfill이나 import
-- 쪽 계산이 필요 없다.

-- 0=일요일 ... 6=토요일 (broadcast_date 기준)
ALTER TABLE schedule_events ADD COLUMN weekday INTEGER
  GENERATED ALWAYS AS (CAST(strftime('%w', broadcast_date) AS INTEGER)) VIRTUAL;

-- 방송일 KST 0시로부터의 초. 요일 슬롯을 다른 날짜로 옮겨도 값이 같아서
-- 날짜와 무관하게 인덱스 구간 탐색을 할 수 있다. (+32400 = KST UTC+9)
ALTER TABLE schedule_events ADD COLUMN start_offset INTEGER
  GENERATED ALWAYS AS (
    CAST(round((julianday(starts_at) - julianday(broadcast_date)) * 86400) AS INTEGER) + 32400
  ) VIRTUAL;
ALTER TABLE schedule_events ADD COLUMN end_offset INTEGER
  GENERATED ALWAYS AS (
    CAST(round((julianday(ends_at) - julianday(broadcast_date)) * 86400) AS INTEGER) + 32400
  ) VIRTUAL;

-- 조회(/v1/schedules, /v1/now)와 import 교체·retention 범위용 인덱스.
CREATE INDEX idx_schedule_events_channel_slot
  ON schedule_events(channel_id, weekday, start_offset);
CREATE INDEX idx_schedule_events_source_slot
  ON schedule_events(source_id, channel_id, weekday, broadcast_date);

-- 날짜 기반 조회·삭제에 쓰던 인덱스는 더 이상 쓰이지 않아 쓰기 비용만 남는다.
DROP INDEX IF EXISTS idx_schedule_events_channel_starts;
DROP INDEX IF EXISTS idx_schedule_events_channel_date;
DROP INDEX IF EXISTS idx_schedule_events_source_scope;
DROP INDEX IF EXISTS idx_schedule_events_broadcast_date;
