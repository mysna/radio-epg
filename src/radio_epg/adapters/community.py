"""공동체 라디오 mapping과 보수적인 primary/fallback 병합."""

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from radio_epg.adapters.base import CollectionWindow
from radio_epg.adapters.community_ocr import fetch_kjfm_schedule_image, kjfm_gwangju_fm
from radio_epg.adapters.html_schedule import (
    ChannelMapping,
    ChannelMappingFile,
    ScheduleRow,
    normalize_rows,
)
from radio_epg.broadcast_time import parse_broadcast_interval
from radio_epg.config import SourceConfig
from radio_epg.models import AdapterResult
from radio_epg.validation import SchedulePolicy

_OcrParser = Callable[[bytes, date], dict[str, tuple[ScheduleRow, ...]]]
_ImageFetcher = Callable[[Any], Awaitable[bytes]]
_PARSERS: dict[str, _OcrParser] = {
    "community.kjfm.main": kjfm_gwangju_fm,
}
_IMAGE_FETCHERS: dict[str, _ImageFetcher] = {
    "community.kjfm.main": fetch_kjfm_schedule_image,
}

CommunityStatus = Literal["enabled", "unsupported"]
FallbackKind = Literal["official", "wiki", "inferred", "ocr"]


class CommunityMappingError(ValueError):
    """community/AFN mapping이 strict schema와 다를 때 발생한다."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CommunityChannelMapping(_StrictModel):
    channel_id: str = Field(min_length=1)
    family: Literal["community", "afn"]
    status: CommunityStatus
    official_site: str = Field(pattern=r"^https://")
    schedule_format: str = Field(min_length=1)
    primary_source: str = Field(pattern=r"^https://")
    fallback_source: Annotated[str, Field(pattern=r"^https://")] | None = None
    confidence: float = Field(ge=0, le=1)
    last_verified: date
    reason: str | None = None

    @model_validator(mode="after")
    def status_fields_are_consistent(self) -> Self:
        if self.status == "unsupported" and not self.reason:
            raise ValueError("unsupported community mapping requires a reason")
        if self.status == "enabled" and self.reason is not None:
            raise ValueError("enabled community mapping must not include a reason")
        return self


class CommunityMapping(_StrictModel):
    schema_version: Literal[1]
    channels: tuple[CommunityChannelMapping, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def channel_ids_are_unique(self) -> Self:
        channel_ids = [item.channel_id for item in self.channels]
        if len(channel_ids) != len(set(channel_ids)):
            raise ValueError("community mapping channel IDs must be unique")
        return self


@dataclass(frozen=True, slots=True)
class SourcedScheduleRow:
    """편성 행과 fallback provenance를 함께 보존한다."""

    row: ScheduleRow
    source_kind: FallbackKind


class CommunityUnavailableError(ValueError):
    """fixture-verified enabled community source가 없을 때 발생한다."""


def load_community_mapping(path: Path) -> CommunityMapping:
    """community/AFN mapping을 읽는다."""
    try:
        return CommunityMapping.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise CommunityMappingError("community mapping schema changed") from error


def _overlaps(first: ScheduleRow, second: ScheduleRow) -> bool:
    first_start, first_end = parse_broadcast_interval(first.broadcast_date, first.start, first.end)
    second_start, second_end = parse_broadcast_interval(
        second.broadcast_date, second.start, second.end
    )
    return first_start < second_end and second_start < first_end


def merge_schedule_rows(
    official: list[SourcedScheduleRow] | tuple[SourcedScheduleRow, ...],
    fallback: list[SourcedScheduleRow] | tuple[SourcedScheduleRow, ...],
) -> tuple[SourcedScheduleRow, ...]:
    """fallback은 기존 고우선순위 행과 전혀 겹치지 않는 구간만 채운다."""
    if any(item.source_kind != "official" for item in official):
        raise ValueError("official rows must use the official source kind")
    accepted = list(official)
    for candidate in fallback:
        if candidate.source_kind == "official":
            raise ValueError("fallback rows must have a fallback source kind")
        if any(_overlaps(candidate.row, current.row) for current in accepted):
            continue
        accepted.append(candidate)
    accepted.sort(
        key=lambda item: parse_broadcast_interval(
            item.row.broadcast_date, item.row.start, item.row.end
        )[0]
    )
    return tuple(accepted)


class CommunityAdapter:
    """검증되지 않은 community source를 자동 활성화하지 않는 수집 경계."""

    schedule_policy = SchedulePolicy(allow_adjacent=True)

    def __init__(
        self,
        source: SourceConfig,
        *,
        mapping_path: Path | None = None,
        client: Any | None = None,
    ) -> None:
        self.source = source
        path = mapping_path or Path(__file__).parents[3] / "data" / "mappings" / "community.json"
        self._mapping = load_community_mapping(path)
        self._client = client

    async def collect(self, window: CollectionWindow) -> AdapterResult:
        if self._client is not None:
            return await self._collect_with(self._client, window)
        import httpx

        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            return await self._collect_with(client, window)

    async def _collect_with(self, client: Any, window: CollectionWindow) -> AdapterResult:
        enabled = tuple(
            item
            for item in self._mapping.channels
            if item.family == self.family and item.status == "enabled"
        )
        if not enabled:
            raise CommunityUnavailableError("no fixture-verified community source is enabled")

        collected: dict[str, list[ScheduleRow]] = defaultdict(list)
        day = window.start
        while day <= window.end:
            for item in enabled:
                parser = _PARSERS.get(item.channel_id)
                fetch_image = _IMAGE_FETCHERS.get(item.channel_id)
                if parser is None or fetch_image is None:
                    raise CommunityUnavailableError(
                        f"enabled community source requires a configured parser: {item.channel_id}"
                    )
                try:
                    image_bytes = await fetch_image(client)
                    parsed = parser(image_bytes, day)
                except ValueError as error:
                    if "no rows" not in str(error):
                        raise
                    parsed = {}
                for channel_id, rows in parsed.items():
                    collected[channel_id].extend(rows)
            day += timedelta(days=1)

        mapping = ChannelMappingFile(
            channels=tuple(
                ChannelMapping(
                    channel_id=item.channel_id,
                    upstream_code=item.channel_id,
                    url=item.primary_source,
                    parser="community-ocr",
                    evidence_date=window.start,
                )
                for item in enabled
            )
        )
        return normalize_rows(
            source=self.source,
            mapping=mapping,
            catalog_path=Path(__file__).parents[3] / "data" / "radio_channels.json",
            rows=collected,
            fetched_at=datetime.now(UTC),
        )

    family = "community"
