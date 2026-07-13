"""FEBC 공유 CMS mapping 경계."""

from radio_epg.regional_mapping import (
    ConfiguredRegionalAdapter,
    RegionalChannelMapping,
    RegionalMapping,
    channels_for_family,
)


class FebcAdapter(ConfiguredRegionalAdapter):
    """fixture로 검증되어 enabled 된 FEBC shared CMS만 수집한다."""

    family = "febc"


def owned_channels(mapping: RegionalMapping) -> tuple[RegionalChannelMapping, ...]:
    """FEBC shared CMS가 소유하는 identity를 반환한다."""
    return channels_for_family(mapping, "febc")
