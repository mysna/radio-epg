from datetime import date

import pytest

from radio_epg.broadcast_time import parse_broadcast_interval, parse_broadcast_time


def test_extended_hour_preserves_broadcast_date() -> None:
    parsed = parse_broadcast_time(date(2026, 7, 13), "25:30")

    assert parsed.isoformat() == "2026-07-14T01:30:00+09:00"


def test_interval_end_crosses_midnight() -> None:
    starts_at, ends_at = parse_broadcast_interval(date(2026, 7, 13), "23:30", "00:30")

    assert starts_at.isoformat() == "2026-07-13T23:30:00+09:00"
    assert ends_at.isoformat() == "2026-07-14T00:30:00+09:00"


def test_interval_preserves_equal_times_for_duration_validation() -> None:
    starts_at, ends_at = parse_broadcast_interval(date(2026, 7, 13), "10:00", "10:00")

    assert ends_at == starts_at


def test_broadcast_time_rejects_invalid_minutes() -> None:
    with pytest.raises(ValueError, match="minute"):
        parse_broadcast_time(date(2026, 7, 13), "24:60")
