from collections import Counter
from pathlib import Path

from radio_epg.adapters.independent import owned_channels
from radio_epg.coverage import build_coverage
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


def test_task_11_coverage_accounts_for_168_and_leaves_task_12_visible() -> None:
    report = build_coverage(ROOT, require_accounted=True)

    assert report.catalog_count == 194
    assert report.accounted_count == 168
    assert report.pending_count == 26
    assert all(channel_id.startswith(("community.", "afn.")) for channel_id in report.pending_ids)
