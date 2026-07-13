from collections import Counter
from pathlib import Path

from radio_epg.adapters.independent import owned_channels
from radio_epg.regional_mapping import load_regional_mapping

ROOT = Path(__file__).parents[2]
MAPPING = ROOT / "data" / "mappings" / "regional.json"


def test_independent_adapters_account_for_all_twelve_identities() -> None:
    channels = owned_channels(load_regional_mapping(MAPPING))
    counts = Counter(item.channel_id.split(".", 1)[0] for item in channels)

    assert len(channels) == 12
    assert counts["kookbang"] == 1
    assert counts["kugak"] == 3
    assert counts["tbs"] == 2
    assert counts["arirang"] == 1


def test_task_11_mapping_owns_exactly_97_regional_identities() -> None:
    mapping = load_regional_mapping(MAPPING)

    assert len(mapping.channels) == 97
