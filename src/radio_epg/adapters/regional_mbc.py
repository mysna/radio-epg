"""지역 MBC shared-CMS 경계."""

from datetime import date

from radio_epg.adapters.html_schedule import ScheduleRow, parse_html_schedule
from radio_epg.regional_mapping import (
    ConfiguredRegionalAdapter,
    RegionalChannelMapping,
    RegionalMapping,
    channels_for_family,
)


class RegionalMbcAdapter(ConfiguredRegionalAdapter):
    """fixture로 검증되어 enabled 된 지역 MBC mapping만 수집한다."""

    family = "regional_mbc"


def owned_channels(mapping: RegionalMapping) -> tuple[RegionalChannelMapping, ...]:
    """지역 MBC가 소유하는 identity를 반환한다."""
    return channels_for_family(mapping, "regional_mbc")


def parse_regional_mbc(text: str, *, expected_date: date) -> dict[str, tuple[ScheduleRow, ...]]:
    """지역 MBC가 공유하는 strict HTML 중간 형식을 파싱한다."""
    rows = parse_html_schedule(text, expected_date=expected_date)
    if not rows or not all(rows.values()):
        raise ValueError("regional MBC schedule is empty")
    return rows
