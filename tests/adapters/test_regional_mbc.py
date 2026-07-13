from datetime import date
from pathlib import Path

from radio_epg.adapters.regional_mbc import owned_channels, parse_regional_mbc
from radio_epg.regional_mapping import load_regional_mapping

ROOT = Path(__file__).parents[2]
MAPPING = ROOT / "data" / "mappings" / "regional.json"


def test_regional_mbc_accounts_for_all_32_catalog_identities() -> None:
    mapping = load_regional_mapping(MAPPING)
    channels = owned_channels(mapping)

    assert len(channels) == 32
    assert all(item.channel_id.startswith("mbc.") for item in channels)
    assert all(item.status in {"enabled", "unsupported"} for item in channels)


def test_regional_mbc_uses_the_shared_html_parser() -> None:
    rows = parse_regional_mbc(
        (ROOT / "tests" / "fixtures" / "regional" / "shared.html").read_text(),
        expected_date=date(2026, 7, 13),
    )

    assert rows["mbc.sfm.busan"][0].title == "지역의 아침"
