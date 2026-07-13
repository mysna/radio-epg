"""TBN 13개 지역 공식 편성 adapter."""

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from radio_epg.adapters.base import CollectionWindow
from radio_epg.adapters.html_schedule import (
    ScheduleRow,
    load_channel_mapping,
    normalize_rows,
    parse_json_channel_rows,
)
from radio_epg.config import SourceConfig
from radio_epg.http import PoliteHttpClient
from radio_epg.models import AdapterResult
from radio_epg.validation import SchedulePolicy

_ROOT = Path(__file__).parents[3]
_MAPPING = _ROOT / "data" / "mappings" / "tbn.json"
_CATALOG = _ROOT / "data" / "radio_channels.json"

_STATIONS = {
    "main",
    "busan",
    "gwangju",
    "daegu",
    "daejeon",
    "gangwon",
    "jeonbuk",
    "ulsan",
    "gyeongnam",
    "gyeongbuk",
    "jeju",
    "chungbuk",
    "chungnam",
}
_PAGE_CODES = {
    "main": "6",
    "busan": "2",
    "gwangju": "3",
    "daegu": "4",
    "daejeon": "5",
    "gangwon": "7",
    "jeonbuk": "8",
    "ulsan": "9",
    "gyeongnam": "10",
    "gyeongbuk": "11",
    "jeju": "12",
    "chungbuk": "13",
    "chungnam": "14",
}
_STATION_NAMES = {
    "main": "경인",
    "busan": "부산",
    "gwangju": "광주",
    "daegu": "대구",
    "daejeon": "대전",
    "gangwon": "강원",
    "jeonbuk": "전북",
    "ulsan": "울산",
    "gyeongnam": "경남",
    "gyeongbuk": "경북",
    "jeju": "제주",
    "chungbuk": "충북",
    "chungnam": "충남",
}


class TbnSchemaError(ValueError):
    """TBN 지역 또는 편성 JSON이 검증된 계약과 다를 때 발생한다."""


def parse_tbn_schedule(
    payload: object, *, expected_date: date
) -> dict[str, tuple[ScheduleRow, ...]]:
    """TBN 지역 코드를 유지해 요청일 편성을 읽는다."""
    try:
        parsed = parse_json_channel_rows(
            payload,
            expected_date=expected_date,
            date_key="date",
            channels_key="stations",
            allowed_channels=_STATIONS,
        )
    except ValueError as error:
        message = str(error).replace("channels", "stations")
        raise TbnSchemaError(message) from error
    if not parsed or not any(parsed.values()):
        raise TbnSchemaError("TBN station schedule is empty")
    return parsed


def parse_tbn_html(text: str, *, expected_date: date, station_code: str) -> tuple[ScheduleRow, ...]:
    """지역별 공식 TBN HTML에서 요청일 한 채널만 읽는다."""
    if station_code not in _STATIONS:
        raise TbnSchemaError("TBN region is unknown")
    soup = BeautifulSoup(text, "html.parser")
    date_node = soup.select_one("#today")
    if date_node is None or date_node.get("value") != expected_date.strftime("%Y%m%d"):
        raise TbnSchemaError("TBN response date does not match the requested date")

    page_node = soup.select_one("#page_code")
    if page_node is not None and page_node.get("value") != _PAGE_CODES[station_code]:
        raise TbnSchemaError("TBN response region does not match the requested region")
    selected_region = soup.select_one(".local-select li.on")
    if (
        selected_region is not None
        and selected_region.get_text(" ", strip=True) != _STATION_NAMES[station_code]
    ):
        raise TbnSchemaError("TBN response region does not match the requested region")
    if page_node is None and selected_region is None:
        raise TbnSchemaError("TBN response region metadata is missing")

    parsed: list[tuple[str, str, str, str]] = []
    for table_row in soup.select(".table-list.basic table tr"):
        cells = table_row.find_all("td", recursive=False)
        if not cells:
            continue
        if len(cells) < 3:
            raise TbnSchemaError("TBN schedule row schema changed")
        hour = cells[0].get_text(strip=True)
        minute = cells[1].get_text(strip=True)
        program_cell = table_row.select_one("td.align-left")
        if not hour.isdigit() or not minute.isdigit() or program_cell is None:
            raise TbnSchemaError("TBN schedule row schema changed")
        title_node = program_cell.select_one("strong")
        homepage_node = program_cell.select_one("a[href]")
        if title_node is None or homepage_node is None:
            raise TbnSchemaError("TBN schedule row schema changed")
        homepage = urljoin("https://www.tbn.or.kr", str(homepage_node["href"]))
        forum_ids = parse_qs(urlsplit(homepage).query).get("forum_seq", [])
        if not forum_ids:
            raise TbnSchemaError("TBN schedule row program ID is missing")
        parsed.append(
            (
                f"{int(hour):02d}:{int(minute):02d}",
                title_node.get_text(" ", strip=True),
                forum_ids[0],
                homepage,
            )
        )
    if not parsed:
        raise TbnSchemaError("TBN station schedule is empty")

    rows: list[ScheduleRow] = []
    for index, (start, title, forum_id, homepage) in enumerate(parsed):
        end = parsed[index + 1][0] if index + 1 < len(parsed) else "30:00"
        rows.append(
            ScheduleRow(
                upstream_id=(f"{station_code}:{expected_date.isoformat()}:{start}:{forum_id}"),
                broadcast_date=expected_date,
                start=start,
                end=end,
                title=title,
                homepage_url=homepage,
            )
        )
    return tuple(rows)


class _Client(Protocol):
    async def get(self, url: str) -> httpx.Response: ...


class TbnAdapter:
    """13개 지역별 공식 TBN HTML을 독립 채널로 수집한다."""

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
                    parse_tbn_html(
                        response.text,
                        expected_date=current,
                        station_code=channel.upstream_code,
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
