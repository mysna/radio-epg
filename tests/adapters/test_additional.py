import asyncio
from datetime import date
from pathlib import Path

import httpx
import pytest

from radio_epg.adapters.additional import (
    AdditionalStationAdapter,
    _cbs_pohang_weekly,
    _cbs_regional,
    _febc,
    _knn_busan,
    _mbc_regional_weekly,
    _sbs_affiliate_tbc,
    _tjb_daejeon,
    parse_station_schedule,
)
from radio_epg.adapters.base import CollectionWindow
from radio_epg.config import SourceConfig

FIXTURES = Path(__file__).parents[1] / "fixtures" / "additional"
DAY = date(2026, 7, 14)
REGIONAL_DAY = date(2026, 9, 5)


@pytest.mark.parametrize(
    ("station", "suffix", "channels", "first_title"),
    [
        ("obs", "html", {"obs.main.main"}, "(재) 모닝브레이크 3부"),
        ("ifm", "html", {"ifm.main.main"}, "당신의 BGM"),
        ("ytn", "html", {"ytn.main.main"}, "YTN24"),
        ("tbs", "html", {"tbs.fm.main"}, "권순우의 새벽공감 1부"),
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


@pytest.mark.parametrize(
    ("fixture_name", "channel"),
    [
        ("febc-seoul", "febc.main.main"),
        ("febc-busan", "febc.main.busan"),
    ],
)
def test_febc_parser_maps_the_shared_cms_response_to_the_requested_channel(
    fixture_name: str, channel: str
) -> None:
    rows = _febc((FIXTURES / f"{fixture_name}.html").read_text(), DAY, channel)

    assert set(rows) == {channel}
    assert rows[channel][0].title == "별처럼 빛나는 그대에게"


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


def test_febc_collects_every_region_as_one_source() -> None:
    seoul_fixture = (FIXTURES / "febc-seoul.html").read_text()
    busan_fixture = (FIXTURES / "febc-busan.html").read_text()

    class Client:
        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            fixture = busan_fixture if "busan" in url else seoul_fixture
            return httpx.Response(200, text=fixture, request=httpx.Request("GET", url))

    adapter = AdditionalStationAdapter(
        _source("febc", "https://seoul.febc.net/radio/schedule"), client=Client()
    )
    result = asyncio.run(adapter.collect(CollectionWindow(DAY, DAY)))

    channel_ids = {row.channel_id for row in result.schedules}
    assert "febc.main.main" in channel_ids
    assert "febc.main.busan" in channel_ids
    assert len(channel_ids) == 13


@pytest.mark.parametrize(
    ("fixture_name", "channel", "first_title"),
    [
        ("mbc-gangneung-am", "mbc.sfm.gangneung", "낭만 가요 1,2부"),
        ("mbc-gangneung-fm", "mbc.fm4u.gangneung", "FM영화음악"),
    ],
)
def test_mbc_regional_weekly_parser_marks_rows_with_reduced_confidence(
    fixture_name: str, channel: str, first_title: str
) -> None:
    rows = _mbc_regional_weekly((FIXTURES / f"{fixture_name}.html").read_text(), DAY, channel)

    assert set(rows) == {channel}
    assert rows[channel][0].title == first_title
    assert all(row.confidence == pytest.approx(0.7) for row in rows[channel])


def test_regional_mbc_collects_both_bands_of_a_station_as_one_source() -> None:
    am_fixture = (FIXTURES / "mbc-gangneung-am.html").read_text()
    fm_fixture = (FIXTURES / "mbc-gangneung-fm.html").read_text()

    class Client:
        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            fixture = am_fixture if "g=am" in url else fm_fixture
            return httpx.Response(200, text=fixture, request=httpx.Request("GET", url))

    adapter = AdditionalStationAdapter(
        _source("regional-mbc", "https://www.mbceg.co.kr/schedule/cp_depart"), client=Client()
    )
    result = asyncio.run(adapter.collect(CollectionWindow(DAY, DAY)))

    channel_ids = {row.channel_id for row in result.schedules}
    assert channel_ids == {"mbc.sfm.gangneung", "mbc.fm4u.gangneung"}
    assert all(row.confidence == pytest.approx(0.7) for row in result.schedules)


def test_cbs_regional_parser_reads_the_shared_appradio_api_response() -> None:
    text = (FIXTURES / "cbs-regional-busan.json").read_text()

    rows = _cbs_regional(text, REGIONAL_DAY, "cbs.sfm.busan")

    assert set(rows) == {"cbs.sfm.busan"}
    assert rows["cbs.sfm.busan"][0].title == "최정원의 당신을 향한 노래 (재)"
    assert rows["cbs.sfm.busan"][0].start == "00:00"


def test_regional_cbs_collects_every_configured_station_as_one_source() -> None:
    fixture = (FIXTURES / "cbs-regional-busan.json").read_text()
    pohang_fixture = (FIXTURES / "cbs-pohang-weekly.html").read_text()

    class Client:
        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            body = pohang_fixture if "phcbs.co.kr" in url else fixture
            return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    adapter = AdditionalStationAdapter(
        _source("regional-cbs", "https://appradio.cbs.co.kr/51/GetInfo_ProgSchedule.asp"),
        client=Client(),
    )
    result = asyncio.run(adapter.collect(CollectionWindow(REGIONAL_DAY, REGIONAL_DAY)))

    channel_ids = {row.channel_id for row in result.schedules}
    assert "cbs.sfm.busan" in channel_ids
    assert "cbs.mfm.busan" in channel_ids
    assert "cbs.sfm.ulsan" in channel_ids


@pytest.mark.parametrize(
    ("day", "first_title"),
    [
        (date(2026, 9, 7), "새아침입니다"),  # 월요일
        (date(2026, 9, 12), "새아침입니다"),  # 토요일
        (date(2026, 9, 13), "새아침입니다"),  # 일요일
    ],
)
def test_cbs_pohang_weekly_parser_picks_the_matching_weekday_bucket(
    day: date, first_title: str
) -> None:
    text = (FIXTURES / "cbs-pohang-weekly.html").read_text()

    rows = _cbs_pohang_weekly(text, day, "cbs.sfm.pohang")

    assert set(rows) == {"cbs.sfm.pohang"}
    assert rows["cbs.sfm.pohang"][0].title == first_title
    assert all(row.confidence == pytest.approx(0.7) for row in rows["cbs.sfm.pohang"])


def test_regional_cbs_includes_pohangs_weekly_template() -> None:
    cbs_fixture = (FIXTURES / "cbs-regional-busan.json").read_text()
    pohang_fixture = (FIXTURES / "cbs-pohang-weekly.html").read_text()

    class Client:
        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            fixture = pohang_fixture if "phcbs.co.kr" in url else cbs_fixture
            return httpx.Response(200, text=fixture, request=httpx.Request("GET", url))

    adapter = AdditionalStationAdapter(
        _source("regional-cbs", "https://appradio.cbs.co.kr/51/GetInfo_ProgSchedule.asp"),
        client=Client(),
    )
    result = asyncio.run(adapter.collect(CollectionWindow(REGIONAL_DAY, REGIONAL_DAY)))

    channel_ids = {row.channel_id for row in result.schedules}
    assert "cbs.sfm.pohang" in channel_ids


def test_sbs_affiliate_tbc_parser_reads_the_date_specific_schedule_page() -> None:
    text = (FIXTURES / "sbs-affiliate-tbc-daegu.html").read_text()

    rows = _sbs_affiliate_tbc(text, REGIONAL_DAY, "sbs.powerfm.daegu")

    assert set(rows) == {"sbs.powerfm.daegu"}
    assert rows["sbs.powerfm.daegu"][0].title == "이인권의 펀펀투데이 1부"


def test_regional_sbs_collects_tbc_knn_and_tjb() -> None:
    tbc_fixture = (FIXTURES / "sbs-affiliate-tbc-daegu.html").read_text()
    knn_fixture = (FIXTURES / "sbs-knn-busan.html").read_text()
    tjb_fixture = (FIXTURES / "sbs-tjb-daejeon.html").read_text()

    class Client:
        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            if "knn.co.kr" in url:
                body = knn_fixture
            elif "tjb.co.kr" in url:
                body = tjb_fixture
            else:
                body = tbc_fixture
            return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    adapter = AdditionalStationAdapter(
        _source("regional-sbs", "https://tbc.co.kr/schedule/"), client=Client()
    )
    result = asyncio.run(adapter.collect(CollectionWindow(REGIONAL_DAY, REGIONAL_DAY)))

    channel_ids = {row.channel_id for row in result.schedules}
    assert channel_ids == {
        "sbs.powerfm.daegu",
        "sbs.powerfm.busan",
        "sbs.lovefm.busan",
        "sbs.powerfm.daejeon",
    }


def test_tjb_daejeon_parser_normalizes_the_midnight_crossing() -> None:
    text = (FIXTURES / "sbs-tjb-daejeon.html").read_text()

    rows = _tjb_daejeon(text, REGIONAL_DAY, "sbs.powerfm.daejeon")

    assert set(rows) == {"sbs.powerfm.daejeon"}
    starts = [row.start for row in rows["sbs.powerfm.daejeon"]]
    assert starts == ["05:00", "06:00", "06:30", "25:00", "26:00", "27:00", "28:00"]


@pytest.mark.parametrize(
    ("channel", "first_title"),
    [
        ("sbs.powerfm.busan", "펀펀투데이 1부"),
        ("sbs.lovefm.busan", "OLDIES 20 2부"),
    ],
)
def test_knn_busan_parser_reads_the_matching_channel_section(
    channel: str, first_title: str
) -> None:
    text = (FIXTURES / "sbs-knn-busan.html").read_text()

    rows = _knn_busan(text, REGIONAL_DAY, channel)

    assert set(rows) == {channel}
    assert rows[channel][0].title == first_title


def test_wbs_survives_a_short_burst_of_transient_http_failures(monkeypatch) -> None:
    fixture = (FIXTURES / "wbs.html").read_text()

    async def skip_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("radio_epg.adapters.additional.asyncio.sleep", skip_sleep)

    class Client:
        attempts = 0

        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            self.attempts += 1
            status = 503 if self.attempts <= 3 else 200
            return httpx.Response(status, text=fixture, request=httpx.Request("GET", url))

    client = Client()
    adapter = AdditionalStationAdapter(
        _source("wbs", "https://wbsi.kr/schedule_radio.php"), client=client
    )
    result = asyncio.run(adapter.collect(CollectionWindow(DAY, DAY)))

    assert result.schedules
    assert client.attempts == 4
