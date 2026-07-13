from datetime import date
from pathlib import Path

import pytest

from radio_epg.adapters.ebs import EbsSchemaError, parse_ebs_schedule
from radio_epg.adapters.html_schedule import load_channel_mapping

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ebs"
MAPPING = Path(__file__).parents[2] / "data" / "mappings" / "ebs.json"


def test_ebs_fm_supports_extended_hours_subtitles_and_images() -> None:
    rows = parse_ebs_schedule((FIXTURES / "fm.html").read_text(), expected_date=date(2026, 7, 13))

    assert [row.start for row in rows] == ["05:00", "24:20"]
    assert rows[0].subtitle == "영어회화 레벨1"
    assert rows[0].image_url == "https://static.ebs.co.kr/images/english.jpg"


def test_ebs_bandi_is_a_separately_verified_channel() -> None:
    rows = parse_ebs_schedule(
        (FIXTURES / "bandi.html").read_text(), expected_date=date(2026, 7, 13)
    )

    assert rows[0].title == "Morning Special"


def test_ebs_rejects_empty_html() -> None:
    with pytest.raises(EbsSchemaError, match="empty"):
        parse_ebs_schedule("<html></html>", expected_date=date(2026, 7, 13))


def test_ebs_mapping_keeps_fm_and_bandi_codes_separate() -> None:
    mapping = load_channel_mapping(MAPPING)
    by_id = {item.channel_id: item.url for item in mapping.channels}

    assert "channelCd=RADIO" in by_id["ebs.fm.main"]
    assert "channelCd=IRADIO" in by_id["ebs.bandi.main"]
