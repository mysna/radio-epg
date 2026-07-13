import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import httpx
import pytest

from radio_epg.models import (
    ImageCandidate,
    ImportBatch,
    ProgramCandidate,
    ScheduleCandidate,
    SourceMetadata,
)
from radio_epg.publisher import PublishError, publish_batch

TOKEN = "super-secret-ingest-token"


def _batch() -> ImportBatch:
    source = SourceMetadata(
        source_id="kbs",
        name="KBS 편성표",
        source_kind="official",
        source_url="https://schedule.kbs.co.kr/",
        priority=100,
        fetched_at=datetime(2026, 7, 13, 1, tzinfo=UTC),
    )
    schedule = ScheduleCandidate(
        source_id="kbs",
        source_url="https://schedule.kbs.co.kr/",
        source_kind="official",
        fetched_at=datetime(2026, 7, 13, 1, tzinfo=UTC),
        confidence=1,
        channel_id="kbs.1radio.main",
        broadcast_date=date(2026, 7, 13),
        starts_at=datetime(2026, 7, 13, 3, tzinfo=UTC),
        ends_at=datetime(2026, 7, 13, 4, tzinfo=UTC),
        title="KBS 뉴스",
    )
    return ImportBatch(
        idempotency_key="kbs-2026-07-13",
        source=source,
        schedules=(schedule,),
        images=(
            ImageCandidate(
                entity_type="program",
                entity_id="kbs:news",
                source_url="https://images.example.test/news.png",
                source_page_url="https://schedule.kbs.co.kr/",
            ),
        ),
        collected_at=datetime(2026, 7, 13, 1, 1, tzinfo=UTC),
    )


def test_publisher_sends_bearer_token_json_and_explicit_timeouts() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["authorization"] = request.headers["Authorization"]
        observed["body"] = request.read().decode()
        observed["timeout"] = request.extensions["timeout"]
        return httpx.Response(201, json={"status": "applied"})

    result = asyncio.run(
        publish_batch(
            _batch(),
            base_url="https://epg.example.test/",
            token=TOKEN,
            transport=httpx.MockTransport(handler),
        )
    )

    assert result == {"status": "applied"}
    assert observed["authorization"] == f"Bearer {TOKEN}"
    assert '"idempotency_key":"kbs-2026-07-13"' in str(observed["body"])
    assert '"images"' not in str(observed["body"])
    assert observed["timeout"] == {"connect": 5.0, "read": 20.0, "write": 20.0, "pool": 5.0}


def test_publisher_partitions_large_batches_without_splitting_schedule_scopes() -> None:
    base = _batch()
    template = base.schedules[0]
    schedules = tuple(
        template.model_copy(
            update={
                "source_event_id": f"event-{index}",
                "broadcast_date": template.broadcast_date + timedelta(days=index // 700),
                "starts_at": template.starts_at + timedelta(days=index // 700),
                "ends_at": template.ends_at + timedelta(days=index // 700),
                "title": f"KBS 프로그램 {index}",
            }
        )
        for index in range(2_100)
    )
    batch = base.model_copy(update={"schedules": schedules})
    payloads: list[dict[str, object]] = []
    body_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        body_sizes.append(len(body))
        payloads.append(json.loads(body))
        return httpx.Response(201, json={"status": "applied"})

    result = asyncio.run(
        publish_batch(
            batch,
            base_url="https://epg.example.test",
            token=TOKEN,
            transport=httpx.MockTransport(handler),
        )
    )

    scopes: list[set[tuple[str, str]]] = []
    for payload in payloads:
        schedules_payload = payload["schedules"]
        assert isinstance(schedules_payload, list)
        schedule_rows = cast(list[dict[str, Any]], schedules_payload)
        assert len(schedule_rows) <= 2_000
        scopes.append(
            {
                (str(schedule["channel_id"]), str(schedule["broadcast_date"]))
                for schedule in schedule_rows
            }
        )
    assert result == {"status": "applied", "part_count": len(payloads)}
    assert len(payloads) > 1
    assert all(size < 1_000_000 for size in body_sizes)
    assert all(scopes[index].isdisjoint(scopes[index + 1]) for index in range(len(scopes) - 1))


def test_publisher_partitions_batches_over_the_program_limit() -> None:
    base = _batch()
    template = base.schedules[0]
    programs = tuple(
        ProgramCandidate(
            source_id="kbs",
            program_id=f"kbs:program-{index}",
            title=f"KBS 프로그램 {index}",
        )
        for index in range(1_001)
    )
    schedules = tuple(
        template.model_copy(
            update={
                "program_id": program.program_id,
                "source_event_id": f"program-event-{index}",
                "broadcast_date": template.broadcast_date + timedelta(days=index // 500),
                "starts_at": template.starts_at + timedelta(days=index // 500),
                "ends_at": template.ends_at + timedelta(days=index // 500),
                "title": program.title,
            }
        )
        for index, program in enumerate(programs)
    )
    batch = base.model_copy(update={"programs": programs, "schedules": schedules})
    payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.read()))
        return httpx.Response(201, json={"status": "applied"})

    asyncio.run(
        publish_batch(
            batch,
            base_url="https://epg.example.test",
            token=TOKEN,
            transport=httpx.MockTransport(handler),
        )
    )

    assert len(payloads) > 1
    assert all(len(cast(list[object], payload["programs"])) <= 1_000 for payload in payloads)


def test_publisher_retries_only_bounded_transient_responses() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, json={"error": {"code": "temporary"}})
        return httpx.Response(200, json={"status": "already_applied"})

    result = asyncio.run(
        publish_batch(
            _batch(),
            base_url="https://epg.example.test",
            token=TOKEN,
            max_retries=2,
            retry_base_delay=0,
            transport=httpx.MockTransport(handler),
        )
    )

    assert attempts == 3
    assert result == {"status": "already_applied"}


def test_publisher_does_not_retry_permanent_errors_or_leak_payload() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, json={"error": {"code": "invalid_import"}})

    with pytest.raises(PublishError) as captured:
        asyncio.run(
            publish_batch(
                _batch(),
                base_url="https://epg.example.test",
                token=TOKEN,
                max_retries=2,
                retry_base_delay=0,
                transport=httpx.MockTransport(handler),
            )
        )

    assert attempts == 1
    assert str(captured.value) == "ingestion request failed with HTTP 400 (invalid_import)"
    assert TOKEN not in str(captured.value)
    assert "KBS 뉴스" not in str(captured.value)


def test_publisher_retries_transient_transport_errors() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("temporary failure", request=request)
        return httpx.Response(201, json={"status": "applied"})

    result = asyncio.run(
        publish_batch(
            _batch(),
            base_url="https://epg.example.test",
            token=TOKEN,
            max_retries=1,
            retry_base_delay=0,
            transport=httpx.MockTransport(handler),
        )
    )

    assert attempts == 2
    assert result == {"status": "applied"}


def test_publisher_wraps_invalid_success_responses() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, text="not-json")

    with pytest.raises(PublishError, match="JSON object"):
        asyncio.run(
            publish_batch(
                _batch(),
                base_url="https://epg.example.test",
                token=TOKEN,
                transport=httpx.MockTransport(handler),
            )
        )
