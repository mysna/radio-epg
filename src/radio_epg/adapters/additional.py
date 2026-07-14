"""사용자가 확인한 공식 편성표 11종의 엄격한 parser."""

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


def _rows(
    channel: str, day: date, items: Iterable[tuple[str, str, str | None]]
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


def _febc(text: str, day: date) -> dict[str, tuple[ScheduleRow, ...]]:
    _require_date(text, day)
    soup = BeautifulSoup(text, "html.parser")
    items = []
    for node in soup.select(".radio-broadcasting-accordions-wrap .accordion-item"):
        time_node, title_node = node.select_one(".area-txt .time"), node.select_one(".tit")
        if time_node and title_node:
            items.append(
                (time_node.get_text(strip=True), title_node.get_text(" ", strip=True), None)
            )
    channel = "febc.main.main"
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
        "febc": _febc,
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
    "febc-seoul": ("febc.main.main",),
    "cpbc": ("cpbc.main.main",),
    "wbs": ("wbs.main.main",),
    "kfn": ("kookbang.main.main",),
    "gugak": ("kugak.main.main", "kugak.main.gwangju", "kugak.main.daejeon"),
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
        elif source_id == "febc-seoul":
            response = await client.get(endpoint, params={"searchDate": day.isoformat()})
        elif source_id == "cpbc":
            response = await client.get(
                f"https://apis.cpbc.co.kr/radio-api/schedule/{day.strftime('%Y%m%d')}"
            )
        elif source_id == "wbs":
            response = await client.get(
                endpoint, params={"r": "서울", "w": (day.weekday() + 1) % 7}
            )
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
                    parsed = parse_station_schedule(
                        "tbs", await self._request(client, day, url=url), expected_date=day
                    )
                    collected[channel].extend(parsed["tbs.fm.main"])
            else:
                parser_name = {"febc-seoul": "febc"}.get(
                    self.source.source_id, self.source.source_id
                )
                parsed = parse_station_schedule(
                    parser_name, await self._request(client, day), expected_date=day
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
