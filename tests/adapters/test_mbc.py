from datetime import date
from pathlib import Path

import pytest

from radio_epg.adapters.html_schedule import JsonpError, parse_jsonp
from radio_epg.adapters.mbc import MbcSchemaError, parse_mbc_schedule
from radio_epg.catalog import load_catalog

FIXTURES = Path(__file__).parents[1] / "fixtures" / "mbc"
MAPPING = Path(__file__).parents[2] / "data" / "mappings" / "mbc.json"
CATALOG = Path(__file__).parents[2] / "data" / "radio_channels.json"


def test_mbc_jsonp_maps_the_three_verified_central_channels() -> None:
    rows = parse_mbc_schedule(
        (FIXTURES / "schedule.jsonp").read_text(), expected_date=date(2026, 7, 13)
    )

    assert set(rows) == {"sfm", "fm4u", "chm"}
    assert rows["sfm"][0].upstream_id == "mbc-s-1"
    assert rows["sfm"][0].is_live is True


@pytest.mark.parametrize(
    "payload",
    [
        "callback({}, {});",
        "callback({}); alert(1)",
        "not a callback",
    ],
)
def test_jsonp_boundary_accepts_exactly_one_json_argument(payload: str) -> None:
    with pytest.raises(JsonpError):
        parse_jsonp(payload)


def test_mbc_rejects_empty_and_mismatched_dates() -> None:
    with pytest.raises(MbcSchemaError, match="empty"):
        parse_mbc_schedule((FIXTURES / "empty.jsonp").read_text(), expected_date=date(2026, 7, 13))
    with pytest.raises(MbcSchemaError, match="date"):
        parse_mbc_schedule(
            (FIXTURES / "schedule.jsonp").read_text(), expected_date=date(2026, 7, 14)
        )


def test_mbc_parses_reduced_official_jsonp_shape() -> None:
    rows = parse_mbc_schedule(
        (FIXTURES / "official-fm.jsonp").read_text(),
        expected_date=date(2026, 7, 13),
        channel_code="sfm",
    )

    assert rows["sfm"][0].start == "05:00"
    assert rows["sfm"][0].homepage_url == "https://miniwebapp.imbc.com/index"


def test_mbc_preserves_the_overnight_broadcast_day_and_scopes_event_ids() -> None:
    rows = parse_mbc_schedule(
        (FIXTURES / "official-fm-overnight.jsonp").read_text(),
        expected_date=date(2026, 7, 13),
        channel_code="sfm",
    )["sfm"]

    assert [(row.start, row.end) for row in rows] == [("23:00", "24:00"), ("24:00", "26:00")]
    assert rows[0].upstream_id == "sfm:2026-07-13:23:00:shared-program"
    assert rows[1].upstream_id == "sfm:2026-07-13:24:00:shared-program"


def test_mbc_rejects_rows_beyond_the_next_day_broadcast_boundary() -> None:
    payload = (
        'scheduleCallback([{"BroadDate":"2026-07-14","BroadcastID":"late",'
        '"Title":"잘못된 낮 편성","StartTime":"0500","EndTime":"0600"}]);'
    )

    with pytest.raises(MbcSchemaError, match="date"):
        parse_mbc_schedule(
            payload,
            expected_date=date(2026, 7, 13),
            channel_code="sfm",
        )


def test_mbc_mapping_owns_three_central_channels_and_accounts_for_bora() -> None:
    import json

    mapping = json.loads(MAPPING.read_text())
    catalog = load_catalog(CATALOG)
    central = {
        channel_id
        for channel_id, channel in catalog.channels.items()
        if channel.stn == "mbc" and channel.city is None
    }

    assert {item["channel_id"] for item in mapping["channels"]} == {
        "mbc.sfm.main",
        "mbc.fm4u.main",
        "mbc.chm.main",
    }
    assert {item["channel_id"] for item in mapping["unsupported"]} == {"mbc.bora.main"}
    assert central == {
        *(item["channel_id"] for item in mapping["channels"]),
        *(item["channel_id"] for item in mapping["unsupported"]),
    }
