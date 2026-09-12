"""표 형태 편성표 이미지에서 격자선을 찾아 셀 단위로 OCR하는 범용 도구.

일부 공동체 라디오는 주간편성표를 텍스트가 아니라 디자인된 표 이미지(JPG/PNG)로만
게시한다. OpenCV 같은 무거운 의존성을 추가하지 않고, 순수 Pillow 픽셀 투영만으로
격자선을 찾은 뒤 각 셀을 개별적으로 잘라 tesseract에 넘긴다. 표 전체를 한 번에
OCR하면 여러 열의 텍스트가 읽는 순서가 뒤섞이기 때문에(다열 표의 흔한 실패
양상), 셀 단위로 나눠 읽는 쪽이 훨씬 안정적이다.
"""

import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from radio_epg.adapters.ocr_schedule import require_korean_tesseract

_BOX = tuple[int, int, int, int]


def _cluster(positions: list[int], *, gap: int = 5) -> list[int]:
    """인접한(간격 이하) 좌표들을 하나의 대표값(평균)으로 묶는다."""
    if not positions:
        return []
    groups: list[list[int]] = [[positions[0]]]
    for value in positions[1:]:
        if value - groups[-1][-1] <= gap:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [sum(group) // len(group) for group in groups]


def detect_grid_lines(
    image: Image.Image, *, min_run_ratio: float = 0.6, sample_step: int = 3
) -> tuple[list[int], list[int]]:
    """표의 가로/세로 격자선 위치를 어두운 픽셀 비율로 찾는다.

    반환값은 (수평선 y좌표 목록, 수직선 x좌표 목록)이며, 각각 표를
    (len-1)개의 행/열로 나누는 경계선이다.
    """
    gray = image.convert("L")
    width, height = gray.size
    binary = gray.point(lambda value: 0 if value < 150 else 255, mode="L")
    data = binary.tobytes()

    row_dark = [data[y * width : (y + 1) * width].count(0) for y in range(height)]
    horizontal = _cluster([y for y, dark in enumerate(row_dark) if dark > min_run_ratio * width])

    top = horizontal[0] if horizontal else 0
    bottom = horizontal[-1] if horizontal else height
    sampled_rows = range(top, bottom, sample_step)
    col_dark = [0] * width
    for y in sampled_rows:
        row = data[y * width : (y + 1) * width]
        for x in range(width):
            if row[x] == 0:
                col_dark[x] += 1
    threshold = min_run_ratio * len(sampled_rows)
    vertical = _cluster([x for x, dark in enumerate(col_dark) if dark > threshold])
    return horizontal, vertical


def ocr_cell(image: Image.Image, box: _BOX, *, margin: int = 10, psm: int = 6) -> tuple[str, float]:
    """셀 영역을 잘라 OCR하고 (합쳐진 텍스트, 평균 단어 신뢰도 0-100)을 돌려준다.

    격자선이 셀 경계에 그대로 남아있으면 tesseract가 그 줄을 표 구조로 오인해
    텍스트를 전혀 못 읽는 경우가 있어(빈 결과), 자르기 전에 각 변에서
    `margin` 픽셀만큼 안쪽으로 줄인다. 원본 색상 그대로 넘기면 색이 있는
    배경(예: 노란 강조 행)에서 인식률이 크게 떨어져 흑백으로 이진화해서
    넘긴다.
    """
    require_korean_tesseract()
    left, top, right, bottom = box
    box = (left + margin, top + margin, right - margin, bottom - margin)
    crop = image.crop(box).convert("L").point(lambda value: 0 if value < 150 else 255, mode="L")

    with tempfile.TemporaryDirectory() as tmp_dir:
        image_path = Path(tmp_dir) / "cell.png"
        crop.save(image_path)
        output_base = Path(tmp_dir) / "cell_out"
        subprocess.run(
            ["tesseract", str(image_path), str(output_base), "-l", "kor", "--psm", str(psm), "tsv"],
            check=True,
            capture_output=True,
            timeout=30,
        )
        tsv_text = output_base.with_suffix(".tsv").read_text(encoding="utf-8")

    words: list[str] = []
    confidences: list[float] = []
    for line in tsv_text.splitlines()[1:]:
        fields = line.split("\t")
        if len(fields) != 12:
            continue
        confidence = float(fields[10])
        text = fields[11].strip()
        if confidence < 0 or not text:
            continue
        words.append(text)
        confidences.append(confidence)
    merged_text = " ".join(words)
    average_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return merged_text, average_confidence
