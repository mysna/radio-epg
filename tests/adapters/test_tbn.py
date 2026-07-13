import json
from datetime import date
from pathlib import Path

import pytest

from radio_epg.adapters.html_schedule import load_channel_mapping
from radio_epg.adapters.tbn import TbnSchemaError, parse_tbn_html, parse_tbn_schedule

FIXTURES = Path(__file__).parents[1] / "fixtures" / "tbn"
MAPPING = Path(__file__).parents[2] / "data" / "mappings" / "tbn.json"


def test_tbn_maps_official_regional_station_codes() -> None:
    payload = json.loads((FIXTURES / "schedule.json").read_text())
    rows = parse_tbn_schedule(payload, expected_date=date(2026, 7, 13))

    assert set(rows) == {"main", "busan", "jeju"}
    assert rows["busan"][0].title == "부산매거진"


def test_tbn_rejects_unknown_regions_and_empty_data() -> None:
    with pytest.raises(TbnSchemaError, match="station"):
        parse_tbn_schedule(
            {"date": "2026-07-13", "stations": {"unknown": []}},
            expected_date=date(2026, 7, 13),
        )


def test_tbn_mapping_accounts_for_all_regions_and_maps_gyeongin_to_page_six() -> None:
    mapping = load_channel_mapping(MAPPING)
    by_id = {item.channel_id: item.url for item in mapping.channels}

    assert len(by_id) == 13
    assert "page_code=6" in by_id["tbn.main.main"]
    assert all("page_code=1&" not in url for url in by_id.values())


def test_tbn_html_parser_preserves_the_requested_region() -> None:
    rows = parse_tbn_html(
        (FIXTURES / "schedule.html").read_text(),
        expected_date=date(2026, 7, 13),
        station_code="main",
    )

    assert rows[0].upstream_id == "main-1"
