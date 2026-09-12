"""이미지로만 게시되는 공동체 라디오 주간편성표의 station별 OCR parser."""

import io
import re
from datetime import date
from typing import Any

from PIL import Image

from radio_epg.adapters.html_schedule import ScheduleRow
from radio_epg.adapters.image_grid_ocr import detect_grid_lines, ocr_cell

# OCR 결과는 오탈자가 섞이기 쉬워 fixture로 검증된 다른 소스보다 신뢰도를 낮게 둔다.
_OCR_MINIMUM_CONFIDENCE = 60.0
_TIME_LABEL = re.compile(r"(\d{1,2})\s*시")
# tesseract가 한글 음절을 한 글자씩 별도 단어로 끊어 사이마다 공백을 넣는다.
# 완성형 한글 음절끼리 붙어있는 공백만 제거해 원래 글자 붙임을 복원한다
# (사람 이름처럼 실제로 띄어써야 하는 경우까지 합쳐지는 건 감수한다).
_HANGUL_GAP = re.compile(r"(?<=[가-힣])\s+(?=[가-힣])")


def _clean_ocr_text(text: str) -> str:
    return _HANGUL_GAP.sub("", " ".join(text.split()))


def _rows_from_hourly_entries(
    channel: str, day: date, entries: list[tuple[str, str, float]]
) -> tuple[ScheduleRow, ...]:
    rows: list[ScheduleRow] = []
    for index, (start, title, confidence) in enumerate(entries):
        end = entries[index + 1][0] if index + 1 < len(entries) else "24:00"
        rows.append(
            ScheduleRow(
                upstream_id=f"{channel}:{day.isoformat()}:{start}",
                broadcast_date=day,
                start=start,
                end=end,
                title=title,
                is_rerun="재방송" in title,
                confidence=confidence / 100,
            )
        )
    return tuple(rows)


_KJFM_CHANNEL = "community.kjfm.main"
_KJFM_BASE = "https://kjfm.communityradio.kr"
_KJFM_SCHEDULE_BBS_ID = "BBSMSTR_000000005911"
_KJFM_ARTICLE_DETAIL = re.compile(
    r"fn_selectArticleDetail\('(\d+)','" + re.escape(_KJFM_SCHEDULE_BBS_ID) + r"'\)"
)
_KJFM_IMAGE_HREF = re.compile(r'href="(/ext/html5fileupload/fileDownload\.do\?[^"]+)"')


async def fetch_kjfm_schedule_image(client: Any) -> bytes:
    """광주FM 편성표 게시판에서 가장 최근 글의 첨부 이미지를 내려받는다.

    편성표는 새 주간표가 올라올 때마다 새 게시글(및 새 첨부파일 URL)로
    교체되는 게시판 글이라 고정 이미지 URL이 없다. 목록에서 가장 최근 글의
    nttId를 얻고, 그 글의 상세 내용에서 실제 이미지 다운로드 링크를 뽑아낸다.
    """
    list_response = await client.post(
        f"{_KJFM_BASE}/cop/bbs/selectArticleList.do",
        data={
            "bbsId": _KJFM_SCHEDULE_BBS_ID,
            "nttId": "0",
            "cateId": "0",
            "pageIndex": "1",
            "bbsTyCode": "BBST01",
            "bbsAttrbCode": "BBSA03",
            "searchCnd": "0",
        },
    )
    list_response.raise_for_status()
    article_match = _KJFM_ARTICLE_DETAIL.search(list_response.text)
    if article_match is None:
        raise ValueError("no rows: 광주FM 편성표 게시글을 찾지 못함")

    detail_response = await client.post(
        f"{_KJFM_BASE}/cop/bbs/selectArticleDetail.do",
        data={"bbsId": _KJFM_SCHEDULE_BBS_ID, "nttId": article_match.group(1)},
    )
    detail_response.raise_for_status()
    image_match = _KJFM_IMAGE_HREF.search(detail_response.text)
    if image_match is None:
        raise ValueError("no rows: 광주FM 편성표 첨부 이미지를 찾지 못함")

    image_response = await client.get(_KJFM_BASE + image_match.group(1))
    image_response.raise_for_status()
    return image_response.content


def kjfm_gwangju_fm(image_bytes: bytes, day: date) -> dict[str, tuple[ScheduleRow, ...]]:
    """광주FM 주간편성표 이미지에서 요청한 요일의 편성을 읽는다.

    표는 시간(월~금 공통 폭)|월|화|수|목|금|토|일의 8열이고, 토/일은 모든
    시간대가 "BGM"으로만 표기돼 요일별로 구분되는 실제 프로그램이 없다.
    """
    weekday = day.weekday()
    if weekday >= 5:
        raise ValueError("no rows: 광주FM 토/일은 구분된 편성 없이 BGM만 표기됨")

    image = Image.open(io.BytesIO(image_bytes))
    hlines, vlines = detect_grid_lines(image)
    if len(vlines) != 9:
        raise ValueError(f"광주FM 표 열 개수가 예상과 다름(9개 예상, {len(vlines)}개 감지)")

    day_column = weekday + 1
    entries: list[tuple[str, str, float]] = []
    for index in range(len(hlines) - 1):
        top, bottom = hlines[index], hlines[index + 1]
        if bottom - top < 60:
            continue
        label_text, _ = ocr_cell(image, (vlines[0], top, vlines[1], bottom))
        match = _TIME_LABEL.search(label_text)
        if not match:
            continue
        start = f"{int(match.group(1)):02d}:00"

        title_text, confidence = ocr_cell(
            image, (vlines[day_column], top, vlines[day_column + 1], bottom)
        )
        title = _clean_ocr_text(title_text)
        if not title:
            # 월~금이 한 칸으로 합쳐진 행(재방송/마을동아리 등)은 특정 요일
            # 칸만 잘라내면 가운데로 쏠린 글자가 빈 칸으로 나온다.
            # 월~금 전체 폭으로 다시 읽는다.
            title_text, confidence = ocr_cell(image, (vlines[1], top, vlines[6], bottom))
            title = _clean_ocr_text(title_text)
        if not title or confidence < _OCR_MINIMUM_CONFIDENCE:
            continue
        entries.append((start, title, confidence))

    if not entries:
        raise ValueError("광주FM 편성표 이미지에서 유효한 행을 하나도 못 읽음")
    return {_KJFM_CHANNEL: _rows_from_hourly_entries(_KJFM_CHANNEL, day, entries)}
