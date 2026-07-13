from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from radio_epg.models import ScheduleCandidate
from radio_epg.validation import SchedulePolicy, ScheduleValidationError, validate_schedule

KST = ZoneInfo("Asia/Seoul")


def _event(
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
    *,
    source_id: str = "kbs",
) -> ScheduleCandidate:
    return ScheduleCandidate(
        source_id=source_id,
        source_url="https://schedule.example.test/",
        source_kind="official",
        fetched_at=datetime(2026, 7, 13, 4, tzinfo=KST),
        confidence=1.0,
        channel_id="kbs.1radio.main",
        broadcast_date=date(2026, 7, 13),
        starts_at=datetime(2026, 7, 13, start_hour, start_minute, tzinfo=KST),
        ends_at=datetime(2026, 7, 13, end_hour, end_minute, tzinfo=KST),
        title=f"{start_hour:02d}:{start_minute:02d} 프로그램",
    )


def test_conflicting_overlap_from_one_source_is_rejected() -> None:
    events = [_event(10, 0, 11, 0), _event(10, 30, 11, 30)]

    with pytest.raises(ScheduleValidationError, match="overlap"):
        validate_schedule(events)


def test_nested_events_require_adapter_declaration() -> None:
    events = [_event(10, 0, 12, 0), _event(10, 30, 11, 0)]

    with pytest.raises(ScheduleValidationError, match="nested"):
        validate_schedule(events)

    validate_schedule(events, policy=SchedulePolicy(allow_nested=True))


def test_adjacent_events_require_adapter_declaration() -> None:
    events = [_event(10, 0, 11, 0), _event(11, 0, 12, 0)]

    with pytest.raises(ScheduleValidationError, match="adjacent"):
        validate_schedule(events)

    validate_schedule(events, policy=SchedulePolicy(allow_adjacent=True))


def test_different_sources_may_overlap() -> None:
    events = [
        _event(10, 0, 11, 0, source_id="kbs"),
        _event(10, 30, 11, 30, source_id="fallback"),
    ]

    validate_schedule(events)
