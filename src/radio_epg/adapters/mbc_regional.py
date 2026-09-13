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


class MbcChuncheonAdapter(ConfiguredRegionalAdapter):
    """춘천MBC 전용 - chmbc.co.kr가 기본 User-Agent를 502로 막아 별도 source로 뺐다."""

    family = "mbc_chuncheon"


class MbcBusanAdapter(ConfiguredRegionalAdapter):
    """부산MBC 전용 - busanmbc.co.kr의 TLS 예외와 주간 PDF 파싱 때문에 별도 source로 뺐다."""

    family = "mbc_busan"


class MbcVisionAdapter(ConfiguredRegionalAdapter):
    """편성표가 이미지로만 공개되는 지역 MBC 전용 - Cowork가 커밋한 JSON을 읽는다.

    안동·청주 등 도시가 달라도 "이미지를 읽어 커밋된 JSON을 읽는다"는 수집 방식
    자체는 동일하므로 도시별 서브클래스를 늘리지 않고 하나의 family로 묶는다."""

    family = "mbc_regional_vision"


def owned_channels(mapping: RegionalMapping) -> tuple[RegionalChannelMapping, ...]:
    """지역 MBC(포항·원주·춘천·부산·vision 판독 포함)가 소유하는 identity를 반환한다."""
    return (
        channels_for_family(mapping, "regional_mbc")
        + channels_for_family(mapping, "mbc_pohang")
        + channels_for_family(mapping, "mbc_wonju")
        + channels_for_family(mapping, "mbc_chuncheon")
        + channels_for_family(mapping, "mbc_busan")
        + channels_for_family(mapping, "mbc_regional_vision")
    )
