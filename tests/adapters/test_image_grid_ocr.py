from pathlib import Path

from PIL import Image

from radio_epg.adapters.image_grid_ocr import detect_grid_lines, ocr_cell

FIXTURE = Path(__file__).parents[1] / "fixtures" / "community" / "kjfm-schedule.jpg"


def test_detect_grid_lines_finds_the_eight_column_table() -> None:
    image = Image.open(FIXTURE)

    horizontal, vertical = detect_grid_lines(image)

    # 시간 | 월 | 화 | 수 | 목 | 금 | 토 | 일 = 8개 열, 9개의 경계선.
    assert len(vertical) == 9
    assert len(horizontal) >= 20
    assert horizontal == sorted(horizontal)
    assert vertical == sorted(vertical)


def test_ocr_cell_reads_a_known_time_label() -> None:
    image = Image.open(FIXTURE)
    _, vlines = detect_grid_lines(image)
    hlines, _ = detect_grid_lines(image)
    # 월요일 10시 행(육안으로 확인한 좌표 범위)의 시간 열.
    row = next(
        (hlines[i], hlines[i + 1])
        for i in range(len(hlines) - 1)
        if hlines[i + 1] - hlines[i] > 300
    )

    text, confidence = ocr_cell(image, (vlines[0], row[0], vlines[1], row[1]))

    assert "시" in text
    assert confidence > 0
