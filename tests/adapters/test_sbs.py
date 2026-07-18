import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from radio_epg.adapters.html_schedule import ScheduleRow, load_channel_mapping, normalize_rows
from radio_epg.adapters.sbs import (
    SbsUnavailableDateError,
    parse_sbs_current_schedule,
    parse_sbs_schedule,
)
from radio_epg.config import SourceConfig

FIXTURES = Path(__file__).parents[1] / "fixtures" / "sbs"
MAPPING = Path(__file__).parents[2] / "data" / "mappings" / "sbs.json"
CATALOG = Path(__file__).parents[2] / "data" / "radio_channels.json"


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def test_sbs_maps_power_love_and_dmb_daily_data() -> None:
    rows = parse_sbs_schedule(_load("schedule.json"), expected_date=date(2026, 7, 13))

    assert set(rows) == {"power", "love", "dmb"}
    assert rows["power"][0].title == "조정식의 펀펀투데이"


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
    with pytest.raises(SbsUnavailableDateError):
        parse_sbs_current_schedule(payload, expected_date=date(2026, 7, 14), today=today)


def test_sbs_normalization_scopes_reused_event_ids_by_channel() -> None:
    source = SourceConfig(
        source_id="sbs",
        name="SBS 편성표",
        source_kind="official",
        source_url="https://www.sbs.co.kr/",
        priority=100,
        adapter="sbs",
    )
    shared = ScheduleRow(
        upstream_id="shared-vod:05:00",
        broadcast_date=date(2026, 7, 15),
        start="05:00",
        end="06:00",
        title="공통 프로그램",
    )

    result = normalize_rows(
        source=source,
        mapping=load_channel_mapping(MAPPING),
        catalog_path=CATALOG,
        rows={"power": (shared,), "love": (shared,)},
        fetched_at=datetime(2026, 7, 15, tzinfo=UTC),
    )

    assert {event.source_event_id for event in result.schedules} == {
        "power:2026-07-15:shared-vod:05:00",
        "love:2026-07-15:shared-vod:05:00",
    }


def test_sbs_normalization_scopes_reused_event_ids_by_broadcast_date() -> None:
    source = SourceConfig(
        source_id="sbs",
        name="SBS 편성표",
        source_kind="official",
        source_url="https://www.sbs.co.kr/",
        priority=100,
        adapter="sbs",
    )

    def normalized_id(broadcast_date: date) -> str | None:
        row = ScheduleRow(
            upstream_id="shared-vod:05:00",
            broadcast_date=broadcast_date,
            start="05:00",
            end="06:00",
            title="매일 같은 프로그램",
        )
        result = normalize_rows(
            source=source,
            mapping=load_channel_mapping(MAPPING),
            catalog_path=CATALOG,
            rows={"power": (row,)},
            fetched_at=datetime(2026, 7, 18, tzinfo=UTC),
        )
        return result.schedules[0].source_event_id

    assert {
        normalized_id(date(2026, 7, 17)),
        normalized_id(date(2026, 7, 18)),
    } == {
        "power:2026-07-17:shared-vod:05:00",
        "power:2026-07-18:shared-vod:05:00",
    }
