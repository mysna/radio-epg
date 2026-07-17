import asyncio
from datetime import UTC, date, datetime, timedelta

import httpx

import radio_epg.collector as collector_module
from radio_epg.adapters.base import CollectionWindow
from radio_epg.broadcast_time import KST
from radio_epg.collector import Collector
from radio_epg.config import SourceConfig
from radio_epg.models import AdapterResult, ImportBatch, ScheduleCandidate, SourceMetadata
from radio_epg.publisher import PublishError


def _source_config(source_id: str) -> SourceConfig:
    return SourceConfig(
        source_id=source_id,
        name=f"{source_id.upper()} 편성표",
        source_kind="official",
        source_url=f"https://{source_id}.example.test/",
        priority=100,
        adapter="fake",
    )


def _result(source_id: str, *, schedules: tuple[ScheduleCandidate, ...]) -> AdapterResult:
    return AdapterResult(
        source=SourceMetadata(
            source_id=source_id,
            name=f"{source_id.upper()} 편성표",
            source_kind="official",
            source_url=f"https://{source_id}.example.test/",
            priority=100,
            fetched_at=datetime(2026, 7, 13, 1, tzinfo=UTC),
        ),
        schedules=schedules,
    )


def _event(
    source_id: str,
    *,
    starts_at: datetime,
    ends_at: datetime,
    title: str = "아침 뉴스",
) -> ScheduleCandidate:
    return ScheduleCandidate(
        source_id=source_id,
        source_url=f"https://{source_id}.example.test/",
        source_kind="official",
        fetched_at=datetime(2026, 7, 13, 1, tzinfo=UTC),
        confidence=1,
        channel_id=f"{source_id}.fm.main",
        broadcast_date=date(2026, 7, 13),
        starts_at=starts_at,
        ends_at=ends_at,
        title=title,
    )


class FakeAdapter:
    def __init__(self, source_id: str, outcome: AdapterResult | Exception) -> None:
        self.source = _source_config(source_id)
        self.outcome = outcome
        self.windows: list[CollectionWindow] = []

    async def collect(self, window: CollectionWindow) -> AdapterResult:
        self.windows.append(window)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakePublisher:
    def __init__(self) -> None:
        self.batches: list[ImportBatch] = []

    async def __call__(self, batch: ImportBatch) -> dict[str, str]:
        self.batches.append(batch)
        return {"status": "applied"}


def test_default_collection_window_uses_korean_broadcast_date(monkeypatch) -> None:
    class FrozenDateTime:
        @classmethod
        def now(cls, timezone):
            assert timezone is KST
            return datetime(2030, 1, 1, 0, 15, tzinfo=KST)

    monkeypatch.setattr(collector_module, "datetime", FrozenDateTime)
    start = datetime(2030, 1, 1, 1, tzinfo=UTC)
    schedule = _event("healthy", starts_at=start, ends_at=start + timedelta(hours=1))
    adapter = FakeAdapter("healthy", _result("healthy", schedules=(schedule,)))
    collector = Collector(
        (adapter,),
        publisher=FakePublisher(),
        now=lambda: datetime(2030, 1, 1, 0, tzinfo=UTC),
    )

    asyncio.run(collector.collect())

    assert adapter.windows == [CollectionWindow(date(2030, 1, 1), date(2030, 1, 2))]


def test_collector_reports_sanitized_publish_error_details() -> None:
    start = datetime(2026, 7, 13, 3, tzinfo=UTC)
    schedule = _event("healthy", starts_at=start, ends_at=start + timedelta(hours=1))

    async def failing_publisher(batch: ImportBatch) -> dict[str, str]:
        del batch
        raise PublishError("ingestion request failed with HTTP 500 (import_failed)")

    collector = Collector(
        (FakeAdapter("healthy", _result("healthy", schedules=(schedule,))),),
        publisher=failing_publisher,
        today=lambda: date(2026, 7, 13),
        now=lambda: datetime(2026, 7, 13, 2, tzinfo=UTC),
    )

    report = asyncio.run(collector.collect())

    assert report.runs[0].error == (
        "PublishError: ingestion request failed with HTTP 500 (import_failed)"
    )


def test_collector_reports_http_status_without_exposing_request_details() -> None:
    request = httpx.Request(
        "GET", "https://schedule.example.test/path?token=do-not-report-this"
    )
    response = httpx.Response(503, request=request)
    collector = Collector(
        (
            FakeAdapter(
                "broken", httpx.HTTPStatusError("failed", request=request, response=response)
            ),
        ),
        publisher=FakePublisher(),
        today=lambda: date(2026, 7, 13),
        now=lambda: datetime(2026, 7, 13, 2, tzinfo=UTC),
    )

    report = asyncio.run(collector.collect())

    assert report.runs[0].error == "HTTPStatusError: HTTP 503 Service Unavailable"
    assert "do-not-report-this" not in report.model_dump_json()


def test_collector_isolates_failures_and_requests_today_and_tomorrow() -> None:
    start = datetime(2026, 7, 13, 3, tzinfo=UTC)
    failing = FakeAdapter("broken", RuntimeError("token=do-not-report-this"))
    schedule = _event("healthy", starts_at=start, ends_at=start + timedelta(hours=1))
    healthy = FakeAdapter("healthy", _result("healthy", schedules=(schedule,)))
    publisher = FakePublisher()
    collector = Collector(
        (failing, healthy),
        publisher=publisher,
        today=lambda: date(2026, 7, 13),
        now=lambda: datetime(2026, 7, 13, 2, tzinfo=UTC),
    )

    report = asyncio.run(collector.collect())

    assert failing.windows == [CollectionWindow(date(2026, 7, 13), date(2026, 7, 14))]
    assert healthy.windows == failing.windows
    assert [batch.source.source_id for batch in publisher.batches] == ["healthy"]
    assert [run.status for run in report.runs] == ["failed", "succeeded"]
    assert report.runs[0].error == "RuntimeError"
    assert "do-not-report-this" not in report.model_dump_json()


def test_collector_publishes_only_structurally_valid_results() -> None:
    start = datetime(2026, 7, 13, 3, tzinfo=UTC)
    invalid = _result(
        "invalid",
        schedules=(
            _event("invalid", starts_at=start, ends_at=start + timedelta(hours=2)),
            _event(
                "invalid",
                starts_at=start + timedelta(hours=1),
                ends_at=start + timedelta(hours=3),
                title="겹치는 프로그램",
            ),
        ),
    )
    publisher = FakePublisher()
    collector = Collector(
        (FakeAdapter("invalid", invalid),),
        publisher=publisher,
        today=lambda: date(2026, 7, 13),
        now=lambda: datetime(2026, 7, 13, 2, tzinfo=UTC),
    )

    report = asyncio.run(collector.collect())

    assert publisher.batches == []
    assert report.runs[0].status == "failed"
    assert report.runs[0].error == "ScheduleValidationError"


def test_empty_results_preserve_prior_data_and_summary_contains_counts_and_timing() -> None:
    times = iter(
        (
            datetime(2026, 7, 13, 2, 0, 0, tzinfo=UTC),
            datetime(2026, 7, 13, 2, 0, 3, tzinfo=UTC),
        )
    )
    publisher = FakePublisher()
    collector = Collector(
        (FakeAdapter("empty", _result("empty", schedules=())),),
        publisher=publisher,
        today=lambda: date(2026, 7, 13),
        now=lambda: next(times),
    )

    report = asyncio.run(collector.collect())
    run = report.runs[0]

    assert publisher.batches == []
    assert run.status == "failed"
    assert run.error == "EmptyScheduleError"
    assert run.started_at == datetime(2026, 7, 13, 2, tzinfo=UTC)
    assert run.finished_at == datetime(2026, 7, 13, 2, 0, 3, tzinfo=UTC)
    assert run.duration_ms == 3000
    assert run.channel_count == 0
    assert run.program_count == 0
    assert run.event_count == 0
