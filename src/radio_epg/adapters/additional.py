"""사용자가 확인한 공식 편성표 11종의 엄격한 parser."""

import asyncio
import json
import re
import ssl
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

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


# MBC 지역국 자체 홈페이지는 요일별로 고정된 주간 편성 템플릿만 제공하고, 그날그날의
# 실제 특보·결방 여부는 반영하지 않는다. 그래도 방송사가 직접 공개한 정규 편성이므로
# 낮은 confidence로 신뢰도를 낮춰서 싣는다.
_MBC_TEMPLATE_CONFIDENCE = 0.7


def _mbc_regional_weekly(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
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
    return {channel: _rows(channel, day, items, confidence=_MBC_TEMPLATE_CONFIDENCE)}


# 지역 MBC는 공유 CMS 없이 방송사마다 완전히 별도 도메인을 쓴다. 실제로 접속·구조를
# 확인한 방송국만 여기 추가한다. g=am은 표준FM, g=fm은 FM4U, d는 날짜가 아니라
# 요일 index(일=0~토=6)다.
_MBC_REGIONAL_STATIONS: dict[str, tuple[str, str, str]] = {
    # station: (표준FM channel_id, FM4U channel_id, base_url)
    "gangneung": (
        "mbc.sfm.gangneung",
        "mbc.fm4u.gangneung",
        "https://www.mbceg.co.kr/schedule/cp_depart",
    ),
}


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


def _bbs(text: str, day: date) -> dict[str, tuple[ScheduleRow, ...]]:
    _require_date(text, day)
    soup = BeautifulSoup(text, "html.parser")
    items = []
    for node in soup.select("#DivSchedule .program"):
        time_node, title_node = node.select_one(".date-box p"), node.select_one(".date-box strong")
        if time_node and title_node:
            items.append(
                (time_node.get_text(strip=True), title_node.get_text(" ", strip=True), None)
            )
    channel = "bbs.main.main"
    return {channel: _rows(channel, day, items)}


def _cpbc(text: str, day: date) -> dict[str, tuple[ScheduleRow, ...]]:
    payload = json.loads(text)
    items = []
    for raw in payload:
        if not str(raw.get("START_DATE", "")).startswith(day.isoformat()):
            raise ValueError("official schedule date does not match requested date")
        items.append((raw["START_TIME"], raw["TITLE"], raw["END_TIME"]))
    channel = "cpbc.main.main"
    return {channel: _rows(channel, day, items)}


def _kfn(text: str, day: date) -> dict[str, tuple[ScheduleRow, ...]]:
    payload = json.loads(text)
    items = []
    for raw in payload.get("map", {}).get("resultList", []):
        if raw.get("program_date") != day.strftime("%Y%m%d"):
            raise ValueError("official schedule date does not match requested date")
        start, end = raw["program_start_time"], raw["program_end_time"]
        items.append((f"{start[:2]}:{start[2:]}", raw["program_name"], f"{end[:2]}:{end[2:]}"))
    channel = "kookbang.main.main"
    return {channel: _rows(channel, day, items)}


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


def _afn(text: str, day: date) -> dict[str, tuple[ScheduleRow, ...]]:
    match = re.fullmatch(r"\s*\$afn\.ProcessRadioSchedule\((.*)\)\s*;?\s*", text, re.DOTALL)
    if match is None:
        raise ValueError("AFN schedule JSONP contract changed")
    payload = json.loads(match.group(1))
    if payload.get("station") != "Humphreys" or payload.get("date") != day.isoformat():
        raise ValueError("official schedule date or station does not match requested value")
    channel = "afn.main.humphreys"
    return {
        channel: _rows(
            channel, day, ((raw["start"], raw["title"], raw["end"]) for raw in payload["events"])
        )
    }


# CBS 지역국은 자체 도메인을 쓰지만, 편성표 위젯은 전부 CBS 본사의 공유 API
# (appradio.cbs.co.kr)를 station 번호로 구분해서 호출한다. FEBC와 마찬가지로
# fixture로 실제 접속·구조를 확인한 지역국만 여기 추가한다.
def _hmm_to_time(value: int) -> str:
    hour, minute = divmod(value, 100)
    return f"{hour:02d}:{minute:02d}"


def _cbs_regional(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    payload = json.loads(text)
    if payload.get("date") != int(day.strftime("%Y%m%d")):
        raise ValueError("official schedule date does not match requested date")
    items = [
        (_hmm_to_time(entry["start"]), entry["pname"], _hmm_to_time(entry["end"]))
        for entry in payload["ProgSchedule"]
    ]
    return {channel: _rows(channel, day, items)}


# station: (표준FM channel_id, 음악FM channel_id 또는 None, appradio station 번호)
_CBS_REGIONAL_STATIONS: dict[str, tuple[str, str | None, int]] = {
    "busan": ("cbs.sfm.busan", "cbs.mfm.busan", 2),
    "jeonbuk": ("cbs.sfm.jeonbuk", None, 4),
    "cheongju": ("cbs.sfm.cheongju", None, 5),
    "daejeon": ("cbs.sfm.daejeon", None, 7),
    "gyeongnam": ("cbs.sfm.gyeongnam", None, 9),
    "jeju": ("cbs.sfm.jeju", None, 10),
    "jeonnam": ("cbs.sfm.jeonnam", None, 12),
    "ulsan": ("cbs.sfm.ulsan", None, 13),
}


# 포항CBS는 공유 API 대신 자체 페이지에 평일/토/일 3종 고정 주간표를 각각
# <div id="Mon|Sat|Sun">로 서버 렌더링해서 하나의 응답에 전부 담아 보낸다.
# 날짜별 결방·특보는 반영되지 않으므로 MBC 지역국과 같은 낮은 confidence를 쓴다.
_CBS_WEEKDAY_BUCKETS = {0: "Mon", 1: "Mon", 2: "Mon", 3: "Mon", 4: "Mon", 5: "Sat", 6: "Sun"}


def _cbs_pohang_weekly(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    bucket = _CBS_WEEKDAY_BUCKETS[day.weekday()]
    soup = BeautifulSoup(text, "html.parser")
    container = soup.find(id=bucket)
    if container is None:
        raise ValueError("official schedule weekday section missing")
    items: list[tuple[str, str, str | None]] = []
    for row in container.select(".pairingCon"):
        time_node = row.select_one(".time")
        title_node = row.select_one(".proyiynph .title")
        if time_node and title_node:
            items.append((time_node.get_text(strip=True), title_node.get_text(strip=True), None))
    return {channel: _rows(channel, day, items, confidence=_MBC_TEMPLATE_CONFIDENCE)}


_CBS_WEEKLY_STATIONS: dict[str, tuple[str, str]] = {
    # station: (channel_id, url)
    "pohang": ("cbs.sfm.pohang", "https://phcbs.co.kr/pairing_standardFm"),
}


# SBS 지역 제휴사는 CBS와 달리 회사마다 완전히 다른 사이트를 쓴다. 실제로 접속해서
# 날짜별 편성 페이지 구조를 확인한 곳만 추가한다. TBC(대구)는 sYear/sMonth/sDate
# 쿼리로 날짜별 서버 렌더링 HTML을 제공한다.
def _sbs_affiliate_tbc(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
    return _table(text, day, channel, selector="table.sch tr")


_SBS_AFFILIATE_STATIONS: dict[str, tuple[str, str]] = {
    # station: (channel_id, base_url)
    "daegu": ("sbs.powerfm.daegu", "https://tbc.co.kr/schedule/"),
}


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
def _knn_busan(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
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


_KNN_BUSAN_CHANNELS = ("sbs.powerfm.busan", "sbs.lovefm.busan")


# TJB(대전)는 날짜별 페이지(/sub0502/pairing/radio/date/YYYY-MM-DD)를 서버 렌더링해서
# 준다. 자정 전후 표기가 뒤섞여 있어(23:30 -> 00:00 -> 25:00 -> 02:00) 정규화가 필요하다.
def _tjb_daejeon(text: str, day: date, channel: str) -> dict[str, tuple[ScheduleRow, ...]]:
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


_TJB_DAEJEON_CHANNEL = "sbs.powerfm.daejeon"


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
        "afn-humphreys": _afn,
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
    "cpbc": ("cpbc.main.main",),
    "wbs": ("wbs.main.main",),
    "kfn": ("kookbang.main.main",),
    "gugak": ("kugak.main.main", "kugak.main.gwangju", "kugak.main.daejeon"),
    "febc": tuple(channel for channel, _ in _FEBC_REGIONS.values()),
    "regional-mbc": tuple(
        channel
        for sfm_channel, fm4u_channel, _ in _MBC_REGIONAL_STATIONS.values()
        for channel in (sfm_channel, fm4u_channel)
    ),
    "regional-cbs": tuple(
        channel
        for sfm_channel, mfm_channel, _ in _CBS_REGIONAL_STATIONS.values()
        for channel in (sfm_channel, mfm_channel)
        if channel is not None
    )
    + tuple(channel for channel, _ in _CBS_WEEKLY_STATIONS.values()),
    "regional-sbs": tuple(channel for channel, _ in _SBS_AFFILIATE_STATIONS.values())
    + _KNN_BUSAN_CHANNELS
    + (_TJB_DAEJEON_CHANNEL,),
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

    async def _request(self, client: Any, day: date, *, url: str | None = None) -> str:
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
                f"https://apis.cpbc.co.kr/radio-api/schedule/{day.strftime('%Y%m%d')}"
            )
        elif source_id == "wbs":
            for attempt in range(5):
                response = await client.get(
                    endpoint, params={"r": "서울", "w": (day.weekday() + 1) % 7}
                )
                if response.status_code not in _TRANSIENT_STATUSES or attempt == 4:
                    break
                await asyncio.sleep(0.25 * (2**attempt))
        elif source_id == "kfn":
            response = await client.post(
                "https://radio.dema.mil.kr/api/v1/media/radio/fmTimeTableListAjax.do",
                json={"program_date": day.strftime("%Y%m%d")},
                headers={"Referer": self.source.source_url},
            )
        elif source_id == "gugak":
            response = await client.get(
                endpoint, params={"sub_num": "786", "today": day.strftime("%Y%m%d")}
            )
        elif source_id in {"regional-mbc", "regional-cbs", "regional-sbs"}:
            response = await client.get(endpoint)
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
            if self.source.source_id == "tbs":
                for channel, url in (
                    ("tbs.fm.main", "https://tbs.seoul.kr/fm/schedule.do"),
                    ("tbs.efm.main", "https://tbs.seoul.kr/eFm/schedule.do"),
                ):
                    text = await self._request(client, day, url=url)
                    collected[channel].extend(_table(text, day, channel)[channel])
            elif self.source.source_id == "febc":
                for channel, url in _FEBC_REGIONS.values():
                    text = await self._request(client, day, url=url)
                    collected[channel].extend(_febc(text, day, channel)[channel])
            elif self.source.source_id == "regional-mbc":
                weekday = (day.weekday() + 1) % 7
                for sfm_channel, fm4u_channel, base_url in _MBC_REGIONAL_STATIONS.values():
                    for channel, band in ((sfm_channel, "am"), (fm4u_channel, "fm")):
                        url = f"{base_url}?g={band}&d={weekday}&a=g"
                        text = await self._request(client, day, url=url)
                        collected[channel].extend(_mbc_regional_weekly(text, day, channel)[channel])
            elif self.source.source_id == "regional-cbs":
                for sfm_channel, mfm_channel, station in _CBS_REGIONAL_STATIONS.values():
                    for channel, ch_param in ((sfm_channel, 1), (mfm_channel, 0)):
                        if channel is None:
                            continue
                        url = (
                            "https://appradio.cbs.co.kr/51/GetInfo_ProgSchedule.asp"
                            f"?station={station}&ch={ch_param}&fetchDate={day.isoformat()}"
                        )
                        text = await self._request(client, day, url=url)
                        collected[channel].extend(_cbs_regional(text, day, channel)[channel])
                for channel, url in _CBS_WEEKLY_STATIONS.values():
                    text = await self._request(client, day, url=url)
                    collected[channel].extend(_cbs_pohang_weekly(text, day, channel)[channel])
            elif self.source.source_id == "regional-sbs":
                for channel, base_url in _SBS_AFFILIATE_STATIONS.values():
                    url = (
                        f"{base_url}?mid=7_181&sYear={day.strftime('%Y')}"
                        f"&sMonth={day.strftime('%m')}&sDate={day.strftime('%d')}"
                    )
                    text = await self._request(client, day, url=url)
                    collected[channel].extend(_sbs_affiliate_tbc(text, day, channel)[channel])
                knn_url = (
                    f"https://www.knn.co.kr/schedule/schedule.do?date={day.strftime('%Y%m%d')}"
                    "&channel=rd1"
                )
                knn_text = await self._request(client, day, url=knn_url)
                for channel in _KNN_BUSAN_CHANNELS:
                    collected[channel].extend(_knn_busan(knn_text, day, channel)[channel])
                tjb_url = f"https://www.tjb.co.kr/sub0502/pairing/radio/date/{day.isoformat()}"
                tjb_text = await self._request(client, day, url=tjb_url)
                collected[_TJB_DAEJEON_CHANNEL].extend(
                    _tjb_daejeon(tjb_text, day, _TJB_DAEJEON_CHANNEL)[_TJB_DAEJEON_CHANNEL]
                )
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
