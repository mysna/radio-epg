import asyncio
import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from radio_epg.adapters.base import CollectionWindow
from radio_epg.adapters.kbs import KbsAdapter, KbsEmptyScheduleError, KbsSchemaError
from radio_epg.catalog import load_catalog
from radio_epg.config import SourceConfig
from radio_epg.validation import validate_schedule

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "kbs"
MAPPING = ROOT / "data" / "mappings" / "kbs.json"
CATALOG = ROOT / "data" / "radio_channels.json"


def _source() -> SourceConfig:
    return SourceConfig(
        source_id="kbs",
        name="KBS 편성표",
        source_kind="official",
        source_url="https://schedule.kbs.co.kr/",
        priority=100,
        adapter="kbs",
    )


class FixtureClient:
    def __init__(self, fixture: Path) -> None:
        self.payload = json.loads(fixture.read_text(encoding="utf-8"))
        self.requests: list[httpx.URL] = []

    async def get(self, url: str) -> httpx.Response:
        parsed = httpx.URL(url)
        self.requests.append(parsed)
        if not isinstance(self.payload, list):
            return httpx.Response(200, json=self.payload)

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


def _adapter(client: FixtureClient) -> KbsAdapter:
    return KbsAdapter(
        _source(),
        client=client,
        mapping_path=MAPPING,
        catalog_path=CATALOG,
        now=lambda: datetime(2026, 7, 13, 1, tzinfo=UTC),
    )


def test_mapping_accounts_for_every_kbs_catalog_identity() -> None:
    catalog = load_catalog(CATALOG)
    expected = {channel_id for channel_id in catalog.channels if channel_id.startswith("kbs.")}
    raw_mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    mapped = {item["channel_id"] for item in raw_mapping["channels"]}

    assert len(expected) == 46
    assert mapped == expected


def test_adapter_maps_national_and_regional_schedules_and_request_parameters() -> None:
    client = FixtureClient(FIXTURES / "weekly.json")
    adapter = _adapter(client)

    result = asyncio.run(adapter.collect(CollectionWindow(date(2026, 7, 13), date(2026, 7, 20))))

    assert len(result.channels) == 46
    assert {event.channel_id for event in result.schedules} == {
        "kbs.1fm.main",
        "kbs.1fm.wonju",
        "kbs.1radio.busan",
        "kbs.hanminjok.main",
    }
    national = [
        request for request in client.requests if request.params["local_station_code"] == "00"
    ]
    regional = [
        request for request in client.requests if request.params["local_station_code"] == "10"
    ]
    assert all(
        set(request.params["channel_code"].split(",")) == {"21", "22", "23", "24", "25", "26"}
        for request in national
    )
    assert all(
        set(request.params["channel_code"].split(",")) == {"21", "22", "24"} for request in regional
    )
    assert [
        (
            request.params["program_planned_date_from"],
            request.params["program_planned_date_to"],
        )
        for request in national
    ] == [("20260713", "20260719"), ("20260720", "20260720")]


def test_adapter_preserves_stable_ids_extended_hours_and_flags() -> None:
    adapter = _adapter(FixtureClient(FIXTURES / "weekly.json"))

    first = asyncio.run(adapter.collect(CollectionWindow(date(2026, 7, 13), date(2026, 7, 20))))
    second = asyncio.run(adapter.collect(CollectionWindow(date(2026, 7, 13), date(2026, 7, 20))))
    live = next(
        event for event in first.schedules if (event.source_event_id or "").endswith(":9001")
    )
    extended = next(
        event for event in first.schedules if (event.source_event_id or "").endswith(":9002")
    )

    assert [event.source_event_id for event in first.schedules] == [
        event.source_event_id for event in second.schedules
    ]
    assert live.is_live is True
    assert live.is_rerun is False
    assert extended.is_live is False
    assert extended.is_rerun is True
    assert extended.title == "심야 음악"
    assert extended.starts_at.isoformat() == "2026-07-14T00:00:00+09:00"
    assert extended.ends_at.isoformat() == "2026-07-14T01:30:00+09:00"
    validate_schedule(first.schedules, policy=adapter.schedule_policy)


def test_adapter_scopes_reused_upstream_event_ids_to_canonical_channels() -> None:
    client = FixtureClient(FIXTURES / "weekly.json")
    client.payload[1]["schedules"][0]["schedule_unique_id"] = 9001
    adapter = _adapter(client)

    result = asyncio.run(adapter.collect(CollectionWindow(date(2026, 7, 13), date(2026, 7, 14))))

    source_event_ids = [event.source_event_id for event in result.schedules]
    reused = [event_id for event_id in source_event_ids if event_id and event_id.endswith(":9001")]
    assert len(source_event_ids) == len(set(source_event_ids))
    assert len(reused) == 2


def test_adapter_rejects_empty_responses_without_fabricating_schedules() -> None:
    adapter = _adapter(FixtureClient(FIXTURES / "empty.json"))

    with pytest.raises(KbsEmptyScheduleError, match="empty"):
        asyncio.run(adapter.collect(CollectionWindow(date(2026, 7, 13), date(2026, 7, 20))))


def test_adapter_fails_closed_with_a_clear_schema_change_error() -> None:
    adapter = _adapter(FixtureClient(FIXTURES / "schema-change.json"))

    with pytest.raises(KbsSchemaError, match="schema changed"):
        asyncio.run(adapter.collect(CollectionWindow(date(2026, 7, 13), date(2026, 7, 20))))
