from datetime import date
from pathlib import Path

import pytest

from radio_epg.adapters.ocr_schedule import OcrScheduleError, parse_ocr_tsv

FIXTURE = Path(__file__).parents[1] / "fixtures" / "community" / "ocr.tsv"


def test_ocr_emits_only_strict_rows_above_the_confidence_threshold() -> None:
    rows = parse_ocr_tsv(
        FIXTURE.read_text(),
        broadcast_date=date(2026, 7, 13),
        minimum_confidence=85,
    )

    assert [row.title for row in rows] == ["공동체 아침", "심야 음악"]
    assert rows[1].start == "25:00"
    assert all(row.confidence >= 0.85 for row in rows)


@pytest.mark.parametrize("line", ["99:00\t07:00\t제목\t99", "05:00\t07:00\t \t99"])
def test_ocr_rejects_invalid_times_and_blank_titles(line: str) -> None:
    with pytest.raises(OcrScheduleError):
        parse_ocr_tsv(line, broadcast_date=date(2026, 7, 13), minimum_confidence=85)
