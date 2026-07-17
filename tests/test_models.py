from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from radio_epg.models import (
    AdapterResult,
    Channel,
    ImportBatch,
    ProgramCandidate,
    ScheduleCandidate,
    SourceMetadata,
)

KST = ZoneInfo("Asia/Seoul")
FETCHED_AT = datetime(2026, 7, 13, 12, tzinfo=KST)


def _schedule(
    *,
    starts_at: datetime,
    ends_at: datetime,
    title: str = "KBS 뉴스",
    source_id: str = "kbs",
) -> ScheduleCandidate:
    return ScheduleCandidate(
        source_id=source_id,
        source_url="https://schedule.kbs.co.kr/",
        source_kind="official",
        fetched_at=FETCHED_AT,
        confidence=1.0,
        channel_id="kbs.1radio.main",
        broadcast_date=date(2026, 7, 13),
        starts_at=starts_at,
        ends_at=ends_at,
        title=title,
    )


@pytest.mark.parametrize("duration", [timedelta(0), timedelta(minutes=-1)])
def test_schedule_rejects_non_positive_duration(duration: timedelta) -> None:
    starts_at = datetime(2026, 7, 13, 12, tzinfo=KST)

    with pytest.raises(ValidationError, match="ends_at"):
        _schedule(starts_at=starts_at, ends_at=starts_at + duration)


def test_schedule_rejects_empty_title() -> None:
    with pytest.raises(ValidationError, match="title"):
        _schedule(
            starts_at=datetime(2026, 7, 13, 12, tzinfo=KST),
            ends_at=datetime(2026, 7, 13, 13, tzinfo=KST),
            title="   ",
        )


def test_schedule_rejects_naive_datetimes() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        _schedule(
            starts_at=datetime(2026, 7, 13, 12),
            ends_at=datetime(2026, 7, 13, 13),
        )


def test_domain_models_compose_an_adapter_result() -> None:
    channel = Channel(
        channel_id="kbs.1radio.main",
        broadcaster_id="kbs",
        name="KBS 1라디오",
        stn="kbs",
        ch="1radio",
    )
    program = ProgramCandidate(source_id="kbs", program_id="news", title="KBS 뉴스")
    source = SourceMetadata(
        source_id="kbs",
        name="KBS 편성표",
        source_kind="official",
        source_url="https://schedule.kbs.co.kr/",
        priority=100,
        fetched_at=FETCHED_AT,
    )
    schedule = _schedule(
        starts_at=datetime(2026, 7, 13, 12, tzinfo=KST),
        ends_at=datetime(2026, 7, 13, 13, tzinfo=KST),
    )

    result = AdapterResult(
        source=source,
        channels=(channel,),
        programs=(program,),
        schedules=(schedule,),
    )

    assert result.channels[0].channel_id == "kbs.1radio.main"
    assert result.programs[0].title == "KBS 뉴스"
    assert "images" not in result.model_dump()


def test_import_batch_serializes_instants_as_utc_and_keeps_broadcast_date() -> None:
    source = SourceMetadata(
        source_id="kbs",
        name="KBS 편성표",
        source_kind="official",
        source_url="https://schedule.kbs.co.kr/",
        priority=100,
        fetched_at=FETCHED_AT,
    )
    schedule = _schedule(
        starts_at=datetime(2026, 7, 14, 1, 30, tzinfo=KST),
        ends_at=datetime(2026, 7, 14, 2, tzinfo=KST),
    )
    batch = ImportBatch(
        idempotency_key="kbs-2026-07-13",
        source=source,
        schedules=(schedule,),
        collected_at=datetime(2026, 7, 13, 13, tzinfo=KST),
    )

    serialized = batch.model_dump(mode="json")

    assert "images" not in serialized
    assert serialized["schedules"][0]["starts_at"] == "2026-07-13T16:30:00Z"
    assert serialized["schedules"][0]["broadcast_date"] == "2026-07-13"
    assert datetime.fromisoformat(serialized["collected_at"]).tzinfo == UTC
