"""Collector 직렬화와 배포 API smoke 계약을 한 경로로 검증한다."""

import asyncio
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import httpx
import pytest

from radio_epg.adapters.base import CollectionWindow
from radio_epg.adapters.kbs import KbsAdapter
from radio_epg.cli import SmokeCheckError, publish_collection_batch, smoke_api
from radio_epg.collector import Collector
from radio_epg.config import SourceConfig
from radio_epg.models import AdapterResult, ImportBatch
from radio_epg.publisher import publish_batch

ROOT = Path(__file__).parents[2]
RAW_FIXTURE = ROOT / "tests" / "fixtures" / "e2e" / "kbs-busan.json"
IMPORT_FIXTURE = ROOT / "tests" / "fixtures" / "e2e" / "kbs-import.json"
MAPPING = ROOT / "data" / "mappings" / "kbs.json"
CATALOG = ROOT / "data" / "radio_channels.json"
RADIO_ID = "busan-039-kbs-1radio-busan"
NOW = datetime(2026, 7, 12, 20, 15, tzinfo=UTC)


class FixtureClient:
    def __init__(self) -> None:
        self.payload = json.loads(RAW_FIXTURE.read_text(encoding="utf-8"))

    async def get(self, url: str) -> httpx.Response:
        parsed = httpx.URL(url)
        station = parsed.params["local_station_code"]
        channels = set(parsed.params["channel_code"].split(","))
        start = parsed.params["program_planned_date_from"]
        end = parsed.params["program_planned_date_to"]
        selected = []
        for group in self.payload:
            if group["local_station_code"] != station or group["channel_code"] not in channels:
                continue
            selected.append(
                {
                    **group,
                    "schedules": [
                        schedule
                        for schedule in group["schedules"]
                        if start <= schedule["program_planned_date"] <= end
                    ],
                }
            )
        return httpx.Response(200, json=selected)


def _source() -> SourceConfig:
    return SourceConfig(
        source_id="kbs",
        name="KBS 편성표",
        source_kind="official",
        source_url="https://schedule.kbs.co.kr/",
        priority=100,
        adapter="kbs",
    )


class BusanFixtureAdapter:
    """실제 KBS adapter 결과에서 E2E에 필요한 한 채널만 선택한다."""

    schedule_policy = KbsAdapter.schedule_policy

    def __init__(self) -> None:
        self.source = _source()
        self._adapter = KbsAdapter(
            self.source,
            client=FixtureClient(),
            mapping_path=MAPPING,
            catalog_path=CATALOG,
            now=lambda: NOW,
        )

    async def collect(self, window: CollectionWindow) -> AdapterResult:
        result = await self._adapter.collect(window)
        schedules = tuple(
            event for event in result.schedules if event.channel_id == "kbs.1radio.busan"
        )
        program_ids = {event.program_id for event in schedules}
        return result.model_copy(
            update={
                "channels": tuple(
                    channel
                    for channel in result.channels
                    if channel.channel_id == "kbs.1radio.busan"
                ),
                "programs": tuple(
                    program for program in result.programs if program.program_id in program_ids
                ),
                "schedules": schedules,
                "images": tuple(
                    image for image in result.images if image.entity_id in program_ids
                ),
            }
        )


def test_fixture_collection_serializes_the_worker_import_contract() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed.update(json.loads(request.read()))
        return httpx.Response(201, json={"status": "applied"})

    async def publisher(batch: ImportBatch) -> dict[str, object]:
        return await publish_batch(
            batch,
            base_url="https://epg.example.test",
            token="test-token",
            transport=httpx.MockTransport(handler),
        )

    report = asyncio.run(
        Collector(
            (BusanFixtureAdapter(),),
            publisher=publisher,
            today=lambda: date(2026, 7, 13),
            now=lambda: NOW,
        ).collect()
    )
    expected = json.loads(IMPORT_FIXTURE.read_text(encoding="utf-8"))

    assert report.runs[0].status == "succeeded"
    assert observed == expected
    channels = cast(list[dict[str, object]], observed["channels"])
    assert channels[0]["radio_ids"] == [RADIO_ID]


def test_fixture_collection_imports_schedule_without_image_variants() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/v1/admin/import":
            return httpx.Response(201, json={"status": "applied"})
        if request.url.path == "/v1/admin/images":
            return httpx.Response(201, json={"status": "stored"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    async def publisher(batch: ImportBatch) -> dict[str, object]:
        async def schedule_publisher(batch: ImportBatch, **_kwargs: object):
            return await publish_batch(
                batch,
                base_url="https://epg.example.test",
                token="test-token",
                transport=transport,
            )

        return await publish_collection_batch(
            batch,
            base_url="https://epg.example.test",
            token="test-token",
            schedule_publisher=schedule_publisher,
        )

    run = asyncio.run(
        Collector(
            (BusanFixtureAdapter(),),
            publisher=publisher,
            today=lambda: date(2026, 7, 13),
            now=lambda: NOW,
        ).collect()
    ).runs[0]

    assert paths == ["/v1/admin/import"]
    assert run.status == "succeeded"
    assert run.image_count == 1
    assert run.image_variant_count == 0
    assert run.image_error_count == 0


def test_smoke_api_checks_health_channels_alias_and_coverage() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, json={"service": "radio-epg"})
        if request.url.path == "/v1/channels":
            return httpx.Response(200, json={"channels": [{"channel_id": "kbs.1radio.busan"}]})
        if request.url.path == f"/v1/channels/{RADIO_ID}":
            return httpx.Response(
                200,
                json={"channel_id": "kbs.1radio.busan", "aliases": [{"value": RADIO_ID}]},
            )
        if request.url.path == "/v1/coverage":
            return httpx.Response(200, json={"sources": [{"source_id": "kbs"}]})
        return httpx.Response(404)

    result = asyncio.run(
        smoke_api(
            "https://epg.example.test",
            RADIO_ID,
            transport=httpx.MockTransport(handler),
        )
    )

    assert paths == [
        "/health",
        "/v1/channels",
        f"/v1/channels/{RADIO_ID}",
        "/v1/coverage",
    ]
    assert result == {
        "service": "radio-epg",
        "channel_count": 1,
        "radio_id": RADIO_ID,
        "channel_id": "kbs.1radio.busan",
        "coverage_source_count": 1,
    }


@pytest.mark.parametrize(
    ("empty_path", "message"),
    [
        ("/v1/channels", "at least one channel"),
        ("/v1/coverage", "at least one source"),
    ],
)
def test_smoke_api_rejects_empty_deployment_data(empty_path: str, message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"service": "radio-epg"})
        if request.url.path == "/v1/channels":
            channels = (
                [] if empty_path == request.url.path else [{"channel_id": "kbs.1radio.busan"}]
            )
            return httpx.Response(200, json={"channels": channels})
        if request.url.path == f"/v1/channels/{RADIO_ID}":
            return httpx.Response(
                200,
                json={"channel_id": "kbs.1radio.busan", "aliases": [{"value": RADIO_ID}]},
            )
        if request.url.path == "/v1/coverage":
            sources = [] if empty_path == request.url.path else [{"source_id": "kbs"}]
            return httpx.Response(200, json={"sources": sources})
        return httpx.Response(404)

    with pytest.raises(SmokeCheckError, match=message):
        asyncio.run(
            smoke_api(
                "https://epg.example.test",
                RADIO_ID,
                transport=httpx.MockTransport(handler),
            )
        )
