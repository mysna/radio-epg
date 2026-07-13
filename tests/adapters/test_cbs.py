import asyncio
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from radio_epg.adapters.base import CollectionWindow
from radio_epg.adapters.cbs import CbsAdapter, parse_cbs_schedule
from radio_epg.adapters.html_schedule import load_channel_mapping
from radio_epg.adapters.pdf_schedule import parse_pdf_schedule_text
from radio_epg.config import SourceConfig

FIXTURES = Path(__file__).parents[1] / "fixtures" / "cbs"
MAPPING = Path(__file__).parents[2] / "data" / "mappings" / "cbs.json"
CATALOG = Path(__file__).parents[2] / "data" / "radio_channels.json"


class FixtureClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[httpx.URL] = []

    async def get(self, url: str) -> httpx.Response:
        self.requests.append(httpx.URL(url))
        return httpx.Response(200, text=self.text)


def _source() -> SourceConfig:
    return SourceConfig(
        source_id="cbs",
        name="CBS 편성표",
        source_kind="official",
        source_url="https://www.cbs.co.kr/schedule",
        priority=100,
        adapter="cbs",
    )


def test_cbs_html_maps_standard_music_and_joy4u() -> None:
    rows = parse_cbs_schedule(
        (FIXTURES / "schedule.html").read_text(), expected_date=date(2026, 7, 13)
    )

    assert set(rows) == {"sfm", "mfm", "joy4u"}
    assert rows["joy4u"][0].title == "당신을 향한 노래"


def test_cbs_pdf_text_uses_channel_boundaries_and_strict_time_rows() -> None:
    rows = parse_pdf_schedule_text((FIXTURES / "schedule.txt").read_text())

    assert set(rows) == {"sfm", "mfm"}
    assert rows["sfm"][1].title == "CBS 뉴스"


def test_cbs_official_html_selects_the_schedule_slide_and_keeps_the_last_program() -> None:
    rows = parse_cbs_schedule(
        (FIXTURES / "official-schedule.html").read_text(),
        expected_date=date(2026, 7, 14),
        channel_code="sfm",
    )["sfm"]

    assert [(row.start, row.end) for row in rows] == [("22:00", "23:05"), ("23:05", "24:00")]
    assert rows[-1].title == "CBS 뉴스"
    assert rows[-1].is_rerun is True


def test_cbs_adapter_requests_the_compact_official_date() -> None:
    client = FixtureClient((FIXTURES / "official-schedule.html").read_text())
    adapter = CbsAdapter(
        _source(),
        client=client,
        mapping_path=MAPPING,
        catalog_path=CATALOG,
        now=lambda: datetime(2026, 7, 14, tzinfo=UTC),
    )

    result = asyncio.run(adapter.collect(CollectionWindow(date(2026, 7, 14), date(2026, 7, 14))))

    assert len(result.channels) == 3
    assert {request.params["date"] for request in client.requests} == {"20260714"}


def test_cbs_mapping_owns_only_the_three_central_channels() -> None:
    mapping = load_channel_mapping(MAPPING)

    assert {item.channel_id for item in mapping.channels} == {
        "cbs.sfm.main",
        "cbs.mfm.main",
        "cbs.joy4u.main",
    }
