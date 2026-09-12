from datetime import date
from pathlib import Path

import pytest

from radio_epg.adapters.community_ocr import _OCR_MINIMUM_CONFIDENCE, kjfm_gwangju_fm

FIXTURE = Path(__file__).parents[1] / "fixtures" / "community" / "kjfm-schedule.jpg"


def test_kjfm_gwangju_fm_reads_the_requested_weekday_column() -> None:
    image_bytes = FIXTURE.read_bytes()

    monday = kjfm_gwangju_fm(image_bytes, date(2026, 9, 7))["community.kjfm.main"]
    tuesday = kjfm_gwangju_fm(image_bytes, date(2026, 9, 8))["community.kjfm.main"]

    assert monday[0].start == "08:00"
    assert monday[-1].end == "24:00"
    # 표에서 육안으로 확인한 월요일 10시/12시 실제 편성과 비교한다.
    assert "이기환" in monday[2].title
    assert "백승우" in next(row for row in monday if row.start == "12:00").title
    # 화요일은 다른 진행자로 바뀌어 같은 시간대 내용이 요일마다 달라야 한다.
    tuesday_ten = next(row for row in tuesday if row.start == "10:00")
    assert "박진경" in tuesday_ten.title
    assert all(0 <= row.confidence <= 1 for row in monday)


def test_kjfm_gwangju_fm_drops_low_confidence_rows() -> None:
    image_bytes = FIXTURE.read_bytes()

    rows = kjfm_gwangju_fm(image_bytes, date(2026, 9, 7))["community.kjfm.main"]

    assert all(row.confidence * 100 >= _OCR_MINIMUM_CONFIDENCE for row in rows)


def test_kjfm_gwangju_fm_has_no_distinct_weekend_programming() -> None:
    image_bytes = FIXTURE.read_bytes()

    with pytest.raises(ValueError, match="no rows"):
        kjfm_gwangju_fm(image_bytes, date(2026, 9, 12))  # Saturday
