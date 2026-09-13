"""MBC 지역국 mapping 경계."""

from radio_epg.regional_mapping import (
    ConfiguredRegionalAdapter,
    RegionalChannelMapping,
    RegionalMapping,
    channels_for_family,
)


class MbcRegionalAdapter(ConfiguredRegionalAdapter):
    """강릉·대구·제주·여수·목포·광주·원주 등 fixture로 검증된 지역 MBC를 수집한다."""

    family = "regional_mbc"


class MbcPohangAdapter(ConfiguredRegionalAdapter):
    """포항MBC 전용 - phmbc.co.kr의 TLS/User-Agent 예외 때문에 별도 source로 뺐다."""

    family = "mbc_pohang"


class MbcWonjuAdapter(ConfiguredRegionalAdapter):
    """원주MBC 전용 - wjmbc.co.kr가 기본 User-Agent를 막아 별도 source로 뺐다."""

    family = "mbc_wonju"


def owned_channels(mapping: RegionalMapping) -> tuple[RegionalChannelMapping, ...]:
    """지역 MBC(포항·원주 포함)가 소유하는 identity를 반환한다."""
    return (
        channels_for_family(mapping, "regional_mbc")
        + channels_for_family(mapping, "mbc_pohang")
        + channels_for_family(mapping, "mbc_wonju")
    )
