"""HTML/JSONP 편성표가 공유하는 엄격한 파싱과 정규화 도구."""

import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from radio_epg.broadcast_time import parse_broadcast_interval
from radio_epg.catalog import RadioCatalog, load_catalog
from radio_epg.config import SourceConfig
from radio_epg.models import (
    AdapterResult,
    Channel,
    ProgramCandidate,
    ScheduleCandidate,
    SourceMetadata,
)

_CALLBACK = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*")


class JsonpError(ValueError):
    """JSONP가 callback 하나와 JSON 인자 하나라는 경계를 벗어났을 때 발생한다."""


class MappingSchemaError(ValueError):
    """채널 mapping 파일이 엄격한 계약과 다를 때 발생한다."""


@dataclass(frozen=True, slots=True)
class ScheduleRow:
    """소스별 파서와 공통 정규화 경계 사이의 최소 편성 행."""

    upstream_id: str
    broadcast_date: date
    start: str
    end: str
    title: str
    subtitle: str | None = None
    homepage_url: str | None = None
    is_live: bool = False
    is_rerun: bool = False
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not self.upstream_id.strip() or not self.title.strip():
            raise ValueError("schedule row ID and title must not be blank")
        if not 0 <= self.confidence <= 1:
            raise ValueError("schedule row confidence must be between 0 and 1")
        starts_at, ends_at = parse_broadcast_interval(self.broadcast_date, self.start, self.end)
        if ends_at <= starts_at:
            raise ValueError("schedule row end must follow start")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChannelMapping(_StrictModel):
    channel_id: str = Field(min_length=1)
    upstream_code: str = Field(min_length=1)
    url: str = Field(min_length=1)
    parser: str = Field(min_length=1)
    evidence_date: date


class UnsupportedMapping(_StrictModel):
    channel_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    last_investigated: date


class ChannelMappingFile(_StrictModel):
    channels: tuple[ChannelMapping, ...] = Field(min_length=1)
    unsupported: tuple[UnsupportedMapping, ...] = ()

    @model_validator(mode="after")
    def identities_must_be_unique(self) -> "ChannelMappingFile":
        channel_ids = [item.channel_id for item in (*self.channels, *self.unsupported)]
        upstream_codes = [item.upstream_code for item in self.channels]
        if len(channel_ids) != len(set(channel_ids)):
            raise ValueError("mapping channel IDs must be unique")
        if len(upstream_codes) != len(set(upstream_codes)):
            raise ValueError("enabled upstream codes must be unique")
        return self


def parse_jsonp(text: str, *, callback: str | None = None) -> Any:
    """callback(JSON) 이외의 JavaScript를 허용하지 않고 JSON 인자 하나만 읽는다."""
    source = text.strip()
    match = _CALLBACK.match(source)
    if match is None or (callback is not None and match.group() != callback):
        raise JsonpError("JSONP callback is missing or unexpected")
    cursor = match.end()
    if cursor >= len(source) or source[cursor] != "(":
        raise JsonpError("JSONP callback must be followed by one argument")
    cursor += 1
    while cursor < len(source) and source[cursor].isspace():
        cursor += 1
    try:
        value, consumed = json.JSONDecoder().raw_decode(source[cursor:])
    except json.JSONDecodeError as error:
        raise JsonpError("JSONP argument is not JSON") from error
    tail = source[cursor + consumed :].strip()
    if not re.fullmatch(r"\)\s*;?", tail):
        raise JsonpError("JSONP must contain exactly one JSON argument")
    return value


def parse_html_schedule(
    text: str,
    *,
    expected_date: date,
    container_selector: str = ".schedule",
    row_selector: str = "li, article",
) -> dict[str, tuple[ScheduleRow, ...]]:
    """data 속성 기반 HTML 편성 행을 채널별로 파싱한다."""
    soup = BeautifulSoup(text, "html.parser")
    parsed: dict[str, list[ScheduleRow]] = defaultdict(list)
    for container in soup.select(container_selector):
        channel = container.get("data-channel")
        schedule_date = container.get("data-date")
        if not isinstance(channel, str) or schedule_date != expected_date.isoformat():
            continue
        for item in container.select(row_selector):
            upstream_id = item.get("data-event-id")
            start = item.get("data-start")
            end = item.get("data-end")
            title_node = item.select_one(".title")
            if (
                not isinstance(upstream_id, str)
                or not isinstance(start, str)
                or not isinstance(end, str)
            ):
                raise ValueError("HTML schedule row is missing required data attributes")
            if title_node is None:
                raise ValueError("HTML schedule row is missing a title")
            subtitle_node = item.select_one(".subtitle")
            homepage_node = item.select_one("a.title[href]")
            parsed[channel].append(
                ScheduleRow(
                    upstream_id=upstream_id,
                    broadcast_date=expected_date,
                    start=start,
                    end=end,
                    title=title_node.get_text(" ", strip=True),
                    subtitle=(
                        subtitle_node.get_text(" ", strip=True)
                        if subtitle_node is not None
                        else None
                    ),
                    homepage_url=(
                        str(homepage_node["href"]) if homepage_node is not None else None
                    ),
                    is_live=item.get("data-live") == "true",
                    is_rerun=item.get("data-rerun") == "true",
                )
            )
    return {channel: tuple(rows) for channel, rows in parsed.items()}


def parse_json_channel_rows(
    payload: object,
    *,
    expected_date: date,
    date_key: str,
    channels_key: str,
    allowed_channels: set[str],
) -> dict[str, tuple[ScheduleRow, ...]]:
    """명시적 날짜와 channel 객체를 가진 JSON을 엄격한 공통 행으로 변환한다."""
    if not isinstance(payload, dict):
        raise ValueError("schedule response must be an object")
    raw_payload = cast(dict[str, Any], payload)
    if raw_payload.get(date_key) != expected_date.isoformat():
        raise ValueError("schedule response date does not match the requested date")
    raw_channels = raw_payload.get(channels_key)
    if not isinstance(raw_channels, dict):
        raise ValueError("schedule response channels must be an object")
    unknown = set(raw_channels) - allowed_channels
    if unknown:
        raise ValueError(f"schedule response contains unknown channels: {sorted(unknown)!r}")
    parsed: dict[str, tuple[ScheduleRow, ...]] = {}
    for channel, raw_rows in raw_channels.items():
        if not isinstance(channel, str) or not isinstance(raw_rows, list):
            raise ValueError("schedule channel rows must be an array")
        rows: list[ScheduleRow] = []
        for raw in raw_rows:
            if not isinstance(raw, dict):
                raise ValueError("schedule row must be an object")
            required = (raw.get("id"), raw.get("start"), raw.get("end"), raw.get("title"))
            if not all(isinstance(value, str) for value in required):
                raise ValueError("schedule row is missing required string fields")
            optional_strings: dict[str, str | None] = {}
            for key in ("subtitle", "homepage"):
                value = raw.get(key)
                if value is not None and not isinstance(value, str):
                    raise ValueError(f"schedule row {key} must be a string")
                optional_strings[key] = value
            for key in ("live", "rerun"):
                if key in raw and not isinstance(raw[key], bool):
                    raise ValueError(f"schedule row {key} must be a boolean")
            rows.append(
                ScheduleRow(
                    upstream_id=required[0],
                    broadcast_date=expected_date,
                    start=required[1],
                    end=required[2],
                    title=required[3],
                    subtitle=optional_strings["subtitle"],
                    homepage_url=optional_strings["homepage"],
                    is_live=raw.get("live", False),
                    is_rerun=raw.get("rerun", False),
                )
            )
        parsed[channel] = tuple(rows)
    return parsed


def load_channel_mapping(path: Path) -> ChannelMappingFile:
    """엄격한 채널 mapping 파일을 읽는다."""
    try:
        return ChannelMappingFile.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise MappingSchemaError(f"invalid channel mapping: {path.name}") from error


def catalog_channels(mapping: ChannelMappingFile, catalog: RadioCatalog) -> tuple[Channel, ...]:
    """mapping에 활성화된 정규 채널과 기존 radio ID 별칭을 결합한다."""
    aliases: dict[str, list[str]] = defaultdict(list)
    for radio_id, channel_id in catalog.radio_aliases.items():
        aliases[channel_id].append(radio_id)
    channels: list[Channel] = []
    for item in mapping.channels:
        catalog_channel = catalog.channels.get(item.channel_id)
        if catalog_channel is None:
            raise MappingSchemaError(f"mapping references unknown channel {item.channel_id!r}")
        channels.append(
            Channel(
                channel_id=catalog_channel.channel_id,
                broadcaster_id=catalog_channel.stn,
                name=catalog_channel.name,
                stn=catalog_channel.stn,
                ch=catalog_channel.ch,
                city=catalog_channel.city,
                region_ids=catalog_channel.region_ids,
                radio_ids=tuple(aliases[item.channel_id]),
            )
        )
    return tuple(channels)


def normalize_rows(
    *,
    source: SourceConfig,
    mapping: ChannelMappingFile,
    catalog_path: Path,
    rows: Mapping[str, Sequence[ScheduleRow]],
    fetched_at: datetime | None = None,
    errors: Sequence[str] = (),
) -> AdapterResult:
    """채널별 파서 행을 공유 도메인 모델로 변환한다."""
    timestamp = fetched_at or datetime.now(UTC)
    catalog = load_catalog(catalog_path)
    by_upstream = {item.upstream_code: item for item in mapping.channels}
    unknown = set(rows) - set(by_upstream)
    if unknown:
        raise MappingSchemaError(f"response contains unmapped channels: {sorted(unknown)!r}")
    programs: dict[str, ProgramCandidate] = {}
    schedules: list[ScheduleCandidate] = []
    for upstream_code, channel_rows in rows.items():
        channel_mapping = by_upstream[upstream_code]
        for row in channel_rows:
            starts_at, ends_at = parse_broadcast_interval(row.broadcast_date, row.start, row.end)
            program_id = f"{source.source_id}:{upstream_code}:{row.upstream_id}"
            programs.setdefault(
                program_id,
                ProgramCandidate(
                    source_id=source.source_id,
                    program_id=program_id,
                    title=row.title,
                    homepage_url=row.homepage_url,
                ),
            )
            schedules.append(
                ScheduleCandidate(
                    source_id=source.source_id,
                    source_url=channel_mapping.url,
                    source_kind=source.source_kind,
                    fetched_at=timestamp,
                    confidence=row.confidence,
                    channel_id=channel_mapping.channel_id,
                    program_id=program_id,
                    source_event_id=f"{upstream_code}:{row.upstream_id}",
                    broadcast_date=row.broadcast_date,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    title=row.title,
                    subtitle=row.subtitle,
                    is_live=row.is_live,
                    is_rerun=row.is_rerun,
                )
            )
    return AdapterResult(
        source=SourceMetadata(
            source_id=source.source_id,
            name=source.name,
            source_kind=source.source_kind,
            source_url=source.source_url,
            priority=source.priority,
            fetched_at=timestamp,
        ),
        channels=catalog_channels(mapping, catalog),
        programs=tuple(programs.values()),
        schedules=tuple(schedules),
        errors=tuple(errors),
    )
