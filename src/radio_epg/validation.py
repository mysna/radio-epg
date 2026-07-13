"""정규화된 편성 후보 사이의 구조적 충돌을 검증한다."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations

from radio_epg.models import ScheduleCandidate


class ScheduleValidationError(ValueError):
    """한 소스가 제공한 편성 구조가 선언된 정책과 다를 때 발생한다."""


@dataclass(frozen=True, slots=True)
class SchedulePolicy:
    """어댑터가 명시적으로 허용하는 편성 관계."""

    allow_nested: bool = False
    allow_adjacent: bool = False


def _is_nested(first: ScheduleCandidate, second: ScheduleCandidate) -> bool:
    """두 편성 중 하나가 다른 하나의 시간 범위 안에 포함되는지 확인한다."""
    first_contains_second = first.starts_at <= second.starts_at and first.ends_at >= second.ends_at
    second_contains_first = second.starts_at <= first.starts_at and second.ends_at >= first.ends_at
    return first_contains_second or second_contains_first


def _validate_pair(
    first: ScheduleCandidate,
    second: ScheduleCandidate,
    policy: SchedulePolicy,
) -> None:
    """동일 소스·채널·방송일의 편성 두 개 사이 관계를 검증한다."""
    if first.ends_at < second.starts_at or second.ends_at < first.starts_at:
        return
    if first.ends_at == second.starts_at or second.ends_at == first.starts_at:
        if not policy.allow_adjacent:
            raise ScheduleValidationError("adjacent events require adapter declaration")
        return
    if _is_nested(first, second):
        if not policy.allow_nested:
            raise ScheduleValidationError("nested events require adapter declaration")
        return
    raise ScheduleValidationError("conflicting overlap from one source")


def validate_schedule(
    events: Sequence[ScheduleCandidate],
    *,
    policy: SchedulePolicy | None = None,
) -> None:
    """같은 소스·채널·방송일 안의 모든 편성 관계를 검증한다."""
    declared_policy = policy or SchedulePolicy()
    groups: dict[tuple[str, str, object], list[ScheduleCandidate]] = defaultdict(list)
    for event in events:
        key = (event.source_id, event.channel_id, event.broadcast_date)
        groups[key].append(event)

    for group in groups.values():
        for first, second in combinations(group, 2):
            _validate_pair(first, second, declared_policy)
