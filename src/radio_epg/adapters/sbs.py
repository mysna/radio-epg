"""SBS 파워FM, 러브FM, 고릴라디오M daily JSON adapter."""

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
)
from radio_epg.broadcast_time import KST
from radio_epg.config import SourceConfig
from radio_epg.http import PoliteHttpClient
from radio_epg.models import AdapterResult
from radio_epg.validation import SchedulePolicy

_ROOT = Path(__file__).parents[3]
_MAPPING = _ROOT / "data" / "mappings" / "sbs.json"
_CATALOG = _ROOT / "data" / "radio_channels.json"
_CHANNELS = {"power", "love", "dmb"}


class SbsSchemaError(ValueError):
    """SBS daily JSON 구조가 검증된 계약과 다를 때 발생한다."""


class SbsUnavailableDateError(SbsSchemaError):
    """요청일 대신 다른 날짜 편성이 반환되어 재사용을 막을 때 발생한다."""


class _Client(Protocol):
    async def get(self, url: str) -> httpx.Response: ...


def parse_sbs_schedule(
    payload: object, *, expected_date: date
) -> dict[str, tuple[ScheduleRow, ...]]:
    """요청일과 실제 편성일이 모두 일치하는 SBS daily JSON만 허용한다."""
    if not isinstance(payload, dict):
        raise SbsSchemaError("SBS response must be an object")
    raw_payload = cast(dict[str, Any], payload)
    if raw_payload.get("requestedDate") != expected_date.isoformat():
        raise SbsSchemaError("SBS requested date is missing or changed")
    if raw_payload.get("scheduleDate") != expected_date.isoformat():
        raise SbsUnavailableDateError(f"SBS schedule unavailable for {expected_date.isoformat()}")
    try:
        parsed = parse_json_channel_rows(
            raw_payload,
            expected_date=expected_date,
            date_key="scheduleDate",
            channels_key="channels",
            allowed_channels=_CHANNELS,
        )
    except ValueError as error:
        raise SbsSchemaError(str(error)) from error
    if not parsed or not any(parsed.values()):
        raise SbsSchemaError("SBS schedule response is empty")
    return parsed


def parse_sbs_current_schedule(
    payload: object, *, expected_date: date, today: date
) -> dict[str, tuple[ScheduleRow, ...]]:
    """날짜 필드가 없는 SBS current-day 응답을 오늘에만 귀속한다."""
    if expected_date != today:
        raise SbsUnavailableDateError(f"SBS schedule unavailable for {expected_date.isoformat()}")
    if not isinstance(payload, dict):
        raise SbsSchemaError("SBS current schedule schema changed")
    raw_payload = cast(dict[str, Any], payload)
    raw_channels_value = raw_payload.get("schedule")
    if not isinstance(raw_channels_value, dict):
        raise SbsSchemaError("SBS current schedule schema changed")
    raw_channels = cast(dict[str, Any], raw_channels_value)
    if set(raw_channels) != _CHANNELS:
        raise SbsSchemaError("SBS current schedule channel set changed")
    parsed: dict[str, tuple[ScheduleRow, ...]] = {}
    for channel, raw_rows in raw_channels.items():
        if not isinstance(raw_rows, list):
            raise SbsSchemaError("SBS current schedule rows changed")
        rows: list[ScheduleRow] = []
        for raw in raw_rows:
            if not isinstance(raw, dict):
                raise SbsSchemaError("SBS current schedule row changed")
            item = cast(dict[str, Any], raw)
            required = (
                item.get("vod_id"),
                item.get("start_time"),
                item.get("end_time"),
                item.get("title"),
            )
            if not all(isinstance(value, str) for value in required):
                raise SbsSchemaError("SBS current schedule row fields changed")
            vod_id, start, end, title = cast(tuple[str, str, str, str], required)
            rows.append(
                ScheduleRow(
                    upstream_id=f"{vod_id}:{start}",
                    broadcast_date=expected_date,
                    start=start.zfill(5),
                    end=end.zfill(5),
                    title=title,
                    homepage_url=(
                        item["hom_url"] if isinstance(item.get("hom_url"), str) else None
                    ),
                    is_live=item.get("onair_flag") == "Y",
                )
            )
        parsed[channel] = tuple(rows)
    if not all(parsed.values()):
        raise SbsSchemaError("SBS current schedule is empty")
    return parsed


class SbsAdapter:
    """날짜가 확인된 SBS daily 편성만 모으고 미래 반복 응답은 기록한다."""

    schedule_policy = SchedulePolicy(allow_adjacent=True)

    def __init__(
        self,
        source: SourceConfig,
        *,
        client: _Client | None = None,
        mapping_path: Path = _MAPPING,
        catalog_path: Path = _CATALOG,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        today: Callable[[], date] = lambda: datetime.now(KST).date(),
    ) -> None:
        self.source = source
        self._client = client
        self._mapping = load_channel_mapping(mapping_path)
        self._catalog_path = catalog_path
        self._now = now
        self._today = today

    async def collect(self, window: CollectionWindow) -> AdapterResult:
        if self._client is not None:
            return await self._collect_with(self._client, window)
        async with PoliteHttpClient() as client:
            return await self._collect_with(client, window)

    async def _collect_with(self, client: _Client, window: CollectionWindow) -> AdapterResult:
        endpoint = self._mapping.channels[0].url
        collected: dict[str, list[ScheduleRow]] = defaultdict(list)
        unavailable: list[str] = []
        today = self._today()
        current = window.start
        response_payload: object | None = None
        while current <= window.end:
            if current == today:
                if response_payload is None:
                    response_payload = (await client.get(endpoint)).json()
                parsed = parse_sbs_current_schedule(
                    response_payload, expected_date=current, today=today
                )
                for code, rows in parsed.items():
                    collected[code].extend(rows)
            else:
                unavailable.append(f"unavailable:{current.isoformat()}")
            current += timedelta(days=1)
        if not collected:
            raise SbsUnavailableDateError("SBS schedule is unavailable for the requested window")
        return normalize_rows(
            source=self.source,
            mapping=self._mapping,
            catalog_path=self._catalog_path,
            rows=collected,
            fetched_at=self._now(),
            errors=unavailable,
        )
