"""CBS 중앙 표준FM, 음악FM, JOY4U HTML adapter."""

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx
from bs4 import BeautifulSoup

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
_MAPPING = _ROOT / "data" / "mappings" / "cbs.json"
_CATALOG = _ROOT / "data" / "radio_channels.json"


class CbsSchemaError(ValueError):
    """CBS HTML이 검증된 편성 DOM 계약과 다를 때 발생한다."""


def parse_cbs_schedule(
    text: str, *, expected_date: date, channel_code: str | None = None
) -> dict[str, tuple[ScheduleRow, ...]]:
    """CBS 중앙 세 채널의 요청일 편성을 읽는다."""
    try:
        channels = parse_html_schedule(text, expected_date=expected_date)
        if not channels and channel_code is not None:
            channels = {
                channel_code: _parse_official_html(
                    text, expected_date=expected_date, channel_code=channel_code
                )
            }
    except ValueError as error:
        raise CbsSchemaError(str(error)) from error
    expected = {"sfm", "mfm", "joy4u"}
    if not channels or not set(channels).issubset(expected) or not all(channels.values()):
        raise CbsSchemaError("CBS schedule response is empty or incomplete")
    return channels


def _parse_official_html(
    text: str, *, expected_date: date, channel_code: str
) -> tuple[ScheduleRow, ...]:
    soup = BeautifulSoup(text, "html.parser")
    compact_date = expected_date.strftime("%Y%m%d")
    container = soup.select_one(f'.forSwiper .swiper-slide[data-fulldate="{compact_date}"]')
    if container is None:
        raise CbsSchemaError("CBS response date does not match the requested date")
    parsed: list[tuple[str, str, str | None]] = []
    for item in container.select("ul.time-table > li.slide"):
        time_node = item.select_one(".time")
        program_node = item.select_one(".program")
        if time_node is None or program_node is None:
            raise CbsSchemaError("CBS schedule row schema changed")
        title_node = program_node.select_one("a")
        strings = program_node.stripped_strings
        title = (
            title_node.get_text(" ", strip=True) if title_node is not None else next(strings, "")
        )
        if not title:
            raise CbsSchemaError("CBS schedule row title is empty")
        homepage = str(title_node["href"]) if title_node is not None else None
        parsed.append((time_node.get_text(strip=True), title, homepage))
    rows: list[ScheduleRow] = []
    for index, (start, raw_title, homepage) in enumerate(parsed):
        title = raw_title.removesuffix("(재)").strip()
        end = parsed[index + 1][0] if index + 1 < len(parsed) else "24:00"
        rows.append(
            ScheduleRow(
                upstream_id=f"{channel_code}:{compact_date}:{start}:{title}",
                broadcast_date=expected_date,
                start=start,
                end=end,
                title=title,
                homepage_url=homepage,
                is_rerun=raw_title.endswith("(재)"),
            )
        )
    if not rows:
        raise CbsSchemaError("CBS schedule response is empty")
    return tuple(rows)


class _Client(Protocol):
    async def get(self, url: str) -> httpx.Response: ...


class CbsAdapter:
    """CBS 중앙 세 채널의 공식 HTML을 날짜별로 수집한다."""

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
                response = await client.get(
                    channel.url.format(
                        date=current.isoformat(), date_compact=current.strftime("%Y%m%d")
                    )
                )
                parsed = parse_cbs_schedule(
                    response.text,
                    expected_date=current,
                    channel_code=channel.upstream_code,
                )
                if channel.upstream_code not in parsed:
                    raise CbsSchemaError("CBS response omitted the requested channel")
                collected[channel.upstream_code].extend(parsed[channel.upstream_code])
            current += timedelta(days=1)
        return normalize_rows(
            source=self.source,
            mapping=self._mapping,
            catalog_path=self._catalog_path,
            rows=collected,
            fetched_at=self._now(),
        )
