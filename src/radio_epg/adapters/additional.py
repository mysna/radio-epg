"""사용자가 확인한 공식 편성표 11종의 엄격한 parser."""

import asyncio
import io
import json
import re
import ssl
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pdfplumber
import pdfplumber.page
import pdfplumber.table
from bs4 import BeautifulSoup, Tag

from radio_epg.adapters.base import CollectionWindow
from radio_epg.adapters.html_schedule import (
    ChannelMapping,
    ChannelMappingFile,
    ScheduleRow,
    normalize_rows,
)
from radio_epg.config import SourceConfig
from radio_epg.models import AdapterResult
from radio_epg.validation import SchedulePolicy

_TIME = re.compile(r"(\d{1,2}:\d{2})")
_TRANSIENT_STATUSES = {408, 429, 500, 502, 503, 504}
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def _rows(
    channel: str,
    day: date,
    items: Iterable[tuple[str, str, str | None]],
    *,
    confidence: float = 1.0,
) -> tuple[ScheduleRow, ...]:
    values = list(items)
    result: list[ScheduleRow] = []
    for index, (start, title, explicit_end) in enumerate(values):
        end = values[index + 1][0] if index + 1 < len(values) else explicit_end or "30:00"
        result.append(
            ScheduleRow(
                upstream_id=f"{channel}:{day.isoformat()}:{start}:{index}",
                broadcast_date=day,
                start=start,
                end=end,
                title=title.strip(),
                is_rerun="(재)" in title,
                confidence=confidence,
            )
        )
    if not result:
        raise ValueError("official schedule contains no rows")
    return tuple(result)


def _require_date(text: str, day: date) -> None:
    candidates = {
        day.isoformat(),
        day.strftime("%Y%m%d"),
        day.strftime("%Y.%m.%d"),
        day.strftime("%Y년 %m월 %d일"),
    }
    if not any(candidate in text for candidate in candidates):
        raise ValueError("official schedule date does not match requested date")


def _table(
    text: str, day: date, channel: str, selector: str = "tr"
) -> dict[str, tuple[ScheduleRow, ...]]:
    _require_date(text, day)
    soup = BeautifulSoup(text, "html.parser")
    items: list[tuple[str, str, str | None]] = []
    for row in soup.select(selector):
        cells = row.find_all(["td", "th"], recursive=False)
        if len(cells) < 2:
            continue
        match = _TIME.search(cells[0].get_text(" ", strip=True))
        title_node = (
            row.select_one(".ft_01")
            if channel in {"obs.main.main", "ifm.main.main"}
            else row.select_one(".tit")
        )
        title = (title_node or cells[1]).get_text(" ", strip=True)
        if match and title:
            items.append((match.group(1), title, None))
    return {channel: _rows(channel, day, items)}


# WBS 지역국은 본사와 같은 schedule_radio.php를 쓰되 "r" 파라미터만 지역명으로
# 바꿔서 요청한다(사이트의 지역 탭 링크 onclick에 그대로 노출되어 있음).
_WBS_REGIONAL_STATIONS: dict[str, tuple[str, str]] = {
    "busan": ("wbs.main.busan", "부산"),
    "daegu": ("wbs.main.daegu", "대구"),
    "gwangju": ("wbs.main.gwangju", "광주"),
    "jeonbuk": ("wbs.main.jeonbuk", "전북"),
}


def _wbs_regional(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    return _table(text, day, channel)


# 일부 방송사는 날짜를 바꿔 요청해도 요일별로 고정된 주간 편성 템플릿만 돌려주고,
# 그날그날의 실제 특보·결방 여부는 반영하지 않는다. 그래도 방송사가 직접 공개한 정규
# 편성이므로 낮은 confidence로 신뢰도를 낮춰서 싣는다.
_STATIC_TEMPLATE_CONFIDENCE = 0.7


def mbc_regional_weekly(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    soup = BeautifulSoup(text, "html.parser")
    items: list[tuple[str, str, str | None]] = []
    for row in soup.select("tr"):
        cells = row.find_all(["td", "th"], recursive=False)
        if len(cells) < 2:
            continue
        match = _TIME.search(cells[0].get_text(" ", strip=True))
        title = cells[1].get_text(" ", strip=True)
        if match and title:
            items.append((match.group(1), title, None))
    return {channel: _rows(channel, day, items, confidence=_STATIC_TEMPLATE_CONFIDENCE)}


# 원주MBC는 요일별 컬럼(월~일 7개)이 있는 정적 주간표를 서버 렌더링한다. 시간대별로
# 며칠씩 묶어 colspan으로 합치는데 묶는 경계가 행마다 다르다(예: 월~금을 3+2로 쪼개고
# 토·일을 따로 두는 행도 있다). 그래서 "몇 번째 칸이냐"가 아니라 각 칸의 colspan을
# 누적해 실제 요일 컬럼 번호(월=1~일=7)와 겹치는 칸을 찾는다. 표 자체가 (예) 05:00부터
# 다음날 05:00까지 하루 전체를 담고 있어서 맨 처음 시각이 다시 나오면 그 시점에서
# 멈춘다(안 그러면 같은 하루가 두 번 들어간다).
def wonju_mbc(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    soup = BeautifulSoup(text, "html.parser")
    target_column = day.weekday() + 1
    entries: list[tuple[str, str]] = []
    first_time: str | None = None
    for row in soup.select("table.twc-w-full tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 2:
            continue
        match = _TIME.search(cells[0].get_text(strip=True))
        if not match:
            continue
        if first_time is None:
            first_time = match.group(1)
        elif match.group(1) == first_time:
            break
        title = None
        column = 1
        for cell in cells[1:]:
            colspan = cell.get("colspan", "1")
            span = int(colspan) if isinstance(colspan, str) else 1
            if column <= target_column < column + span:
                title = cell.get_text(" ", strip=True)
                break
            column += span
        if title:
            entries.append((match.group(1), title))
    items = _normalize_wrapping_times(entries)
    if items and first_time is not None:
        hour, minute = first_time.split(":")
        wrap_end = f"{int(hour) + 24:02d}:{minute}"
        start, title, _ = items[-1]
        items[-1] = (start, title, wrap_end)
    return {channel: _rows(channel, day, items, confidence=_STATIC_TEMPLATE_CONFIDENCE)}


# 대구·제주·여수·목포·광주·대전 MBC는 별도 CMS 업체가 공통으로 만들어준 것으로
# 보이는 같은 템플릿(.broadcast-list li > strong+p)을 쓴다. URL 경로 접두사는
# 방송사마다 다르지만(/FMTimetable/, /StandardFM/ 등) 날짜별 실제 편성(주간
# 템플릿이 아니다)을 서버 렌더링해서 주는 응답 구조 자체는 동일하다.
def mbc_shared_cms(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    _require_date(text, day)
    soup = BeautifulSoup(text, "html.parser")
    entries: list[tuple[str, str]] = []
    for node in soup.select(".broadcast-list li"):
        time_node, title_node = node.select_one("strong"), node.select_one("p")
        if time_node and title_node:
            entries.append((time_node.get_text(strip=True), title_node.get_text(" ", strip=True)))
    return {channel: _rows(channel, day, _normalize_wrapping_times(entries))}


# 춘천MBC는 위 공용 CMS와 다른 자체 템플릿(.guide2_schedule_wrap .row)을 쓰고,
# 시각도 "05시 00분" 형식이다. 날짜는 URL 경로(.../date/YYYY-MM-DD)로 지정하고
# 그 날짜의 편성만 돌려주므로 요일 선택이나 날짜 검증이 따로 필요 없다.
_CHUNCHEON_TIME = re.compile(r"(\d{1,2})시\s*(\d{1,2})분")


def chuncheon_mbc(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    soup = BeautifulSoup(text, "html.parser")
    entries: list[tuple[str, str]] = []
    for row in soup.select(".guide2_schedule_wrap .row"):
        time_node = row.select_one(".left_section i:not(.far)")
        title_node = row.select_one(".title-wrap")
        if time_node is None or title_node is None:
            continue
        match = _CHUNCHEON_TIME.search(time_node.get_text(strip=True))
        title = title_node.get_text(" ", strip=True)
        if match and title:
            entries.append((f"{int(match.group(1)):02d}:{match.group(2)}", title))
    return {channel: _rows(channel, day, _normalize_wrapping_times(entries))}


# 포항MBC는 표준FM/FM4U가 서로 다른 경로(scheduler_fm/scheduler_fm4u)로 완전히
# 분리돼 있고, 날짜 파라미터가 실제로 다른 편성을 주지만 아직 게시되지 않은 날짜를
# 요청하면 조용히 직전 게시일로 대체한다. 날짜 네비게이션의 "on" 항목이 실제로
# 표시된 날짜를 알려주므로 그걸로 요청한 날짜와 일치하는지 확인한다.
def phmbc(text: str, day: date, channel: str, path: str) -> dict[str, tuple[ScheduleRow, ...]]:
    marker = f'<li class="on"><a href="/www/support/scheduler/{path}?date={day.isoformat()}">'
    if marker not in text:
        raise ValueError("official schedule contains no rows")
    soup = BeautifulSoup(text, "html.parser")
    entries: list[tuple[str, str]] = []
    for row in soup.select("table tr"):
        time_node, title_node = row.select_one("td.time"), row.select_one("td.left")
        if time_node and title_node:
            entries.append((time_node.get_text(strip=True), title_node.get_text(" ", strip=True)))
    return {channel: _rows(channel, day, _normalize_wrapping_times(entries))}


# 부산MBC는 편성표를 HTML이 아니라 주간 PDF로만 공개한다. PDF는 ruling line으로
# 그려진 표라 pdfplumber의 find_tables()로 셀 좌표를 얻어 x좌표로 요일 칸을,
# 시간 칸의 위치로 시간대 블록을 구분한다. 오전/오후 표시는 12시 경계에서만
# 나오므로 _BusanMbcHourTracker가 마지막 상태를 이어받아 24시간제로 바꾼다.
# 원 표는 1부/2부/3부/4부로 세분돼 있지만 이 구분을 재현할 만큼 신뢰도 있는
# 시각 정보가 없어(사용자 확인 후) 한 시간대의 내용을 합쳐 하나의 항목으로 싣는다.
class _BusanMbcHourTracker:
    def __init__(self) -> None:
        self.is_pm = False

    def parse(self, text: str) -> tuple[int, str]:
        parts = text.split("\n")
        if len(parts) >= 2 and parts[0] in ("AM", "PM"):
            self.is_pm = parts[0] == "PM"
            hour = int(parts[1])
            minute = parts[2] if len(parts) == 3 else "00"
        else:
            hour = int(parts[-1])
            minute = "00"
        hour24 = (12 if self.is_pm else 0) if hour == 12 else hour + 12 if self.is_pm else hour
        return hour24, minute


_BUSAN_MBC_SYMBOLS = re.compile(r"[★◆◇※▲◎●⊙n△]\s*\(?[RL]?\)?")
_BUSAN_MBC_STRAY_DIGIT = re.compile(r"(^|\s)\d{1,2}(\s|$)")


def _busan_mbc_clean_title(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ")
    text = re.sub(r"[1-4]\s*부", " ", text)
    text = _BUSAN_MBC_SYMBOLS.sub(" ", text)
    text = re.sub(r"\bC\b", " ", text)
    text = re.sub(r"[@/]", " ", text)
    text = _BUSAN_MBC_STRAY_DIGIT.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip(" .,-")


def _busan_mbc_overlaps(cell: tuple[float, float, float, float], band: tuple[float, float]) -> bool:
    # 인접 요일 칸과 경계가 거의 붙어 있어(실측 0.02pt 단위 오차) 여유를 두지
    # 않으면 옆 칸 내용이 새어 들어온다.
    x0, x1 = cell[0], cell[2]
    b0, b1 = band
    return x0 < b1 - 0.5 and x1 > b0 + 0.5


def _busan_mbc_cell_text(
    page: "pdfplumber.page.Page", cell: tuple[float, float, float, float]
) -> str:
    return _busan_mbc_clean_title(page.within_bbox(cell).extract_text() or "")


def _busan_mbc_bands(
    page: "pdfplumber.page.Page", header_row: "pdfplumber.table.CellGroup", labels: tuple[str, ...]
) -> dict[str, tuple[float, float]]:
    bands: dict[str, tuple[float, float]] = {}
    for cell in header_row.cells:
        if cell is None:
            continue
        text = (page.within_bbox(cell).extract_text() or "").strip()
        if text in labels:
            bands[text] = (cell[0], cell[2])
    return bands


# 표준FM: 요일 칸이 "월 - 금"/"토"/"일" 3개뿐이고, 시간 칸(85<=x0<99)과 분 칸
# (99<=x0<111)이 나뉘어 있어 한 시간대에 최대 두 개(정시/반시)의 분 표시가 온다.
def busan_mbc_sfm(pdf_bytes: bytes, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    band_key = "토" if day.weekday() == 5 else "일" if day.weekday() == 6 else "월 - 금"
    entries: list[tuple[str, str]] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        table = page.find_tables()[0]
        band = _busan_mbc_bands(page, table.rows[0], ("월 - 금", "토", "일"))[band_key]
        tracker = _BusanMbcHourTracker()
        current_hour: int | None = None
        block_rows: list[list] = []

        def flush(rows_in_block: list[list], hour: int | None) -> None:
            if not rows_in_block or hour is None:
                return
            minute_labels: list[str] = []
            for cell in rows_in_block[0]:
                if cell is not None and 99 <= cell[0] < 111:
                    text = page.within_bbox(cell).extract_text() or ""
                    minute_labels = [
                        part.strip() for part in text.split("\n") if part.strip().isdigit()
                    ]
                    break
            if not minute_labels:
                minute_labels = ["00"]
            row_texts: list[str] = []
            for row_cells in rows_in_block:
                texts = [
                    cleaned
                    for cell in row_cells
                    if cell is not None
                    and _busan_mbc_overlaps(cell, band)
                    and (cleaned := _busan_mbc_cell_text(page, cell))
                ]
                joined = " ".join(texts).strip()
                if joined:
                    row_texts.append(joined)
            if len(minute_labels) >= 2 and row_texts:
                first_minute, second_minute = minute_labels[0], minute_labels[1]
                first, rest = row_texts[0], " / ".join(row_texts[1:]) or row_texts[0]
                entries.append((f"{hour:02d}:{first_minute}", first))
                if rest != first:
                    entries.append((f"{hour:02d}:{second_minute}", rest))
            elif row_texts:
                entries.append((f"{hour:02d}:{minute_labels[0]}", " / ".join(row_texts)))

        for row in table.rows[1:]:
            hour_cell = next(
                (cell for cell in row.cells if cell is not None and 85 <= cell[0] < 99), None
            )
            if hour_cell is not None:
                flush(block_rows, current_hour)
                hour_text = page.within_bbox(hour_cell).extract_text() or ""
                current_hour, _ = tracker.parse(hour_text)
                block_rows = [row.cells]
            else:
                block_rows.append(row.cells)
        flush(block_rows, current_hour)

    if not entries:
        raise ValueError("official schedule contains no rows")
    return {channel: _rows(channel, day, _normalize_wrapping_times(entries))}


# FM4U: 요일 칸이 "월 - 수"/"목 - 금"/"토"/"일" 4개로 더 세분돼 있고, 시간 칸
# (100<=x0<119.3) 하나에 시+분이 함께 오며 첫 칸(AM 5시) 말고는 분 표시가 아예
# 없다 - 그래서 한 시간대의 내용을 정시(:00) 하나로 합쳐서 싣는다.
def busan_mbc_fm4u(pdf_bytes: bytes, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    weekday = day.weekday()
    if weekday in (0, 1, 2):
        band_key = "월 - 수"
    elif weekday in (3, 4):
        band_key = "목 - 금"
    else:
        band_key = "토" if weekday == 5 else "일"
    entries: list[tuple[str, str]] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        table = page.find_tables()[0]
        band = _busan_mbc_bands(page, table.rows[0], ("월 - 수", "목 - 금", "토", "일"))[band_key]
        tracker = _BusanMbcHourTracker()
        current_hour: int | None = None
        current_minute = "00"
        block_rows: list[list] = []

        def flush(rows_in_block: list[list], hour: int | None, minute: str) -> None:
            if not rows_in_block or hour is None:
                return
            row_texts: list[str] = []
            for row_cells in rows_in_block:
                texts = [
                    cleaned
                    for cell in row_cells
                    if cell is not None
                    and cell[0] >= 130
                    and _busan_mbc_overlaps(cell, band)
                    and (cleaned := _busan_mbc_cell_text(page, cell))
                ]
                if texts:
                    row_texts.append(" ".join(texts).strip())
            merged = " / ".join(dict.fromkeys(row_texts))
            if merged:
                entries.append((f"{hour:02d}:{minute}", merged))

        for row in table.rows[1:]:
            hour_cell = next(
                (cell for cell in row.cells if cell is not None and 100 <= cell[0] < 119.3), None
            )
            if hour_cell is not None:
                flush(block_rows, current_hour, current_minute)
                hour_text = page.within_bbox(hour_cell).extract_text() or ""
                current_hour, current_minute = tracker.parse(hour_text)
                block_rows = [row.cells]
            else:
                block_rows.append(row.cells)
        flush(block_rows, current_hour, current_minute)

    if not entries:
        raise ValueError("official schedule contains no rows")
    return {channel: _rows(channel, day, _normalize_wrapping_times(entries))}


# 편성표가 이미지로만 공개돼 결정적으로 파싱할 수 없는 채널(예: 안동MBC)은 Cowork가
# 주기적으로 이미지를 읽어 이 스키마의 JSON을 커밋해 넣는다:
#   {"week_of": "YYYY-MM-DD" (그 주 월요일 날짜),
#    "days": {"monday": [{"start": "HH:MM", "title": "..."}, ...], ..., "sunday": [...]}}
# LLM 판독이라 다른 공식 소스보다 신뢰도를 낮게 매긴다. week_of가 요청한 날짜가
# 속한 주의 월요일과 다르면(아직 그 주 편성이 올라오지 않음) 조용히 건너뛴다.
_VISION_CONFIDENCE = 0.5
_WEEKDAY_KEYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def vision_json(payload: Any, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    if not isinstance(payload, dict):
        raise ValueError("no rows")
    week_of_text = payload.get("week_of")
    if not isinstance(week_of_text, str):
        raise ValueError("no rows")
    try:
        week_of = date.fromisoformat(week_of_text)
    except ValueError:
        raise ValueError("no rows") from None
    if week_of != day - timedelta(days=day.weekday()):
        raise ValueError("no rows")
    days = payload.get("days")
    if not isinstance(days, dict):
        raise ValueError("no rows")
    entries = days.get(_WEEKDAY_KEYS[day.weekday()])
    if not isinstance(entries, list) or not entries:
        raise ValueError("no rows")
    try:
        items = [(str(entry["start"]), str(entry["title"])) for entry in entries]
    except (KeyError, TypeError):
        raise ValueError("no rows") from None
    normalized = _normalize_wrapping_times(items)
    return {channel: _rows(channel, day, normalized, confidence=_VISION_CONFIDENCE)}


def _ytn(text: str, day: date) -> dict[str, tuple[ScheduleRow, ...]]:
    _require_date(text, day)
    soup = BeautifulSoup(text, "html.parser")
    items = []
    for node in soup.select("#schedule2 .time_content"):
        time_node = node.select_one(".time")
        if time_node is None:
            continue
        match = _TIME.search(time_node.get_text(" ", strip=True))
        title_node = node.select_one(".program") or time_node.find_next_sibling()
        if match and isinstance(title_node, Tag):
            items.append((match.group(1), title_node.get_text(" ", strip=True), None))
    channel = "ytn.main.main"
    return {channel: _rows(channel, day, items)}


# FEBC 지역국은 서울과 동일한 CMS를 지역별 subdomain으로 그대로 미러링한다.
# 방송사 하나(FEBC)가 소유한 채널 13개이므로 tbs처럼 소스 하나 아래에서 함께 수집한다.
_FEBC_REGIONS: dict[str, tuple[str, str]] = {
    "seoul": ("febc.main.main", "https://seoul.febc.net/radio/schedule"),
    "busan": ("febc.main.busan", "https://busan.febc.net/radio/schedule"),
    "changwon": ("febc.main.changwon", "https://changwon.febc.net/radio/schedule"),
    "daegu": ("febc.main.daegu", "https://daegu.febc.net/radio/schedule"),
    "daejeon": ("febc.main.daejeon", "https://daejeon.febc.net/radio/schedule"),
    "gangwon": ("febc.main.gangwon", "https://gangwon.febc.net/radio/schedule"),
    "gwangju": ("febc.main.gwangju", "https://gj.febc.net/radio/schedule"),
    "jeju": ("febc.main.jeju", "https://jeju.febc.net/radio/schedule"),
    "jeonbuk": ("febc.main.jeonbuk", "https://jb.febc.net/radio/schedule"),
    "jeonnam": ("febc.main.jeonnam", "https://jndb.febc.net/radio/schedule"),
    "mokpo": ("febc.main.mokpo", "https://mokpo.febc.net/radio/schedule"),
    "pohang": ("febc.main.pohang", "https://pohang.febc.net/radio/schedule"),
    "ulsan": ("febc.main.ulsan", "https://ulsan.febc.net/radio/schedule"),
}


def _febc(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    _require_date(text, day)
    soup = BeautifulSoup(text, "html.parser")
    items = []
    for node in soup.select(".radio-broadcasting-accordions-wrap .accordion-item"):
        time_node, title_node = node.select_one(".area-txt .time"), node.select_one(".tit")
        if time_node and title_node:
            items.append(
                (time_node.get_text(strip=True), title_node.get_text(" ", strip=True), None)
            )
    return {channel: _rows(channel, day, items)}


# 실제 편성표는 CODE(방송국)·SchGubun(TV/RADIO)·SchDate로 요청하는 AJAX 조각
# (template/ajaxSchedule.html)으로 내려오고, 그 조각 자체에는 날짜 문자열이 없어
# _require_date로 되짚어 검증할 수 없다. 날짜를 바꿔 요청하면 실제로 다른 편성이
# 오는 것은 직접 확인했다.
def _bbs(text: str, day: date) -> dict[str, tuple[ScheduleRow, ...]]:
    soup = BeautifulSoup(text, "html.parser")
    entries: list[tuple[str, str]] = []
    for node in soup.select(".program"):
        time_node, title_node = node.select_one(".date-box p"), node.select_one(".date-box strong")
        if time_node and title_node:
            entries.append((time_node.get_text(strip=True), title_node.get_text(" ", strip=True)))
    channel = "bbs.main.main"
    return {channel: _rows(channel, day, _normalize_wrapping_times(entries))}


def _cpbc(text: str, day: date) -> dict[str, tuple[ScheduleRow, ...]]:
    payload = json.loads(text)
    items = []
    for raw in payload:
        if not str(raw.get("START_DATE", "")).startswith(day.isoformat()):
            raise ValueError("official schedule date does not match requested date")
        items.append((raw["START_TIME"], raw["TITLE"], raw["END_TIME"]))
    channel = "cpbc.main.main"
    return {channel: _rows(channel, day, items)}


# CPBC 지역국은 본사와 다른 최신 API(schedule/{내부채널번호}/{date})를 쓴다. 번호별로
# 응답에 섞여 나오는 "오늘의 강론(지역명)" 프로그램으로 어느 도시인지 직접 확인했다.
_CPBC_REGIONAL_STATIONS: dict[str, tuple[str, str]] = {
    # station: (channel_id, cpbc 내부 channel 번호)
    "busan": ("cpbc.main.busan", "05"),
    "daegu": ("cpbc.main.daegu", "03"),
    "gwangju": ("cpbc.main.gwangju", "04"),
}


def _cpbc_regional(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    payload = json.loads(text)
    items: list[tuple[str, str, str | None]] = []
    for raw in payload.get("data", []):
        if raw.get("broadcastDate") != day.strftime("%Y%m%d"):
            raise ValueError("official schedule date does not match requested date")
        title = raw.get("program", {}).get("title", "")
        items.append((raw["startTime"], title, raw["endTime"]))
    return {channel: _rows(channel, day, items)}


def _kfn(text: str, day: date) -> dict[str, tuple[ScheduleRow, ...]]:
    payload = json.loads(text)
    items = []
    for raw in payload.get("map", {}).get("resultList", []):
        if raw.get("program_date") != day.strftime("%Y%m%d"):
            raise ValueError("official schedule date does not match requested date")
        start, end = raw["program_time"], raw["program_end_time"]
        items.append((f"{start[:2]}:{start[2:]}", raw["program_title"], f"{end[:2]}:{end[2:]}"))
    channel = "kookbang.main.main"
    return {channel: _rows(channel, day, items)}


# 아리랑 라디오는 리액트 SPA라 서버 렌더링된 편성표가 없지만, 브라우저 개발자도구로
# 확인한 내부 API(같은 도메인의 프록시를 거쳐 script.arirang.com을 호출)로 진짜
# JSON 편성을 준다. 같은 요일(화-화, 토-토 등)끼리는 완전히 똑같은 편성이 나와서
# (직접 여러 주 확인) 요일별 고정 템플릿으로 보고 confidence를 낮춘다.
def _arirang(text: str, day: date) -> dict[str, tuple[ScheduleRow, ...]]:
    payload = json.loads(text)
    items: list[tuple[str, str, str | None]] = []
    for raw in payload.get("responseBody", {}).get("dsSchWeek", []):
        if raw.get("broadYmd") != day.strftime("%Y%m%d"):
            raise ValueError("official schedule date does not match requested date")
        start = raw["broadHm"]
        start_minutes = int(start[:2]) * 60 + int(start[2:])
        end_minutes = start_minutes + int(raw["broadRun"])
        start_fmt = f"{start_minutes // 60:02d}:{start_minutes % 60:02d}"
        end_fmt = f"{end_minutes // 60:02d}:{end_minutes % 60:02d}"
        items.append((start_fmt, raw["displayNm"], end_fmt))
    channel = "arirang.main.main"
    return {channel: _rows(channel, day, items, confidence=_STATIC_TEMPLATE_CONFIDENCE)}


def _gugak(text: str, day: date) -> dict[str, tuple[ScheduleRow, ...]]:
    _require_date(text, day)
    soup = BeautifulSoup(text, "html.parser")
    channels = ("kugak.main.main", "kugak.main.gwangju", "kugak.main.daejeon")
    collected: dict[str, list[tuple[str, str, str | None]]] = {channel: [] for channel in channels}
    for row in soup.select("#schedule tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 2:
            continue
        times = _TIME.findall(cells[0].get_text(" ", strip=True))
        if len(times) != 2:
            continue
        for cell in cells[1:]:
            for link in cell.select("a") or [cell]:
                title = link.get_text(" ", strip=True)
                if not title:
                    continue
                channel = (
                    "kugak.main.gwangju"
                    if "[광주]" in title
                    else "kugak.main.daejeon"
                    if "[대전]" in title
                    else "kugak.main.main"
                )
                collected[channel].append((times[0], title, times[1]))
    return {channel: _rows(channel, day, items) for channel, items in collected.items()}


# BeFM(부산영어방송)은 요일별로 별도 div(mon/tue-thu/fri/sat/sun, 화·수·목은
# 하나로 묶임)에 완전한 표를 정적으로 렌더링한다. 날짜별이 아니라 "이번 주" 고정
# 편성이므로 낮은 confidence로 싣는다.
_BEFM_DAY_IDS = {0: "mon", 1: "tue-thu", 2: "tue-thu", 3: "tue-thu", 4: "fri", 5: "sat", 6: "sun"}


def _befm(text: str, day: date) -> dict[str, tuple[ScheduleRow, ...]]:
    soup = BeautifulSoup(text, "html.parser")
    container = soup.select_one(f"#{_BEFM_DAY_IDS[day.weekday()]}")
    items: list[tuple[str, str, str | None]] = []
    if container is not None:
        for row in container.select("tbody tr"):
            cells = row.find_all(["th", "td"], recursive=False)
            if len(cells) < 2:
                continue
            match = _TIME.search(cells[0].get_text(strip=True))
            title = cells[1].get_text(" ", strip=True)
            if match and title:
                items.append((match.group(1), title, None))
    channel = "befm.main.main"
    return {channel: _rows(channel, day, items, confidence=_STATIC_TEMPLATE_CONFIDENCE)}


# CBS 지역국은 자체 도메인을 쓰지만, 편성표 위젯은 전부 CBS 본사의 공유 API
# (appradio.cbs.co.kr)를 station 번호로 구분해서 호출한다(번호는
# data/mappings/regional.json의 채널별 source_url에 있다 - 예: station=6/11은
# 편성표에 지역명이 직접 나오지 않아 그 시간대에만 편성되는 프로그램명을 웹
# 검색으로 교차 확인해서 구분했다. station=11: "반가운 오늘"(강원CBS 93.7MHz,
# 토요일 12:05 편성과 정확히 일치) → 춘천. station=6은 배제법으로 대구).
def _hmm_to_time(value: int) -> str:
    hour, minute = divmod(value, 100)
    return f"{hour:02d}:{minute:02d}"


def cbs_regional(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    payload = json.loads(text)
    if payload.get("date") != int(day.strftime("%Y%m%d")):
        raise ValueError("official schedule date does not match requested date")
    items = [
        (_hmm_to_time(entry["start"]), entry["pname"], _hmm_to_time(entry["end"]))
        for entry in payload["ProgSchedule"]
    ]
    return {channel: _rows(channel, day, items)}


# 강원영동CBS(yd.local.cbs.co.kr)는 appradio 공유 API가 아니라 자체 EUC-KR 정적
# 페이지에 요일별 고정 편성표만 제공한다(날짜 쿼리 파라미터 없음). 표가 rowspan과
# colspan을 함께 써서(시간/월~금/토/일/주일시간 6개 열) 단순 colspan 누적만으로는
# 안 되고, 두 속성을 모두 반영해 실제 격자(grid)로 펼친 뒤 요일에 맞는 열을 읽는다.
_YOUNGDONG_CBS_CHANNEL = "cbs.sfm.youngdong"
_YOUNGDONG_NUM_COLS = 6


def _expand_table_grid(table: Tag) -> list[dict[int, str]]:
    carry: dict[int, tuple[int, str]] = {}
    grid: list[dict[int, str]] = []
    for row_tag in table.select("tbody tr"):
        cells = row_tag.find_all(["td", "th"], recursive=False)
        cell_iter = iter(cells)
        row: dict[int, str] = {}
        col = 0
        while col < _YOUNGDONG_NUM_COLS:
            if col in carry:
                remaining, carried_text = carry[col]
                row[col] = carried_text
                carry[col] = (remaining - 1, carried_text)
                if carry[col][0] <= 0:
                    del carry[col]
                col += 1
                continue
            try:
                cell = next(cell_iter)
            except StopIteration:
                break
            cell_text = cell.get_text(" ", strip=True)
            raw_colspan = cell.get("colspan", "1")
            raw_rowspan = cell.get("rowspan", "1")
            colspan = int(raw_colspan) if isinstance(raw_colspan, str) and raw_colspan else 1
            rowspan = int(raw_rowspan) if isinstance(raw_rowspan, str) and raw_rowspan else 1
            for offset in range(colspan):
                target = col + offset
                if target >= _YOUNGDONG_NUM_COLS:
                    break
                row[target] = cell_text
                if rowspan > 1:
                    carry[target] = (rowspan - 1, cell_text)
            col += colspan
        grid.append(row)
    return grid


def cbs_youngdong(text: str, day: date) -> dict[str, tuple[ScheduleRow, ...]]:
    soup = BeautifulSoup(text, "html.parser")
    table = soup.select_one("table.ti")
    grid = _expand_table_grid(table) if table is not None else []

    weekday = day.weekday()
    if weekday == 6:  # 일요일: 전용 시간(주일시간) + 전용 열
        time_col, title_col = 5, 4
    elif weekday == 5:  # 토요일
        time_col, title_col = 0, 3
    else:  # 월~금
        time_col, title_col = 0, 1

    entries: list[tuple[str, str]] = []
    last_start: str | None = None
    first_time: str | None = None
    for row in grid:
        start_label = row.get(time_col, "")
        if not start_label or start_label == last_start:
            continue
        match = _TIME.search(start_label)
        title = row.get(title_col, "")
        if not match or not title:
            continue
        last_start = start_label
        if first_time is None:
            first_time = match.group(1)
        entries.append((match.group(1), title))

    items = _normalize_wrapping_times(entries)
    if items and first_time is not None:
        hour, minute = first_time.split(":")
        wrap_end = f"{int(hour) + 24:02d}:{minute}"
        start, title, _ = items[-1]
        items[-1] = (start, title, wrap_end)
    return {
        _YOUNGDONG_CBS_CHANNEL: _rows(
            _YOUNGDONG_CBS_CHANNEL, day, items, confidence=_STATIC_TEMPLATE_CONFIDENCE
        )
    }


# SBS 지역 제휴사는 CBS와 달리 회사마다 완전히 다른 사이트를 쓴다. 실제로 접속해서
# 날짜별 편성 페이지 구조를 확인한 곳만 추가한다. TBC(대구)는 sYear/sMonth/sDate
# 쿼리로 날짜별 서버 렌더링 HTML을 제공한다.
def sbs_affiliate_tbc(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    return _table(text, day, channel, selector="table.sch tr")


def _normalize_wrapping_times(
    entries: Iterable[tuple[str, str]],
) -> list[tuple[str, str, str | None]]:
    """자정을 넘기면 다시 00:00부터 시작하는 시각을 단조 증가하도록 정규화한다.

    일부 방송사는 자정을 지나면서 시각을 그냥 00:00으로 되돌리고(예: KNN), 일부는
    "25:00"처럼 24시간을 더한 값과 다시 00:00으로 되돌린 값을 한 응답 안에 섞어서
    보낸다(예: TJB). 두 경우 모두 "정규화한(24시간 나눈 나머지) 값이 직전보다
    줄어드는 순간"을 하루가 넘어간 걸로 보고 그 뒤부터 24시간을 누적해서 더한다.
    같은 시각이 반복되면(생중계가 정규 편성을 대체하는 경우 등) 먼저 온 행만 남긴다.
    """
    result: list[tuple[str, str, str | None]] = []
    previous_canonical: int | None = None
    previous_total: int | None = None
    day_offset = 0
    for time_text, title in entries:
        hour, minute = (int(part) for part in time_text.split(":"))
        canonical = (hour * 60 + minute) % (24 * 60)
        if previous_canonical is not None and canonical < previous_canonical:
            day_offset += 24 * 60
        total = canonical + day_offset
        if total == previous_total:
            continue
        previous_canonical = canonical
        previous_total = total
        hour, minute = divmod(total, 60)
        result.append((f"{hour:02d}:{minute:02d}", title, None))
    return result


# KNN(부산)은 하나의 AJAX 응답(schedule.do?date=...&channel=...) 안에 TV/파워FM/러브FM
# 편성표를 전부 담아 보내고 channel 파라미터는 어느 탭을 펼쳐 보일지에만 쓰인다. 응답
# 본문에 날짜 문자열이 없어 _require_date로 되짚어 검증할 수 없지만, 서로 다른 날짜를
# 요청했을 때 실제로 다른 편성이 오는 것은 직접 확인했다.
def knn_busan(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    container_id = "fm1-schedule" if channel == "sbs.powerfm.busan" else "fm2-schedule"
    soup = BeautifulSoup(text, "html.parser")
    container = soup.find(id=container_id)
    if container is None:
        raise ValueError("official schedule channel section missing")
    entries: list[tuple[str, str]] = []
    for row in container.select("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        match = _TIME.search(cells[0].get_text(" ", strip=True))
        title_cell = cells[1]
        badge = title_cell.select_one(".float-end")
        if badge is not None:
            badge.decompose()
        title = title_cell.get_text(" ", strip=True)
        if match and title:
            entries.append((match.group(1), title))
    return {channel: _rows(channel, day, _normalize_wrapping_times(entries))}


# TJB(대전)는 날짜별 페이지(/sub0502/pairing/radio/date/YYYY-MM-DD)를 서버 렌더링해서
# 준다. 자정 전후 표기가 뒤섞여 있어(23:30 -> 00:00 -> 25:00 -> 02:00) 정규화가 필요하다.
def tjb_daejeon(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    _require_date(text, day)
    soup = BeautifulSoup(text, "html.parser")
    entries: list[tuple[str, str]] = []
    for row in soup.select("table#content_tb tr"):
        time_node = row.select_one(".time")
        title_node = row.select_one(".program")
        if time_node is None or title_node is None:
            continue
        match = _TIME.search(time_node.get_text(strip=True))
        title = title_node.get_text(strip=True)
        if match and title:
            entries.append((match.group(1), title))
    return {channel: _rows(channel, day, _normalize_wrapping_times(entries))}


# ubc(울산)는 /api/broadcast/schedule/?type=RADIO&date=YYYYMMDD로 깔끔한 JSON을
# 준다. 항목마다 start_time/end_time이 명시돼 있어 자정-넘김 정규화가 필요 없다.
def ubc_ulsan(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    payload = json.loads(text)
    if payload.get("date") != day.isoformat():
        raise ValueError("official schedule date does not match requested date")
    items = [(item["start_time"], item["title"], item["end_time"]) for item in payload["items"]]
    return {channel: _rows(channel, day, items)}


# CJB(청주)는 /base/php/onair_ajax.php?mod=radio&moveDate=YYYY-MM-DD로 깔끔한 JSON을
# 준다. sch_start_time/sch_end_time이 자정-넘김도 24를 더한 값("2600" 등)으로 이미
# 정규화돼 있어 추가 정규화가 필요 없다. 서버가 오늘 날짜까지만 값을 채워주고 내일은
# 항상 빈 배열을 돌려준다(사이트 자체가 maxDate를 오늘로 고정).
def cjb_cheongju(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    payload = json.loads(text)
    items: list[tuple[str, str, str | None]] = []
    for raw in payload:
        if raw.get("sch_dt") != day.strftime("%Y%m%d"):
            raise ValueError("official schedule date does not match requested date")
        start, end = raw["sch_start_time"], raw["sch_end_time"]
        items.append((f"{start[:2]}:{start[2:]}", raw["sch_knm"], f"{end[:2]}:{end[2:]}"))
    return {channel: _rows(channel, day, items)}


# JIBS(제주)는 날짜별 URL(timetableMain?search_date=...)이 있지만 실제로는 요청한
# 날짜와 무관하게 항상 같은 편성을 돌려준다(직접 여러 날짜로 확인). 그래서 진짜
# 날짜별 데이터가 아니라 고정 템플릿으로 취급해 confidence를 낮춘다.
def jibs_jeju(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    soup = BeautifulSoup(text, "html.parser")
    tbody = soup.select_one("table#DataTables_Table_0 tbody#TBODY_LIST")
    entries: list[tuple[str, str]] = []
    if tbody is not None:
        for row in tbody.select("tr"):
            cells = row.find_all("td", recursive=False)
            if len(cells) < 2:
                continue
            match = _TIME.search(cells[0].get_text(strip=True))
            title_cell = cells[1]
            for badge in title_cell.select("span.label"):
                badge.decompose()
            title = title_cell.get_text(" ", strip=True)
            if match and title:
                entries.append((match.group(1), title))
    return {
        channel: _rows(
            channel, day, _normalize_wrapping_times(entries), confidence=_STATIC_TEMPLATE_CONFIDENCE
        )
    }


# GGN(글로벌광주방송)는 요일 tab(day=1 월 ~ 7 일)만 있고 날짜별 편성은 아니다.
# 표 구조가 MBC 지역국과 동일(첫 셀 시간, 둘째 셀 제목)해서 같은 파서를 그대로 쓴다.
_GGN_CHANNEL = "ggn.main.main"


def parse_station_schedule(
    station: str, text: str, *, expected_date: date
) -> dict[str, tuple[ScheduleRow, ...]]:
    """방송사별 공식 응답을 canonical channel 행으로 변환한다."""
    if station in {"obs", "ifm", "tbs", "wbs"}:
        return _table(
            text,
            expected_date,
            {
                "obs": "obs.main.main",
                "ifm": "ifm.main.main",
                "tbs": "tbs.fm.main",
                "wbs": "wbs.main.main",
            }[station],
        )
    parsers = {
        "ytn": _ytn,
        "bbs": _bbs,
        "cpbc": _cpbc,
        "kfn": _kfn,
        "gugak": _gugak,
        "befm": _befm,
        "arirang": _arirang,
    }
    try:
        return parsers[station](text, expected_date)
    except KeyError as error:
        raise ValueError(f"unknown additional schedule source: {station}") from error


_CHANNELS = {
    "obs": ("obs.main.main",),
    "ifm": ("ifm.main.main",),
    "ytn": ("ytn.main.main",),
    "tbs": ("tbs.fm.main", "tbs.efm.main"),
    "cpbc": (
        "cpbc.main.main",
        *(channel for channel, _ in _CPBC_REGIONAL_STATIONS.values()),
    ),
    "bbs": ("bbs.main.main",),
    "wbs": (
        "wbs.main.main",
        *(channel for channel, _ in _WBS_REGIONAL_STATIONS.values()),
    ),
    "kfn": ("kookbang.main.main",),
    "gugak": ("kugak.main.main", "kugak.main.gwangju", "kugak.main.daejeon"),
    "befm": ("befm.main.main",),
    "arirang": ("arirang.main.main",),
    "febc": tuple(channel for channel, _ in _FEBC_REGIONS.values()),
    "ggn": (_GGN_CHANNEL,),
}


class AdditionalStationAdapter:
    """fixture로 검증된 추가 공식 방송사를 날짜별로 수집한다."""

    schedule_policy = SchedulePolicy(allow_adjacent=True)

    def __init__(self, source: SourceConfig, *, client: Any | None = None) -> None:
        if source.source_id not in _CHANNELS:
            raise ValueError(f"unsupported additional source: {source.source_id}")
        self.source = source
        self._client = client

    async def collect(self, window: CollectionWindow) -> AdapterResult:
        import httpx

        if self._client is not None:
            return await self._collect_with(self._client, window)
        verify: bool | ssl.SSLContext = True
        if self.source.source_id == "obs":
            verify = ssl.create_default_context()
            verify.set_ciphers("DEFAULT:@SECLEVEL=1")
        async with httpx.AsyncClient(follow_redirects=True, timeout=30, verify=verify) as client:
            return await self._collect_with(client, window)

    async def _request(
        self, client: Any, day: date, *, url: str | None = None, region: str = "서울"
    ) -> str:
        source_id = self.source.source_id
        endpoint = url or self.source.source_url
        if source_id == "obs":
            response = await client.get(
                endpoint,
                params={
                    "type": "radio",
                    "year": day.strftime("%Y"),
                    "month": day.strftime("%m"),
                    "day": day.strftime("%d"),
                },
            )
        elif source_id == "ifm":
            response = await client.get(endpoint, params={"date": day.isoformat()})
        elif source_id == "ytn":
            response = await client.get(endpoint, params={"ymd": day.strftime("%Y%m%d")})
        elif source_id == "tbs":
            response = await client.post(endpoint, data={"onDate": day.strftime("%Y%m%d")})
        elif source_id == "febc":
            response = await client.get(endpoint, params={"searchDate": day.isoformat()})
        elif source_id == "cpbc":
            response = await client.get(
                url or f"https://apis.cpbc.co.kr/radio-api/schedule/{day.strftime('%Y%m%d')}"
            )
        elif source_id == "bbs":
            response = await client.get(
                "https://www.bbs.or.kr/HOME2/template/ajaxSchedule.html",
                params={"CODE": "WWW", "SchGubun": "RADIO", "SchDate": day.isoformat()},
            )
        elif source_id == "wbs":
            for attempt in range(5):
                response = await client.get(
                    endpoint, params={"r": region, "w": (day.weekday() + 1) % 7}
                )
                if response.status_code not in _TRANSIENT_STATUSES or attempt == 4:
                    break
                await asyncio.sleep(0.25 * (2**attempt))
        elif source_id == "kfn":
            # radio.dema.mil.kr은 간헐적으로 연결이 끊기거나 타임아웃난다(약
            # 30초 만에 ConnectTimeout으로 끝나는 패턴이 반복 관찰됨). 짧게
            # 재시도한다.
            import httpx

            for attempt in range(3):
                try:
                    response = await client.post(
                        "https://radio.dema.mil.kr/web/api/v1/media/radio/fmTimeTableListAjax.do",
                        json={"program_date": day.strftime("%Y%m%d")},
                        headers={
                            "Referer": self.source.source_url,
                            "X-Requested-With": "XMLHttpRequest",
                        },
                    )
                    break
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    if attempt == 2:
                        raise
                    await asyncio.sleep(1.0 * (2**attempt))
        elif source_id == "gugak":
            response = await client.get(
                endpoint, params={"sub_num": "786", "today": day.strftime("%Y%m%d")}
            )
        elif source_id == "arirang":
            response = await client.post(
                "https://www.arirang.com/v1.0/open/external/proxy",
                json={
                    "address": "https://script.arirang.com/api/v1/bis/listScheduleV3.do",
                    "method": "POST",
                    "headers": {},
                    "body": {
                        "data": {
                            "dmParam": {
                                "chanId": "CH_R",
                                "broadYmd": day.strftime("%Y%m%d"),
                                "planNo": "1",
                            }
                        }
                    },
                },
            )
        elif source_id == "befm":
            # befm.or.kr는 접속 자체가 간헐적으로 거부되는 일이 잦아(호스팅 쪽 문제로
            # 보임) 연결 실패만 몇 차례 재시도한다.
            import httpx

            for attempt in range(6):
                try:
                    response = await client.get(endpoint)
                    break
                except httpx.ConnectError:
                    if attempt == 5:
                        raise
                    await asyncio.sleep(1.0 * (2**attempt))
        elif source_id == "ggn":
            # ggn.or.kr은 간헐적으로 DNS 조회/연결이 실패한다(약 10초 만에
            # ConnectError로 끝나는 패턴이 반복 관찰됨). 짧게 재시도한다.
            import httpx

            for attempt in range(3):
                try:
                    response = await client.get(endpoint)
                    break
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    if attempt == 2:
                        raise
                    await asyncio.sleep(1.0 * (2**attempt))
        else:
            raise ValueError(f"unsupported additional source: {source_id}")
        response.raise_for_status()
        return response.text

    async def _collect_with(self, client: Any, window: CollectionWindow) -> AdapterResult:
        collected: dict[str, list[ScheduleRow]] = {
            channel: [] for channel in _CHANNELS[self.source.source_id]
        }
        day = window.start
        while day <= window.end:
            # 일부 지역국 CMS(TBS eFM, 광주MBC, 울산 ubc, 대구 TBC 등)는 당일치까지만
            # 채워주거나 특정 날짜(예: 주말 일부)의 편성을 아직 올리지 않아 시간 없는
            # 빈 응답을 돌려준다. 날짜 자체는 정상 응답이므로 "no rows"만 그 채널·날짜에
            # 한해 빈 결과로 건너뛴다.
            if self.source.source_id == "tbs":
                for channel, url in (
                    ("tbs.fm.main", "https://tbs.seoul.kr/fm/schedule.do"),
                    ("tbs.efm.main", "https://tbs.seoul.kr/eFm/schedule.do"),
                ):
                    text = await self._request(client, day, url=url)
                    try:
                        collected[channel].extend(_table(text, day, channel)[channel])
                    except ValueError as error:
                        if "no rows" not in str(error):
                            raise
            elif self.source.source_id == "febc":
                for channel, url in _FEBC_REGIONS.values():
                    text = await self._request(client, day, url=url)
                    collected[channel].extend(_febc(text, day, channel)[channel])
            elif self.source.source_id == "ggn":
                weekday = day.weekday() + 1
                url = f"https://www.ggn.or.kr/sub/content.do?cno=14&menuNo=94&day={weekday}"
                text = await self._request(client, day, url=url)
                collected[_GGN_CHANNEL].extend(
                    mbc_regional_weekly(text, day, _GGN_CHANNEL)[_GGN_CHANNEL]
                )
            elif self.source.source_id == "cpbc":
                text = await self._request(client, day)
                parsed = parse_station_schedule("cpbc", text, expected_date=day)
                for channel, rows in parsed.items():
                    collected[channel].extend(rows)
                for channel, station in _CPBC_REGIONAL_STATIONS.values():
                    url = f"https://apis.cpbc.co.kr/radio-api/schedule/{station}/{day.strftime('%Y%m%d')}"
                    text = await self._request(client, day, url=url)
                    collected[channel].extend(_cpbc_regional(text, day, channel)[channel])
            elif self.source.source_id == "wbs":
                text = await self._request(client, day)
                parsed = parse_station_schedule("wbs", text, expected_date=day)
                for channel, rows in parsed.items():
                    collected[channel].extend(rows)
                for channel, region in _WBS_REGIONAL_STATIONS.values():
                    text = await self._request(client, day, region=region)
                    collected[channel].extend(_wbs_regional(text, day, channel)[channel])
            else:
                parsed = parse_station_schedule(
                    self.source.source_id, await self._request(client, day), expected_date=day
                )
                for channel, rows in parsed.items():
                    collected[channel].extend(rows)
            day += timedelta(days=1)
        mapping = ChannelMappingFile(
            channels=tuple(
                ChannelMapping(
                    channel_id=channel,
                    upstream_code=channel,
                    url=self.source.source_url,
                    parser="additional-official",
                    evidence_date=window.start,
                )
                for channel in _CHANNELS[self.source.source_id]
            )
        )
        return normalize_rows(
            source=self.source,
            mapping=mapping,
            catalog_path=Path(__file__).parents[3] / "data" / "radio_channels.json",
            rows=collected,
            fetched_at=datetime.now(UTC),
        )
