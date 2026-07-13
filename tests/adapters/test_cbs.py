from datetime import date
from pathlib import Path

from radio_epg.adapters.cbs import parse_cbs_schedule
from radio_epg.adapters.html_schedule import load_channel_mapping
from radio_epg.adapters.pdf_schedule import parse_pdf_schedule_text

FIXTURES = Path(__file__).parents[1] / "fixtures" / "cbs"
MAPPING = Path(__file__).parents[2] / "data" / "mappings" / "cbs.json"


def test_cbs_html_maps_standard_music_and_joy4u() -> None:
    rows = parse_cbs_schedule(
        (FIXTURES / "schedule.html").read_text(), expected_date=date(2026, 7, 13)
    )

    assert set(rows) == {"sfm", "mfm", "joy4u"}
    assert rows["joy4u"][0].title == "당신을 향한 노래"


def test_cbs_pdf_text_uses_channel_boundaries_and_strict_time_rows() -> None:
    rows = parse_pdf_schedule_text((FIXTURES / "schedule.txt").read_text())

    assert set(rows) == {"sfm", "mfm"}
    assert rows["sfm"][1].title == "CBS 뉴스"


def test_cbs_mapping_owns_only_the_three_central_channels() -> None:
    mapping = load_channel_mapping(MAPPING)

    assert {item.channel_id for item in mapping.channels} == {
        "cbs.sfm.main",
        "cbs.mfm.main",
        "cbs.joy4u.main",
    }
