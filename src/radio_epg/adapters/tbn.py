"""TBN 13개 지역 공식 편성 adapter."""

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx

from radio_epg.adapters.base import CollectionWindow
from radio_epg.adapters.html_schedule import (
    ScheduleRow,
    load_channel_mapping,
    normalize_rows,
    parse_html_schedule,
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
    try:
        parsed = parse_html_schedule(text, expected_date=expected_date)
    except ValueError as error:
        raise TbnSchemaError(str(error)) from error
    if set(parsed) != {station_code} or not parsed[station_code]:
        raise TbnSchemaError("TBN station schedule is empty or mismatched")
    return parsed[station_code]


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
