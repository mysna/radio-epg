"""adapter 실행, 검증, 게시를 source별로 격리하여 조율한다."""

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from radio_epg.adapters.base import CollectionWindow, ScheduleAdapter
from radio_epg.broadcast_time import KST
from radio_epg.models import AdapterResult, ImportBatch
from radio_epg.publisher import PublishError
from radio_epg.validation import SchedulePolicy, validate_schedule


class EmptyScheduleError(ValueError):
    """빈 결과가 기존 편성을 덮지 않도록 게시를 중단한다."""


class ResultValidationError(ValueError):
    """adapter 결과의 source 관계가 일관되지 않을 때 발생한다."""


class BatchPublisher(Protocol):
    """검증된 import batch를 영속 경계로 전달한다."""

    def __call__(self, batch: ImportBatch) -> Awaitable[dict[str, Any]]:
        """한 batch를 게시한다."""
        ...


class _ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScrapeRunSummary(_ReportModel):
    """비밀정보를 포함하지 않는 source별 실행 결과."""

    source_id: str
    status: Literal["succeeded", "failed"]
    started_at: datetime
    finished_at: datetime
    duration_ms: int = Field(ge=0)
    channel_count: int = Field(ge=0)
    program_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    image_count: int = Field(ge=0)
    error: str | None = None


class CollectionReport(_ReportModel):
    """격리 실행한 모든 source 결과."""

    window: CollectionWindow
    runs: tuple[ScrapeRunSummary, ...]


def _validate_result(adapter: ScheduleAdapter, result: AdapterResult) -> None:
    if not result.schedules:
        raise EmptyScheduleError
    if result.source.source_id != adapter.source.source_id:
        raise ResultValidationError("adapter source does not match result source")
    if any(program.source_id != result.source.source_id for program in result.programs):
        raise ResultValidationError("program source does not match result source")
    if any(schedule.source_id != result.source.source_id for schedule in result.schedules):
        raise ResultValidationError("schedule source does not match result source")
    policy = getattr(adapter, "schedule_policy", None)
    if policy is not None and not isinstance(policy, SchedulePolicy):
        raise ResultValidationError("adapter schedule policy is invalid")
    validate_schedule(result.schedules, policy=policy)


def _batch(result: AdapterResult, collected_at: datetime) -> ImportBatch:
    collected_utc = collected_at.astimezone(UTC)
    idempotency_key = f"{result.source.source_id}:{collected_utc.isoformat()}"
    return ImportBatch(
        idempotency_key=idempotency_key,
        source=result.source,
        channels=result.channels,
        programs=result.programs,
        schedules=result.schedules,
        images=result.images,
        collected_at=collected_at,
    )


def _counts(result: AdapterResult | None) -> tuple[int, int, int, int]:
    if result is None:
        return (0, 0, 0, 0)
    return (
        len(result.channels),
        len(result.programs),
        len(result.schedules),
        len(result.images),
    )


def _korean_today() -> date:
    return datetime.now(KST).date()


def _collection_error(error: Exception) -> str:
    if isinstance(error, PublishError):
        return f"PublishError: {error}"
    if isinstance(error, httpx.HTTPStatusError):
        response = error.response
        return f"HTTPStatusError: HTTP {response.status_code} {response.reason_phrase}"
    return type(error).__name__


class Collector:
    """한 source 실패가 다른 source 실행을 중단하지 않게 수집한다."""

    def __init__(
        self,
        adapters: Sequence[ScheduleAdapter],
        *,
        publisher: BatchPublisher,
        start_date: date | None = None,
        today: Callable[[], date] = _korean_today,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._adapters = tuple(adapters)
        self._publisher = publisher
        self._start_date = start_date
        self._today = today
        self._now = now

    async def collect(self) -> CollectionReport:
        """KST 오늘과 내일의 각 adapter를 독립 실행한다."""
        first_day = self._start_date or self._today()
        window = CollectionWindow(first_day, first_day + timedelta(days=1))
        runs: list[ScrapeRunSummary] = []

        for adapter in self._adapters:
            started_at = self._now()
            result: AdapterResult | None = None
            error: str | None = None
            status: Literal["succeeded", "failed"] = "failed"
            try:
                result = await adapter.collect(window)
                _validate_result(adapter, result)
                await self._publisher(_batch(result, started_at))
                status = "succeeded"
            except Exception as caught:  # adapter별 실패 격리 경계
                error = _collection_error(caught)
            finished_at = self._now()
            channel_count, program_count, event_count, image_count = _counts(result)
            duration_ms = max(0, round((finished_at - started_at).total_seconds() * 1000))
            runs.append(
                ScrapeRunSummary(
                    source_id=adapter.source.source_id,
                    status=status,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=duration_ms,
                    channel_count=channel_count,
                    program_count=program_count,
                    event_count=event_count,
                    image_count=image_count,
                    error=error,
                )
            )

        return CollectionReport(window=window, runs=tuple(runs))
