"""BBS 지역 방송망 mapping 경계.

BBS는 CODE= 파라미터 하나로 지역을 구분하는 bbs.or.kr(전국, additional.py의 독립
source)과 달리, 대구는 아예 별도 사이트(dgbbs.co.kr)를 쓴다. "방송사 → 채널" 원칙에
맞춰 독립된 family로 둔다.
"""

from radio_epg.regional_mapping import ConfiguredRegionalAdapter


class BbsDaeguAdapter(ConfiguredRegionalAdapter):
    """BBS 대구불교방송."""

    family = "bbs_daegu"
