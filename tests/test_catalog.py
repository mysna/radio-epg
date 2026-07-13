from pathlib import Path

from radio_epg.catalog import load_catalog

CATALOG_PATH = Path(__file__).parents[1] / "data" / "radio_channels.json"


def test_catalog_contains_all_current_radio_aliases() -> None:
    catalog = load_catalog(CATALOG_PATH)

    assert len(catalog.radio_aliases) == 226


def test_catalog_folds_duplicate_canonical_channels() -> None:
    catalog = load_catalog(CATALOG_PATH)

    assert len(catalog.channels) == 194


def test_catalog_preserves_known_current_player_id() -> None:
    catalog = load_catalog(CATALOG_PATH)

    assert catalog.radio_aliases["seoul-001-kbs-1radio-main"] == "kbs.1radio.main"


def test_catalog_preserves_each_duplicate_as_an_alias() -> None:
    catalog = load_catalog(CATALOG_PATH)
    ebs_aliases = {
        alias for alias, channel_id in catalog.radio_aliases.items() if channel_id == "ebs.fm.main"
    }

    assert "seoul-014-ebs-fm-main" in ebs_aliases
    assert "jeju-218-ebs-fm-main" in ebs_aliases
