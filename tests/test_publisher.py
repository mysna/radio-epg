import asyncio
from datetime import UTC, date, datetime

import httpx
import pytest

from radio_epg.models import ImageCandidate, ImportBatch, ScheduleCandidate, SourceMetadata
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
