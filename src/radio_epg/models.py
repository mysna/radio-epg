"""수집기와 Worker ingestion 사이에서 공유하는 정규화 도메인 모델."""

from datetime import UTC, date, datetime
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)


def _require_aware(value: datetime) -> datetime:
    """시간대 정보가 없는 datetime을 모델 경계에서 거부한다."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


AwareDatetime = Annotated[datetime, AfterValidator(_require_aware)]


class _DomainModel(BaseModel):
    """모든 도메인 모델에 엄격하고 불변인 입력 규칙을 적용한다."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Channel(_DomainModel):
    """안정적인 ID를 가진 정규화 라디오 채널."""

    channel_id: str = Field(min_length=1)
    broadcaster_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    stn: str = Field(min_length=1)
    ch: str | None = None
    city: str | None = None
    region_ids: tuple[str, ...] = ()
    radio_ids: tuple[str, ...] = ()


class ProgramCandidate(_DomainModel):
    """한 소스에서 수집한 프로그램 메타데이터 후보."""

    source_id: str = Field(min_length=1)
    program_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str | None = None
    hosts: tuple[str, ...] = ()
    genre: str | None = None
    homepage_url: str | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        """공백만 있는 프로그램 제목을 거부한다."""
        if not value.strip():
            raise ValueError("title must not be blank")
        return value.strip()


class ScheduleCandidate(_DomainModel):
    """방송일과 UTC로 직렬화할 실제 시각을 가진 편성 후보."""

    source_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    fetched_at: AwareDatetime
    confidence: float = Field(ge=0, le=1)
    channel_id: str = Field(min_length=1)
    program_id: str | None = None
    source_event_id: str | None = None
    broadcast_date: date
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    title: str = Field(min_length=1)
    subtitle: str | None = None
    is_live: bool = False
    is_rerun: bool = False

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        """공백만 있는 편성 제목을 거부한다."""
        if not value.strip():
            raise ValueError("title must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def end_must_follow_start(self) -> Self:
        """종료 시각이 시작 시각보다 뒤인지 검증한다."""
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be later than starts_at")
        return self

    @field_serializer("fetched_at", "starts_at", "ends_at", when_used="json")
    def serialize_instant_as_utc(self, value: datetime) -> datetime:
        """편성의 모든 실제 시각을 UTC로 직렬화한다."""
        return value.astimezone(UTC)


class ImageCandidate(_DomainModel):
    """출처와 권리 정보를 보존하는 이미지 후보."""

    entity_type: Literal["broadcaster", "channel", "program"]
    entity_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_page_url: str = Field(min_length=1)
    rights_status: str = "unknown"
    author: str | None = None
    license: str | None = None
    attribution: str | None = None


class SourceMetadata(_DomainModel):
    """어댑터 결과와 함께 전달되는 소스 출처 메타데이터."""

    source_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    priority: int = Field(ge=0)
    fetched_at: AwareDatetime

    @field_serializer("fetched_at", when_used="json")
    def serialize_fetched_at_as_utc(self, value: datetime) -> datetime:
        """소스 조회 시각을 UTC로 직렬화한다."""
        return value.astimezone(UTC)


class AdapterResult(_DomainModel):
    """한 어댑터가 반환하는 검증 전 후보 묶음."""

    source: SourceMetadata
    channels: tuple[Channel, ...] = ()
    programs: tuple[ProgramCandidate, ...] = ()
    schedules: tuple[ScheduleCandidate, ...] = ()
    images: tuple[ImageCandidate, ...] = ()
    errors: tuple[str, ...] = ()


class ImportBatch(_DomainModel):
    """검증된 후보를 멱등하게 Worker로 전송하는 배치."""

    idempotency_key: str = Field(min_length=1)
    source: SourceMetadata
    channels: tuple[Channel, ...] = ()
    programs: tuple[ProgramCandidate, ...] = ()
    schedules: tuple[ScheduleCandidate, ...] = ()
    images: tuple[ImageCandidate, ...] = ()
    collected_at: AwareDatetime

    @field_serializer("collected_at", when_used="json")
    def serialize_collected_at_as_utc(self, value: datetime) -> datetime:
        """수집 완료 시각을 UTC로 직렬화한다."""
        return value.astimezone(UTC)
