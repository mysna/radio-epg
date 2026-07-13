"""모든 편성 adapter가 따르는 명시적 수집 계약."""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from radio_epg.config import SourceConfig
from radio_epg.models import AdapterResult


@dataclass(frozen=True, slots=True)
class CollectionWindow:
    """양 끝 날짜를 포함하는 수집 대상 방송일 범위."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("collection window end must not precede start")


class ScheduleAdapter(Protocol):
    """소스 메타데이터와 비동기 수집 함수를 제공하는 adapter."""

    source: SourceConfig

    async def collect(self, window: CollectionWindow) -> AdapterResult:
        """지정한 방송일 범위의 정규화 후보를 반환한다."""
        ...
