import asyncio
from datetime import date
from pathlib import Path

import httpx

from radio_epg.adapters.base import CollectionWindow
from radio_epg.adapters.community import (
    CommunityAdapter,
    SourcedScheduleRow,
    load_community_mapping,
    merge_schedule_rows,
)
from radio_epg.adapters.community_ocr import fetch_kjfm_schedule_image
from radio_epg.adapters.html_schedule import ScheduleRow
from radio_epg.config import SourceConfig
from radio_epg.coverage import build_coverage

ROOT = Path(__file__).parents[2]
MAPPING = ROOT / "data" / "mappings" / "community.json"
FIXTURES = Path(__file__).parents[1] / "fixtures" / "community"


def _row(event_id: str, start: str, end: str, *, confidence: float = 1) -> ScheduleRow:
    return ScheduleRow(
        upstream_id=event_id,
        broadcast_date=date(2026, 7, 13),
        start=start,
        end=end,
        title=event_id,
        confidence=confidence,
    )


def test_mapping_accounts_for_all_23_community_identities() -> None:
    mapping = load_community_mapping(MAPPING)
    community = tuple(item for item in mapping.channels if item.family == "community")

    assert len(community) == 23
    assert all(item.status in {"enabled", "unsupported"} for item in community)
    assert all(item.primary_source.startswith("https://") for item in community)


def test_official_rows_win_and_fallback_only_fills_uncovered_ranges() -> None:
    official = [SourcedScheduleRow(_row("official", "05:00", "07:00"), "official")]
    fallback = [
        SourcedScheduleRow(_row("overlap", "06:00", "08:00", confidence=0.7), "wiki"),
        SourcedScheduleRow(_row("gap", "07:00", "09:00", confidence=0.7), "inferred"),
    ]

    merged = merge_schedule_rows(official, fallback)

    assert [item.row.upstream_id for item in merged] == ["official", "gap"]
    assert merged[1].source_kind == "inferred"


def test_task_12_mapping_completes_all_194_catalog_identities() -> None:
    report = build_coverage(ROOT, require_accounted=True)

    assert report.accounted_count == report.catalog_count == 194
    assert report.pending_count == 0


class _KjfmClient:
    """게시판 목록 → 상세 → 이미지 3단계를 실제 캡처한 응답으로 흉내낸다."""

    def __init__(self) -> None:
        self.list_html = (FIXTURES / "kjfm-article-list.html").read_text(encoding="utf-8")
        self.detail_html = (FIXTURES / "kjfm-article-detail.html").read_text(encoding="utf-8")
        self.image_bytes = (FIXTURES / "kjfm-schedule.jpg").read_bytes()

    async def post(self, url: str, **_kwargs: object) -> httpx.Response:
        if "selectArticleList.do" in url:
            return httpx.Response(200, text=self.list_html, request=httpx.Request("POST", url))
        if "selectArticleDetail.do" in url:
            return httpx.Response(200, text=self.detail_html, request=httpx.Request("POST", url))
        raise AssertionError(f"unexpected POST: {url}")

    async def get(self, url: str, **_kwargs: object) -> httpx.Response:
        assert "fileDownload.do" in url
        return httpx.Response(200, content=self.image_bytes, request=httpx.Request("GET", url))


def test_fetch_kjfm_schedule_image_follows_the_board_to_the_latest_attachment() -> None:
    client = _KjfmClient()

    image_bytes = asyncio.run(fetch_kjfm_schedule_image(client))

    assert image_bytes == client.image_bytes


def _source(source_id: str) -> SourceConfig:
    return SourceConfig(
        source_id=source_id,
        name=source_id,
        source_kind="official-with-fallback",
        source_url="https://kjfm.communityradio.kr/",
        priority=70,
        adapter="community",
    )


def test_community_adapter_collects_kjfm_via_ocr() -> None:
    adapter = CommunityAdapter(_source("community"), client=_KjfmClient())
    day = date(2026, 9, 7)  # Monday

    result = asyncio.run(adapter.collect(CollectionWindow(day, day)))

    channel_ids = {row.channel_id for row in result.schedules}
    assert channel_ids == {"community.kjfm.main"}
    assert len(result.schedules) > 5


def test_community_adapter_skips_weekends_without_failing() -> None:
    adapter = CommunityAdapter(_source("community"), client=_KjfmClient())
    saturday = date(2026, 9, 12)

    result = asyncio.run(adapter.collect(CollectionWindow(saturday, saturday)))

    assert result.schedules == ()
