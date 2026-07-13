"""AFN Eagle 공통 편성과 근거가 있는 local insert 병합."""

from collections.abc import Mapping, Sequence

from radio_epg.adapters.community import CommunityAdapter, SourcedScheduleRow, merge_schedule_rows
from radio_epg.adapters.html_schedule import ScheduleRow


class AfnAdapter(CommunityAdapter):
    """local insert 근거가 없는 AFN source를 실패 폐쇄하는 adapter."""

    family = "afn"


def schedules_for_station(
    *,
    common: Sequence[ScheduleRow],
    local_inserts: Mapping[str, Sequence[ScheduleRow]],
    channel_id: str,
    local_evidence: bool,
) -> tuple[ScheduleRow, ...]:
    """local publication 근거가 있을 때만 공통 Eagle 편성을 local insert로 대체한다."""
    if not local_evidence:
        return tuple(common)
    local = tuple(local_inserts.get(channel_id, ()))
    official_local = tuple(SourcedScheduleRow(row, "official") for row in local)
    common_fallback = tuple(SourcedScheduleRow(row, "inferred") for row in common)
    return tuple(item.row for item in merge_schedule_rows(official_local, common_fallback))
