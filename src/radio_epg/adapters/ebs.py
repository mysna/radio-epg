"""EBS FM과 반디 외국어 전문 HTML schedule adapter."""

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

from radio_epg.adapters.base import CollectionWindow
from radio_epg.adapters.html_schedule import (
    ScheduleRow,
    load_channel_mapping,
    normalize_rows,
    parse_html_schedule,
)
from radio_epg.config import SourceConfig
from radio_epg.http import PoliteHttpClient
from radio_epg.models import AdapterResult
from radio_epg.validation import SchedulePolicy

_ROOT = Path(__file__).parents[3]
_MAPPING = _ROOT / "data" / "mappings" / "ebs.json"
_CATALOG = _ROOT / "data" / "radio_channels.json"


class EbsSchemaError(ValueError):
    """EBS HTML이 검증된 편성 DOM 계약과 다를 때 발생한다."""


def _parse_official_html(
    text: str, *, expected_date: date, channel_code: str
) -> tuple[ScheduleRow, ...]:
    soup = BeautifulSoup(text, "html.parser")
    compact_date = expected_date.strftime("%Y%m%d")
    selected = soup.select_one(f'.day_select li.selected a[href*="date={compact_date}"]')
    if selected is None:
        raise ValueError("EBS response date does not match the requested date")
    raw_items = soup.select("ul.main_timeline > li")
    starts: list[tuple[str, Tag]] = []
    for item in raw_items:
        time_node = item.select_one(".time > span")
        title_node = item.select_one(".tit strong")
        if time_node is None or title_node is None:
            raise ValueError("EBS schedule row schema changed")
        starts.append((time_node.get_text(strip=True), item))
    rows: list[ScheduleRow] = []
    for index, (start, item) in enumerate(starts[:-1]):
        title_node = item.select_one(".tit strong")
        if title_node is None:
            raise ValueError("EBS schedule row title is missing")
        subtitle_node = item.select_one(".tit .txt_cnt")
        homepage_node = item.select_one("a.homepage[href]")
        title = title_node.get_text(" ", strip=True)
        homepage = (
            urljoin("https://www.ebs.co.kr/", str(homepage_node["href"]))
            if homepage_node is not None
            else None
        )
        rows.append(
            ScheduleRow(
                upstream_id=f"{channel_code}:{compact_date}:{start}:{title}",
                broadcast_date=expected_date,
                start=start,
                end=starts[index + 1][0],
                title=title.removesuffix("(재)").strip(),
                subtitle=(
                    subtitle_node.get_text(" ", strip=True) if subtitle_node is not None else None
                ),
                homepage_url=homepage,
                is_live=item.select_one(".icon_wrap .live") is not None,
                is_rerun=title.endswith("(재)"),
            )
        )
    return tuple(rows)


def parse_ebs_schedule(
    text: str, *, expected_date: date, channel_code: str | None = None
) -> tuple[ScheduleRow, ...]:
    """한 EBS 채널 페이지에서 요청일 편성을 읽는다."""
    try:
        channels = parse_html_schedule(text, expected_date=expected_date)
        if not channels and channel_code is not None:
            official_rows = _parse_official_html(
                text, expected_date=expected_date, channel_code=channel_code
            )
            if not official_rows:
                raise EbsSchemaError("EBS schedule response is empty")
            return official_rows
    except ValueError as error:
        raise EbsSchemaError(str(error)) from error
    if len(channels) != 1 or not next(iter(channels.values()), ()):
        raise EbsSchemaError("EBS schedule response is empty")
    return next(iter(channels.values()))


class _Client(Protocol):
    async def get(self, url: str) -> httpx.Response: ...


class EbsAdapter:
    """EBS FM과 반디를 서로 다른 공식 channelCd로 수집한다."""

    schedule_policy = SchedulePolicy(allow_adjacent=True)

    def __init__(
        self,
        source: SourceConfig,
        *,
        client: _Client | None = None,
        mapping_path: Path = _MAPPING,
        catalog_path: Path = _CATALOG,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.source = source
        self._client = client
        self._mapping = load_channel_mapping(mapping_path)
        self._catalog_path = catalog_path
        self._now = now

    async def collect(self, window: CollectionWindow) -> AdapterResult:
        if self._client is not None:
            return await self._collect_with(self._client, window)
        async with PoliteHttpClient() as client:
            return await self._collect_with(client, window)

    async def _collect_with(self, client: _Client, window: CollectionWindow) -> AdapterResult:
        collected: dict[str, list[ScheduleRow]] = defaultdict(list)
        current = window.start
        while current <= window.end:
            for channel in self._mapping.channels:
                response = await client.get(channel.url.format(date=current.strftime("%Y%m%d")))
                collected[channel.upstream_code].extend(
                    parse_ebs_schedule(
                        response.text,
                        expected_date=current,
                        channel_code=channel.upstream_code,
                    )
                )
            current += timedelta(days=1)
        return normalize_rows(
            source=self.source,
            mapping=self._mapping,
            catalog_path=self._catalog_path,
            rows=collected,
            fetched_at=self._now(),
        )
