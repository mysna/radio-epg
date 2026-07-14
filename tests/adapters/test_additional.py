import asyncio
from datetime import date
from pathlib import Path

import httpx
import pytest

from radio_epg.adapters.additional import AdditionalStationAdapter, parse_station_schedule
from radio_epg.adapters.base import CollectionWindow
from radio_epg.config import SourceConfig

FIXTURES = Path(__file__).parents[1] / "fixtures" / "additional"
DAY = date(2026, 7, 14)


@pytest.mark.parametrize(
    ("station", "suffix", "channels", "first_title"),
    [
        ("obs", "html", {"obs.main.main"}, "(재) 모닝브레이크 3부"),
        ("ifm", "html", {"ifm.main.main"}, "당신의 BGM"),
        ("ytn", "html", {"ytn.main.main"}, "YTN24"),
        ("tbs", "html", {"tbs.fm.main"}, "권순우의 새벽공감 1부"),
        ("febc", "html", {"febc.main.main"}, "별처럼 빛나는 그대에게"),
        ("bbs", "html", {"bbs.main.main"}, "경전공부"),
        ("cpbc", "json", {"cpbc.main.main"}, "라디오 고해소 비밀번호 1053"),
        ("wbs", "html", {"wbs.main.main"}, "법문이 있는 음악카페"),
        ("kfn", "json", {"kookbang.main.main"}, "KFN 새벽 음악"),
        (
            "gugak",
            "html",
            {"kugak.main.main", "kugak.main.gwangju", "kugak.main.daejeon"},
            "송지원의 국악산책(재)",
        ),
        ("afn-humphreys", "jsonp", {"afn.main.humphreys"}, "AFN Eagle Overnight"),
    ],
)
def test_each_official_source_has_a_fixture_verified_parser(
    station: str, suffix: str, channels: set[str], first_title: str
) -> None:
    rows = parse_station_schedule(
        station, (FIXTURES / f"{station}.{suffix}").read_text(), expected_date=DAY
    )

    assert set(rows) == channels
    assert next(iter(rows.values()))[0].title == first_title
    assert all(channel_rows[0].end == channel_rows[1].start for channel_rows in rows.values())


def test_parser_rejects_a_response_for_another_date() -> None:
    with pytest.raises(ValueError, match="date"):
        parse_station_schedule(
            "obs", (FIXTURES / "obs.html").read_text(), expected_date=date(2026, 7, 13)
        )


def _source(source_id: str, url: str) -> SourceConfig:
    return SourceConfig(
        source_id=source_id,
        name=source_id,
        source_kind="official",
        source_url=url,
        priority=100,
        adapter="additional",
    )


def test_tbs_fm_and_efm_have_channel_specific_source_event_ids() -> None:
    fixture = (FIXTURES / "tbs.html").read_text()

    class Client:
        async def post(self, url: str, **_kwargs: object) -> httpx.Response:
            return httpx.Response(200, text=fixture, request=httpx.Request("POST", url))

    adapter = AdditionalStationAdapter(
        _source("tbs", "https://tbs.seoul.kr/fm/schedule.do"), client=Client()
    )
    result = asyncio.run(adapter.collect(CollectionWindow(DAY, DAY)))
    event_ids = {
        channel: {row.source_event_id for row in result.schedules if row.channel_id == channel}
        for channel in ("tbs.fm.main", "tbs.efm.main")
    }

    assert all(event_ids.values())
    assert event_ids["tbs.fm.main"].isdisjoint(event_ids["tbs.efm.main"])


def test_wbs_retries_a_transient_http_failure() -> None:
    fixture = (FIXTURES / "wbs.html").read_text()

    class Client:
        attempts = 0

        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            self.attempts += 1
            status = 503 if self.attempts == 1 else 200
            return httpx.Response(status, text=fixture, request=httpx.Request("GET", url))

    client = Client()
    adapter = AdditionalStationAdapter(
        _source("wbs", "https://wbsi.kr/schedule_radio.php"), client=client
    )
    result = asyncio.run(adapter.collect(CollectionWindow(DAY, DAY)))

    assert result.schedules
    assert client.attempts == 2
