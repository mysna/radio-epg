from pathlib import Path

from radio_epg.adapters.sbs_affiliates import owned_channels
from radio_epg.regional_mapping import load_regional_mapping

MAPPING = Path(__file__).parents[2] / "data" / "mappings" / "regional.json"


def test_sbs_affiliates_account_for_all_ten_identities() -> None:
    channels = owned_channels(load_regional_mapping(MAPPING))

    assert len(channels) == 10
    assert {item.channel_id for item in channels if item.channel_id.endswith(".busan")} == {
        "sbs.lovefm.busan",
        "sbs.powerfm.busan",
    }
