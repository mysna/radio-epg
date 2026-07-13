"""공식 KBS weekly JSON을 정규화하는 reference adapter."""

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Protocol, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from radio_epg.adapters.base import CollectionWindow
from radio_epg.broadcast_time import parse_broadcast_interval
from radio_epg.catalog import RadioCatalog, load_catalog
from radio_epg.config import SourceConfig
from radio_epg.http import PoliteHttpClient
from radio_epg.models import (
    AdapterResult,
    Channel,
    ImageCandidate,
    ProgramCandidate,
    ScheduleCandidate,
    SourceMetadata,
)
from radio_epg.validation import SchedulePolicy

KBS_WEEKLY_ENDPOINT = "https://static.api.kbs.co.kr/mediafactory/v1/schedule/weekly"
_ROOT = Path(__file__).parents[3]
_DEFAULT_MAPPING = _ROOT / "data" / "mappings" / "kbs.json"
_DEFAULT_CATALOG = _ROOT / "data" / "radio_channels.json"


class KbsSchemaError(ValueError):
    """KBS 응답 또는 mapping 구조가 알려진 계약과 달라졌을 때 발생한다."""


class KbsEmptyScheduleError(ValueError):
    """KBS가 유효한 편성 없이 응답했을 때 기존 데이터를 보호한다."""


class _HttpClient(Protocol):
    async def get(self, url: str) -> httpx.Response:
        """한 KBS weekly URL을 조회한다."""
        ...


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


_ChannelCode = Annotated[str, Field(pattern=r"^\d{2}$")]


class _MappingItem(_StrictModel):
    channel_id: str = Field(min_length=1)
    local_station_code: _ChannelCode
    channel_code: _ChannelCode
    schedule_channel_codes: tuple[_ChannelCode, ...] = ()

    @property
    def allowed_schedule_codes(self) -> tuple[str, ...]:
        return self.schedule_channel_codes or (self.channel_code,)


class _MappingFile(_StrictModel):
    station_relays: dict[_ChannelCode, _ChannelCode] = Field(default_factory=dict)
    channels: tuple[_MappingItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def mappings_must_be_unique(self) -> Self:
        channel_ids = [item.channel_id for item in self.channels]
        upstream_keys = [(item.local_station_code, item.channel_code) for item in self.channels]
        if len(channel_ids) != len(set(channel_ids)):
            raise ValueError("KBS channel mappings must have unique channel IDs")
        if len(upstream_keys) != len(set(upstream_keys)):
            raise ValueError("KBS channel mappings must have unique upstream keys")
        station_codes = {item.local_station_code for item in self.channels}
        if not set(self.station_relays).issubset(station_codes):
            raise ValueError("KBS relay mapping references an unknown station")
        if not set(self.station_relays.values()).issubset(station_codes):
            raise ValueError("KBS relay mapping references an unknown parent station")
        return self


class _BoundaryModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class _SchedulePayload(_BoundaryModel):
    schedule_unique_id: int | str
    program_planned_date: str = Field(pattern=r"^\d{8}$")
    local_station_code: str = Field(pattern=r"^\d{2}$")
    channel_code: str = Field(pattern=r"^\d{2}$")
    program_planned_start_time: str = Field(pattern=r"^\d{8}$")
    program_planned_end_time: str = Field(pattern=r"^\d{8}$")
    program_code: str | None = None
    program_title: str
    program_subtitle: str | None = None
    programming_table_title: str | None = None
    rerun_classification: str | None = None
    production_type: str | None = None
    program_actor: str | None = None
    program_intention: str | None = None
    program_genre: str | None = None
    image_w: str | None = None
    homepage_url: str | None = None

    @model_validator(mode="after")
    def one_title_must_be_present(self) -> Self:
        if not (self.programming_table_title or self.program_title).strip():
            raise ValueError("KBS schedule must contain a display title")
        return self


class _ChannelPayload(_BoundaryModel):
    program_planned_date: str = Field(pattern=r"^\d{8}$")
    local_station_code: str = Field(pattern=r"^\d{2}$")
    channel_code: str = Field(pattern=r"^\d{2}$")
    schedules: tuple[_SchedulePayload, ...]


_WEEKLY_RESPONSE = TypeAdapter(tuple[_ChannelPayload, ...])


def _load_mapping(path: Path) -> _MappingFile:
    try:
        return _MappingFile.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise KbsSchemaError("KBS mapping schema changed") from error


def _parse_payload(payload: Any) -> tuple[_ChannelPayload, ...]:
    try:
        return _WEEKLY_RESPONSE.validate_python(payload)
    except ValidationError as error:
        raise KbsSchemaError("KBS weekly response schema changed") from error


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as error:
        raise KbsSchemaError("KBS weekly response contains an invalid date") from error


def _clock(value: str) -> str:
    return f"{int(value[:2])}:{value[2:4]}"


def _program_id(program_code: str) -> str:
    return f"kbs:{program_code}"


def _hosts(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _catalog_channels(
    mapping: _MappingFile,
    catalog: RadioCatalog,
) -> tuple[Channel, ...]:
    radio_ids: dict[str, list[str]] = defaultdict(list)
    for radio_id, channel_id in catalog.radio_aliases.items():
        radio_ids[channel_id].append(radio_id)

    channels: list[Channel] = []
    for item in mapping.channels:
        catalog_channel = catalog.channels.get(item.channel_id)
        if catalog_channel is None:
            raise KbsSchemaError(f"KBS mapping references unknown channel {item.channel_id!r}")
        channels.append(
            Channel(
                channel_id=catalog_channel.channel_id,
                broadcaster_id="kbs",
                name=catalog_channel.name,
                stn=catalog_channel.stn,
                ch=catalog_channel.ch,
                city=catalog_channel.city,
                region_ids=catalog_channel.region_ids,
                radio_ids=tuple(radio_ids[item.channel_id]),
            )
        )
    return tuple(channels)


def _request_url(station: str, channel_codes: list[str], window: CollectionWindow) -> str:
    params = httpx.QueryParams(
        {
            "local_station_code": station,
            "channel_code": ",".join(channel_codes),
            "program_planned_date_from": window.start.strftime("%Y%m%d"),
            "program_planned_date_to": window.end.strftime("%Y%m%d"),
        }
    )
    return f"{KBS_WEEKLY_ENDPOINT}?{params}"


def _request_windows(window: CollectionWindow) -> tuple[CollectionWindow, ...]:
    """KBS의 최대 7개 날짜 검색 제한에 맞춰 수집 창을 분할한다."""
    chunks: list[CollectionWindow] = []
    current = window.start
    while current <= window.end:
        chunk_end = min(current + timedelta(days=6), window.end)
        chunks.append(CollectionWindow(current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return tuple(chunks)


class KbsAdapter:
    """KBS 본사와 지역 라디오를 공식 weekly endpoint에서 수집한다."""

    source: SourceConfig
    schedule_policy = SchedulePolicy(allow_adjacent=True)

    def __init__(
        self,
        source: SourceConfig,
        *,
        client: _HttpClient | None = None,
        mapping_path: Path = _DEFAULT_MAPPING,
        catalog_path: Path = _DEFAULT_CATALOG,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.source = source
        self._client = client
        self._mapping = _load_mapping(mapping_path)
        self._catalog = load_catalog(catalog_path)
        self._now = now

    async def collect(self, window: CollectionWindow) -> AdapterResult:
        """station code별 요청을 합쳐 정규화된 KBS 결과를 만든다."""
        if self._client is not None:
            return await self._collect_with(self._client, window)
        async with PoliteHttpClient() as client:
            return await self._collect_with(client, window)

    async def _collect_with(self, client: _HttpClient, window: CollectionWindow) -> AdapterResult:
        grouped: dict[str, list[str]] = defaultdict(list)
        for item in self._mapping.channels:
            grouped[item.local_station_code].append(item.channel_code)

        payloads: list[_ChannelPayload] = []
        for station, channel_codes in sorted(grouped.items()):
            for request_window in _request_windows(window):
                response = await client.get(
                    _request_url(station, sorted(channel_codes), request_window)
                )
                try:
                    payloads.extend(_parse_payload(response.json()))
                except ValueError as error:
                    if isinstance(error, KbsSchemaError):
                        raise
                    raise KbsSchemaError("KBS weekly response schema changed") from error

        return self._normalize(tuple(payloads))

    def _normalize(self, payloads: tuple[_ChannelPayload, ...]) -> AdapterResult:
        mappings = {
            (item.local_station_code, item.channel_code): item for item in self._mapping.channels
        }
        fetched_at = self._now()
        programs: dict[str, ProgramCandidate] = {}
        images: dict[str, ImageCandidate] = {}
        schedules: list[ScheduleCandidate] = []

        for group in payloads:
            mapping = mappings.get((group.local_station_code, group.channel_code))
            if mapping is None:
                raise KbsSchemaError("KBS weekly response contains an unmapped channel")
            allowed_station_codes = {group.local_station_code}
            if group.local_station_code != "00":
                allowed_station_codes.add("00")
            relay_station = self._mapping.station_relays.get(group.local_station_code)
            if relay_station is not None:
                allowed_station_codes.add(relay_station)
            for item in group.schedules:
                if (
                    item.local_station_code not in allowed_station_codes
                    or item.channel_code not in mapping.allowed_schedule_codes
                ):
                    group_key = f"{group.local_station_code}/{group.channel_code}"
                    item_key = f"{item.local_station_code}/{item.channel_code}"
                    raise KbsSchemaError(
                        f"KBS weekly response channel grouping changed: {group_key} -> {item_key}"
                    )
                broadcast_date = _parse_date(item.program_planned_date)
                starts_at, ends_at = parse_broadcast_interval(
                    broadcast_date,
                    _clock(item.program_planned_start_time),
                    _clock(item.program_planned_end_time),
                )
                program_id = _program_id(item.program_code) if item.program_code else None
                title = (item.programming_table_title or item.program_title).strip()
                schedules.append(
                    ScheduleCandidate(
                        source_id=self.source.source_id,
                        source_url=KBS_WEEKLY_ENDPOINT,
                        source_kind=self.source.source_kind,
                        fetched_at=fetched_at,
                        confidence=1,
                        channel_id=mapping.channel_id,
                        program_id=program_id,
                        source_event_id=str(item.schedule_unique_id),
                        broadcast_date=broadcast_date,
                        starts_at=starts_at,
                        ends_at=ends_at,
                        title=title,
                        subtitle=item.program_subtitle or None,
                        is_live=item.production_type == "생방",
                        is_rerun=item.rerun_classification == "재방",
                    )
                )
                if program_id is None:
                    continue
                programs.setdefault(
                    program_id,
                    ProgramCandidate(
                        source_id=self.source.source_id,
                        program_id=program_id,
                        title=title,
                        description=item.program_intention,
                        hosts=_hosts(item.program_actor),
                        genre=item.program_genre,
                        homepage_url=item.homepage_url,
                    ),
                )
                if item.image_w:
                    images.setdefault(
                        program_id,
                        ImageCandidate(
                            entity_type="program",
                            entity_id=program_id,
                            source_url=item.image_w,
                            source_page_url=item.homepage_url or self.source.source_url,
                            rights_status="unknown",
                        ),
                    )

        if not schedules:
            raise KbsEmptyScheduleError("KBS weekly response is empty")

        source = SourceMetadata(
            source_id=self.source.source_id,
            name=self.source.name,
            source_kind=self.source.source_kind,
            source_url=self.source.source_url,
            priority=self.source.priority,
            fetched_at=fetched_at,
        )
        return AdapterResult(
            source=source,
            channels=_catalog_channels(self._mapping, self._catalog),
            programs=tuple(programs.values()),
            schedules=tuple(schedules),
            images=tuple(images.values()),
        )
