"""MBC 서울 표준FM, FM4U, 올댓뮤직 JSONP adapter."""

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, cast

import httpx

from radio_epg.adapters.base import CollectionWindow
from radio_epg.adapters.html_schedule import (
    ScheduleRow,
    load_channel_mapping,
    normalize_rows,
    parse_json_channel_rows,
    parse_jsonp,
)
from radio_epg.config import SourceConfig
from radio_epg.http import PoliteHttpClient
from radio_epg.models import AdapterResult
from radio_epg.validation import SchedulePolicy

_ROOT = Path(__file__).parents[3]
_MAPPING = _ROOT / "data" / "mappings" / "mbc.json"
_CATALOG = _ROOT / "data" / "radio_channels.json"
_CHANNELS = {"sfm", "fm4u", "chm"}


class MbcSchemaError(ValueError):
    """MBC JSONP가 검증된 fixture 계약과 다를 때 발생한다."""


class _Client(Protocol):
    async def get(self, url: str) -> httpx.Response: ...


def _clock(value: str) -> str:
    if len(value) != 4 or not value.isdigit():
        raise ValueError("MBC time must use HHMM")
    return f"{value[:2]}:{value[2:]}"


def _official_clock(value: str, *, day_offset: int) -> str:
    clock = _clock(value)
    hour, minute = (int(part) for part in clock.split(":"))
    return f"{hour + day_offset * 24:02d}:{minute:02d}"


def _parse_official_rows(
    payload: object, *, expected_date: date, channel_code: str
) -> dict[str, tuple[ScheduleRow, ...]]:
    if not isinstance(payload, list):
        raise ValueError("MBC schedule must be an array")
    rows: list[ScheduleRow] = []
    for raw in payload:
        if not isinstance(raw, dict):
            raise ValueError("MBC schedule row must be an object")
        item = cast(dict[str, Any], raw)
        required = (
            item.get("BroadDate"),
            item.get("BroadcastID"),
            item.get("StartTime"),
            item.get("EndTime"),
            item.get("Title"),
        )
        if not all(isinstance(value, str) for value in required):
            raise ValueError("MBC schedule row schema changed")
        row_date_text, schedule_id, start_text, end_text, title = cast(
            tuple[str, str, str, str, str], required
        )
        if row_date_text == expected_date.isoformat():
            day_offset = 0
        elif row_date_text == (expected_date + timedelta(days=1)).isoformat():
            start_minutes = int(start_text[:2]) * 60 + int(start_text[2:])
            end_minutes = int(end_text[:2]) * 60 + int(end_text[2:])
            if start_minutes >= 5 * 60 or end_minutes > 5 * 60:
                raise ValueError("MBC schedule date does not match the requested date")
            day_offset = 1
        else:
            raise ValueError("MBC schedule date does not match the requested date")
        start = _official_clock(start_text, day_offset=day_offset)
        end = _official_clock(end_text, day_offset=day_offset)
        image = item.get("OnAirImage") or item.get("Photo") or None
        homepage = item.get("HomepageURL") or None
        subtitle = item.get("SubTitle") or None
        optional = (image, homepage, subtitle)
        if any(value is not None and not isinstance(value, str) for value in optional):
            raise ValueError("MBC optional schedule fields changed")
        rows.append(
            ScheduleRow(
                upstream_id=f"{channel_code}:{expected_date.isoformat()}:{start}:{schedule_id}",
                broadcast_date=expected_date,
                start=start,
                end=end,
                title=title,
                subtitle=subtitle,
                image_url=image,
                homepage_url=homepage,
                is_live=item.get("IsOnAirNow") == "Y",
            )
        )
    return {channel_code: tuple(rows)}


def parse_mbc_schedule(
    text: str, *, expected_date: date, channel_code: str | None = None
) -> dict[str, tuple[ScheduleRow, ...]]:
    """MBC JSONP를 중앙 3개 채널의 편성 행으로 파싱한다."""
    try:
        payload = parse_jsonp(text, callback="scheduleCallback")
        parsed = (
            _parse_official_rows(payload, expected_date=expected_date, channel_code=channel_code)
            if channel_code is not None
            else parse_json_channel_rows(
                payload,
                expected_date=expected_date,
                date_key="date",
                channels_key="channels",
                allowed_channels=_CHANNELS,
            )
        )
    except ValueError as error:
        raise MbcSchemaError(str(error)) from error
    expected_channels = {channel_code} if channel_code is not None else _CHANNELS
    if set(parsed) != expected_channels or not any(parsed.values()):
        raise MbcSchemaError("MBC schedule response is empty")
    return parsed


class MbcAdapter:
    """요청 날짜별 MBC 중앙 JSONP를 수집한다."""

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
                parsed = parse_mbc_schedule(
                    response.text,
                    expected_date=current,
                    channel_code=channel.upstream_code,
                )
                collected[channel.upstream_code].extend(parsed[channel.upstream_code])
            current += timedelta(days=1)
        return normalize_rows(
            source=self.source,
            mapping=self._mapping,
            catalog_path=self._catalog_path,
            rows=collected,
            fetched_at=self._now(),
        )
