"""PDF 편성표의 텍스트 추출과 보수적인 행 파싱."""

import io
import re
from collections import defaultdict

from pypdf import PdfReader

from radio_epg.adapters.html_schedule import ScheduleRow

_CHANNEL = re.compile(r"^CHANNEL\s+([a-z0-9_-]+)$", re.IGNORECASE)
_ROW = re.compile(r"^(\d{1,2}:\d{2})-(\d{1,2}:\d{2})\s+(.+\S)$")


def extract_pdf_text(content: bytes) -> str:
    """페이지별 텍스트가 없는 PDF를 오류로 처리하며 합친다."""
    reader = PdfReader(io.BytesIO(content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if not text:
        raise ValueError("PDF schedule contains no extractable text")
    return text


def parse_pdf_schedule_text(text: str) -> dict[str, tuple[ScheduleRow, ...]]:
    """명시적 CHANNEL 경계와 HH:MM-HH:MM 행만 받아들인다.

    반환 행의 방송일은 호출자가 실제 요청일로 교체해야 하므로 임시 날짜를 사용한다.
    """
    from datetime import date

    channel: str | None = None
    parsed: dict[str, list[ScheduleRow]] = defaultdict(list)
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        channel_match = _CHANNEL.fullmatch(line)
        if channel_match:
            channel = channel_match.group(1).lower()
            continue
        row_match = _ROW.fullmatch(line)
        if row_match is None:
            continue
        if channel is None:
            raise ValueError("PDF schedule row appears before a channel boundary")
        start, end, title = row_match.groups()
        parsed[channel].append(
            ScheduleRow(
                upstream_id=f"{channel}:{start}:{title}",
                broadcast_date=date.min,
                start=start.zfill(5),
                end=end.zfill(5),
                title=title,
            )
        )
    if not parsed:
        raise ValueError("PDF schedule contains no valid rows")
    return {code: tuple(rows) for code, rows in parsed.items()}
