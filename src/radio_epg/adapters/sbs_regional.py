"""SBS 네트워크 지역 제휴사 mapping 경계.

TBC(대구)·KNN(부산)·TJB(대전)·ubc(울산)·CJB(청주)·JIBS(제주)는 전부 SBS와 제휴
관계일 뿐 각자 별도 회사·별도 사이트다. "방송사 → 채널" 원칙에 맞춰 제휴사마다
독립된 source(=family)로 둔다.
"""

from radio_epg.regional_mapping import ConfiguredRegionalAdapter


class TbcAdapter(ConfiguredRegionalAdapter):
    """TBC(대구)."""

    family = "tbc"


class KnnAdapter(ConfiguredRegionalAdapter):
    """KNN(부산)."""

    family = "knn"


class TjbAdapter(ConfiguredRegionalAdapter):
    """TJB(대전)."""

    family = "tjb"


class UbcAdapter(ConfiguredRegionalAdapter):
    """ubc(울산)."""

    family = "ubc"


class CjbAdapter(ConfiguredRegionalAdapter):
    """CJB(청주)."""

    family = "cjb"


class JibsAdapter(ConfiguredRegionalAdapter):
    """JIBS(제주)."""

    family = "jibs"
