from collections import Counter
from pathlib import Path

from radio_epg.adapters.religious import owned_channels
from radio_epg.regional_mapping import load_regional_mapping

MAPPING = Path(__file__).parents[2] / "data" / "mappings" / "regional.json"


def test_religious_adapters_account_for_cbs_bbs_cpbc_and_wbs() -> None:
    channels = owned_channels(load_regional_mapping(MAPPING))
    counts = Counter(item.channel_id.split(".", 1)[0] for item in channels)

    assert counts == {"cbs": 16, "bbs": 5, "cpbc": 4, "wbs": 5}
    assert all(item.status in {"enabled", "unsupported"} for item in channels)
