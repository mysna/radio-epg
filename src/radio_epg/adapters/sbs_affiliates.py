"""SBS 지역 제휴사 mapping 경계."""

from radio_epg.regional_mapping import (
    ConfiguredRegionalAdapter,
    RegionalChannelMapping,
    RegionalMapping,
    channels_for_family,
)


class SbsAffiliatesAdapter(ConfiguredRegionalAdapter):
    """fixture로 검증되어 enabled 된 SBS 제휴사 mapping만 수집한다."""

    family = "sbs_affiliates"


def owned_channels(mapping: RegionalMapping) -> tuple[RegionalChannelMapping, ...]:
    """SBS 제휴사가 소유하는 identity를 반환한다."""
    return channels_for_family(mapping, "sbs_affiliates")
