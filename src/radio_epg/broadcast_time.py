"""한국 방송일 기준 시각을 시간대가 있는 실제 시각으로 변환한다."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def _parse_clock(value: str) -> tuple[int, int]:
    """`HH:MM` 방송 시각을 확장 시간과 분으로 분리한다."""
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError(f"Broadcast time must use HH:MM: {value!r}")

    hour, minute = (int(part) for part in parts)
    if hour > 47:
        raise ValueError(f"Broadcast hour must be between 0 and 47: {hour}")
    if minute > 59:
        raise ValueError(f"Broadcast minute must be between 0 and 59: {minute}")
    return hour, minute


def parse_broadcast_time(broadcast_date: date, value: str) -> datetime:
    """방송일과 확장 시각을 Asia/Seoul 기준 datetime으로 변환한다."""
    hour, minute = _parse_clock(value)
    midnight = datetime.combine(broadcast_date, time.min, tzinfo=KST)
    return midnight + timedelta(hours=hour, minutes=minute)


def parse_broadcast_interval(
    broadcast_date: date,
    start_value: str,
    end_value: str,
) -> tuple[datetime, datetime]:
    """자정을 넘는 종료 시각을 다음 날로 넘겨 방송 구간을 만든다."""
    starts_at = parse_broadcast_time(broadcast_date, start_value)
    ends_at = parse_broadcast_time(broadcast_date, end_value)
    while ends_at < starts_at:
        ends_at += timedelta(days=1)
    return starts_at, ends_at
