from pathlib import Path

from radio_epg.adapters.febc import owned_channels
from radio_epg.regional_mapping import load_regional_mapping

MAPPING = Path(__file__).parents[2] / "data" / "mappings" / "regional.json"


def test_febc_shared_cms_accounts_for_all_thirteen_identities() -> None:
    channels = owned_channels(load_regional_mapping(MAPPING))

    assert len(channels) == 13
    assert {item.channel_id for item in channels} >= {
        "febc.main.main",
        "febc.main.jeju",
        "febc.main.ulsan",
    }
