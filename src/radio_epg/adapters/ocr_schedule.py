"""Korean Tesseract 출력의 보수적인 편성 행 경계."""

import hashlib
import shutil
import subprocess
from datetime import date, timedelta

from radio_epg.adapters.html_schedule import ScheduleRow
from radio_epg.broadcast_time import parse_broadcast_interval


class OcrScheduleError(ValueError):
    """OCR 실행 환경 또는 행 검증이 실패할 때 발생한다."""


def require_korean_tesseract() -> str:
    """tesseract 실행 파일과 `kor` language data가 모두 있는지 확인한다."""
    executable = shutil.which("tesseract")
    if executable is None:
        raise OcrScheduleError("tesseract executable is unavailable")
    result = subprocess.run(
        [executable, "--list-langs"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if "kor" not in result.stdout.splitlines():
        raise OcrScheduleError("Korean Tesseract language data is unavailable")
    return executable


def parse_ocr_tsv(
    text: str, *, broadcast_date: date, minimum_confidence: float
) -> tuple[ScheduleRow, ...]:
    """`start<TAB>end<TAB>title<TAB>confidence` 행을 엄격히 검증한다."""
    if not 0 <= minimum_confidence <= 100:
        raise OcrScheduleError("OCR confidence threshold must be between 0 and 100")
    rows: list[ScheduleRow] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        fields = raw_line.split("\t")
        if len(fields) != 4:
            raise OcrScheduleError(f"OCR row {line_number} must have four columns")
        start, end, raw_title, confidence_text = fields
        title = raw_title.strip()
        if not title:
            raise OcrScheduleError(f"OCR row {line_number} title is blank")
        try:
            confidence = float(confidence_text)
        except ValueError as error:
            raise OcrScheduleError(f"OCR row {line_number} confidence is invalid") from error
        if not 0 <= confidence <= 100:
            raise OcrScheduleError(f"OCR row {line_number} confidence is invalid")
        if confidence < minimum_confidence:
            continue
        digest = hashlib.sha256(f"{broadcast_date}:{start}:{end}:{title}".encode()).hexdigest()[:16]
        try:
            row = ScheduleRow(
                upstream_id=f"ocr:{digest}",
                broadcast_date=broadcast_date,
                start=start,
                end=end,
                title=title,
                confidence=confidence / 100,
            )
            starts_at, ends_at = parse_broadcast_interval(broadcast_date, start, end)
            if ends_at - starts_at > timedelta(hours=12):
                raise ValueError("OCR schedule duration exceeds 12 hours")
            rows.append(row)
        except ValueError as error:
            raise OcrScheduleError(f"OCR row {line_number} time is invalid") from error
    return tuple(rows)
