import asyncio
from datetime import UTC, date, datetime

import pytest

from radio_epg.cli import app_name, build_parser, publish_collection_batch
from radio_epg.models import (
    ImageCandidate,
    ImportBatch,
    ScheduleCandidate,
    SourceMetadata,
)


def test_app_name() -> None:
    assert app_name() == "radio-epg"


def test_cli_exposes_collection_commands() -> None:
    parser = build_parser()

    assert parser.parse_args(["collect", "--all"]).command == "collect"
    assert parser.parse_args(["collect", "--source", "kbs"]).source == "kbs"
    anchored = parser.parse_args(["collect", "--all", "--start-date", "2026-07-14"])
    assert anchored.start_date.isoformat() == "2026-07-14"
    assert parser.parse_args(["validate-fixtures"]).command == "validate-fixtures"
    assert parser.parse_args(["coverage"]).command == "coverage"
    coverage = parser.parse_args(["coverage", "--require-accounted", "--write", "report.md"])
    assert coverage.require_accounted is True
    assert str(coverage.write) == "report.md"
    smoke = parser.parse_args(["smoke", "--base-url", "https://epg.example.test"])
    assert smoke.radio_id == "busan-039-kbs-1radio-busan"


def _batch() -> ImportBatch:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    source = SourceMetadata(
        source_id="kbs",
        name="KBS",
        source_kind="official",
        source_url="https://schedule.kbs.co.kr/",
        priority=100,
        fetched_at=now,
    )
    return ImportBatch(
        idempotency_key="kbs:test",
        source=source,
        schedules=(
            ScheduleCandidate(
                source_id="kbs",
                source_url=source.source_url,
                source_kind="official",
                fetched_at=now,
                confidence=1,
                channel_id="kbs.1radio.main",
                broadcast_date=date(2026, 7, 14),
                starts_at=now,
                ends_at=datetime(2026, 7, 14, 1, tzinfo=UTC),
                title="뉴스",
            ),
        ),
        images=(
            ImageCandidate(
                entity_type="program",
                entity_id="kbs:news",
                source_url="https://images.example.test/news.png",
                source_page_url="https://schedule.kbs.co.kr/news",
            ),
        ),
        collected_at=now,
    )


def test_collection_batch_publishes_only_schedules_while_images_are_disabled() -> None:
    calls: list[tuple[str, object]] = []

    async def schedule_publisher(batch: ImportBatch, **_kwargs: object) -> dict[str, object]:
        calls.append(("schedule", batch))
        return {"status": "applied"}

    batch = _batch()
    result = asyncio.run(
        publish_collection_batch(
            batch,
            base_url="https://epg.example.test",
            token="token",
            schedule_publisher=schedule_publisher,
        )
    )

    assert calls == [("schedule", batch)]
    assert result == {"status": "applied"}


def test_collection_batch_does_not_publish_images_when_schedule_import_fails() -> None:
    async def schedule_publisher(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("schedule failed")

    with pytest.raises(RuntimeError, match="schedule failed"):
        asyncio.run(
            publish_collection_batch(
                _batch(),
                base_url="https://epg.example.test",
                token="token",
                schedule_publisher=schedule_publisher,
            )
        )
