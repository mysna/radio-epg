"""국방FM, 국악, TBS 및 독립 방송 mapping 경계."""

from radio_epg.regional_mapping import (
    ConfiguredRegionalAdapter,
    RegionalChannelMapping,
    RegionalMapping,
    channels_for_family,
)


class IndependentAdapter(ConfiguredRegionalAdapter):
    """fixture로 검증되어 enabled 된 독립 방송 mapping만 수집한다."""

    family = "independent"


def owned_channels(mapping: RegionalMapping) -> tuple[RegionalChannelMapping, ...]:
    """독립 방송 family가 소유하는 identity를 반환한다."""
    return channels_for_family(mapping, "independent")
