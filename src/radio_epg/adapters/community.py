"""공동체 라디오 mapping과 보수적인 primary/fallback 병합."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from radio_epg.adapters.base import CollectionWindow
from radio_epg.adapters.html_schedule import ScheduleRow
from radio_epg.broadcast_time import parse_broadcast_interval
from radio_epg.config import SourceConfig
from radio_epg.models import AdapterResult

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

    def __init__(self, source: SourceConfig, *, mapping_path: Path | None = None) -> None:
        self.source = source
        path = mapping_path or Path(__file__).parents[3] / "data" / "mappings" / "community.json"
        self._mapping = load_community_mapping(path)

    async def collect(self, window: CollectionWindow) -> AdapterResult:
        del window
        enabled = tuple(
            item
            for item in self._mapping.channels
            if item.family == self.family and item.status == "enabled"
        )
        if not enabled:
            raise CommunityUnavailableError("no fixture-verified community source is enabled")
        raise CommunityUnavailableError("enabled community source requires a configured parser")

    family = "community"
