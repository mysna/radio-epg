"""CBS 지역국 mapping 경계."""

from radio_epg.regional_mapping import (
    ConfiguredRegionalAdapter,
    RegionalChannelMapping,
    RegionalMapping,
    channels_for_family,
)


class CbsRegionalAdapter(ConfiguredRegionalAdapter):
    """fixture로 검증되어 enabled 된 지역 CBS mapping만 수집한다.

    family는 "religious"가 아니라 "cbs_regional"이다 - "religious"는
    bbs/cpbc/wbs(각자 additional.py의 독립 source로 수집됨)도 커버리지 장부에서
    공유하는 라벨이라, 그대로 쓰면 이 adapter가 그 채널들까지 집어 실제로 없는
    parser key를 찾다가 깨진다.
    """

    family = "cbs_regional"


def owned_channels(mapping: RegionalMapping) -> tuple[RegionalChannelMapping, ...]:
    """지역 CBS가 소유하는 identity를 반환한다."""
    return channels_for_family(mapping, "cbs_regional")
