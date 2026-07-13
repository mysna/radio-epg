"""지역·독립 방송 mapping의 엄격한 데이터 계약."""

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from radio_epg.catalog import RadioCatalog
from radio_epg.config import SourceConfig
from radio_epg.models import AdapterResult
from radio_epg.validation import SchedulePolicy

_ROOT = Path(__file__).parents[2]
_MAPPING = _ROOT / "data" / "mappings" / "regional.json"
_CATALOG = _ROOT / "data" / "radio_channels.json"

RegionalStatus = Literal["enabled", "unsupported"]


class RegionalMappingError(ValueError):
    """지역 mapping 구조나 catalog 소유권이 잘못됐을 때 발생한다."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RegionalChannelMapping(_StrictModel):
    """하나의 canonical identity에 대한 조사 결과."""

    channel_id: str = Field(min_length=1)
    family: str = Field(min_length=1)
    status: RegionalStatus
    source_url: str = Field(pattern=r"^https://")
    parser: str = Field(min_length=1)
    reason: str | None = None
    last_investigated: date

    @model_validator(mode="after")
    def unsupported_requires_a_reason(self) -> Self:
        if self.status == "unsupported" and not self.reason:
            raise ValueError("unsupported regional mapping requires a reason")
        if self.status == "enabled" and self.reason is not None:
            raise ValueError("enabled regional mapping must not include a reason")
        return self


class RegionalMapping(_StrictModel):
    """Task 11이 소유하는 모든 identity 목록."""

    schema_version: Literal[1]
    channels: tuple[RegionalChannelMapping, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def channel_ids_must_be_unique(self) -> Self:
        channel_ids = [item.channel_id for item in self.channels]
        if len(channel_ids) != len(set(channel_ids)):
            raise ValueError("regional mapping channel IDs must be unique")
        return self


def load_regional_mapping(path: Path) -> RegionalMapping:
    """지역 mapping을 strict schema로 읽는다."""
    try:
        return RegionalMapping.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise RegionalMappingError("regional mapping schema changed") from error


def validate_regional_catalog(mapping: RegionalMapping, catalog: RadioCatalog) -> None:
    """mapping identity가 실제 catalog에 존재하는지 검증한다."""
    unknown = {item.channel_id for item in mapping.channels} - set(catalog.channels)
    if unknown:
        unknown_ids = sorted(unknown)
        raise RegionalMappingError(f"regional mapping contains unknown channels: {unknown_ids!r}")


def channels_for_family(
    mapping: RegionalMapping, family: str
) -> tuple[RegionalChannelMapping, ...]:
    """mapping 순서를 유지하며 한 shared-CMS family를 선택한다."""
    return tuple(item for item in mapping.channels if item.family == family)


class RegionalUnavailableError(ValueError):
    """family에 fixture-verified enabled channel이 없을 때 발생한다."""


class _Client(Protocol):
    async def get(self, url: str) -> httpx.Response: ...


class ConfiguredRegionalAdapter:
    """공유 HTML 중간 형식을 mapping 설정으로 수집하는 지역 adapter."""

    family = ""
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
        self._mapping = load_regional_mapping(mapping_path)
        self._catalog_path = catalog_path
        self._now = now

    async def collect(self, window: object) -> AdapterResult:
        from radio_epg.adapters.base import CollectionWindow
        from radio_epg.http import PoliteHttpClient

        if not isinstance(window, CollectionWindow):
            raise TypeError("regional adapter requires CollectionWindow")
        if self._client is not None:
            return await self._collect_with(self._client, window)
        async with PoliteHttpClient() as client:
            return await self._collect_with(client, window)

    async def _collect_with(self, client: _Client, window: object) -> AdapterResult:
        from radio_epg.adapters.base import CollectionWindow
        from radio_epg.adapters.html_schedule import (
            ChannelMapping,
            ChannelMappingFile,
            ScheduleRow,
            normalize_rows,
            parse_html_schedule,
        )

        if not isinstance(window, CollectionWindow):
            raise TypeError("regional adapter requires CollectionWindow")
        family_channels = channels_for_family(self._mapping, self.family)
        enabled = tuple(item for item in family_channels if item.status == "enabled")
        if not enabled:
            raise RegionalUnavailableError(f"no enabled channels for {self.family}")
        rows: dict[str, list[ScheduleRow]] = defaultdict(list)
        current = window.start
        while current <= window.end:
            for item in enabled:
                url = item.source_url.format(
                    date=current.isoformat(), date_compact=current.strftime("%Y%m%d")
                )
                parsed = parse_html_schedule((await client.get(url)).text, expected_date=current)
                if set(parsed) != {item.channel_id}:
                    raise RegionalMappingError("regional response channel does not match mapping")
                rows[item.channel_id].extend(parsed[item.channel_id])
            current += timedelta(days=1)
        normalized_mapping = ChannelMappingFile(
            channels=tuple(
                ChannelMapping(
                    channel_id=item.channel_id,
                    upstream_code=item.channel_id,
                    url=item.source_url,
                    parser=item.parser,
                    evidence_date=item.last_investigated,
                )
                for item in enabled
            )
        )
        return normalize_rows(
            source=self.source,
            mapping=normalized_mapping,
            catalog_path=self._catalog_path,
            rows=rows,
            fetched_at=self._now(),
        )
