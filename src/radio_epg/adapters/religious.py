"""CBS 지역국, BBS, CPBC, WBS mapping 경계."""

from radio_epg.regional_mapping import (
    ConfiguredRegionalAdapter,
    RegionalChannelMapping,
    RegionalMapping,
    channels_for_family,
)


class ReligiousAdapter(ConfiguredRegionalAdapter):
    """fixture로 검증되어 enabled 된 종교 방송 mapping만 수집한다."""

    family = "religious"


def owned_channels(mapping: RegionalMapping) -> tuple[RegionalChannelMapping, ...]:
    """종교 방송 family가 소유하는 identity를 반환한다."""
    return channels_for_family(mapping, "religious")
