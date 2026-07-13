import json
from datetime import date
from pathlib import Path

import pytest

from radio_epg.adapters.html_schedule import load_channel_mapping
from radio_epg.adapters.sbs import (
    SbsUnavailableDateError,
    parse_sbs_current_schedule,
    parse_sbs_schedule,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "sbs"
MAPPING = Path(__file__).parents[2] / "data" / "mappings" / "sbs.json"


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def test_sbs_maps_power_love_and_dmb_daily_data() -> None:
    rows = parse_sbs_schedule(_load("schedule.json"), expected_date=date(2026, 7, 13))

    assert set(rows) == {"power", "love", "dmb"}
    assert rows["power"][0].title == "조정식의 펀펀투데이"
    assert rows["power"][0].image_url == "https://img.sbs.co.kr/program/power.jpg"


def test_sbs_rejects_a_future_request_that_repeats_todays_schedule() -> None:
    with pytest.raises(SbsUnavailableDateError, match="2026-07-20"):
        parse_sbs_schedule(_load("repeated-today.json"), expected_date=date(2026, 7, 20))


def test_sbs_rejects_malformed_and_empty_payloads() -> None:
    with pytest.raises(ValueError):
        parse_sbs_schedule({"channels": []}, expected_date=date(2026, 7, 13))


def test_sbs_mapping_uses_only_the_three_central_codes() -> None:
    mapping = load_channel_mapping(MAPPING)

    assert {item.upstream_code for item in mapping.channels} == {"power", "love", "dmb"}
    assert {item.channel_id for item in mapping.channels} == {
        "sbs.powerfm.main",
        "sbs.lovefm.main",
        "sbs.dmb.main",
    }


def test_sbs_parses_the_official_current_day_shape_only_for_today() -> None:
    payload = _load("current.json")
    today = date(2026, 7, 13)

    rows = parse_sbs_current_schedule(payload, expected_date=today, today=today)

    assert rows["power"][0].upstream_id == "power-vod:5:00"
    assert rows["power"][0].image_url == "https://image.cloud.sbs.co.kr/power.png"
    with pytest.raises(SbsUnavailableDateError):
        parse_sbs_current_schedule(payload, expected_date=date(2026, 7, 14), today=today)
