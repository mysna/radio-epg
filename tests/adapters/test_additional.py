import asyncio
from datetime import date
from pathlib import Path

import httpx
import pytest

from radio_epg.adapters.additional import (
    AdditionalStationAdapter,
    _arirang,
    _bbs,
    _befm,
    _cbs_regional,
    _cjb_cheongju,
    _cpbc_regional,
    _febc,
    _jibs_jeju,
    _knn_busan,
    _mbc_regional_weekly,
    _mbc_shared_cms,
    _sbs_affiliate_tbc,
    _tjb_daejeon,
    _ubc_ulsan,
    _wonju_mbc,
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
        ("kfn", "json", {"kookbang.main.main"}, "KFN 논스톱 뮤직 1부"),
        (
            "gugak",
            "html",
            {"kugak.main.main", "kugak.main.gwangju", "kugak.main.daejeon"},
            "송지원의 국악산책(재)",
        ),
        ("befm", "html", {"befm.main.main"}, "[ L ] 4 My Busan (RE)"),
        ("arirang", "json", {"arirang.main.main"}, "K-POP Mix. 120"),
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
    shared_cms_fixture = (FIXTURES / "mbc-daegu.html").read_text()
    wonju_fixture = (FIXTURES / "wonju-mbc-fm4u.html").read_text()

    class Client:
        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            if "g=am" in url:
                fixture = am_fixture
            elif "g=fm" in url:
                fixture = fm_fixture
            elif "wjmbc.co.kr" in url:
                fixture = wonju_fixture
            else:
                fixture = shared_cms_fixture
            return httpx.Response(200, text=fixture, request=httpx.Request("GET", url))

    adapter = AdditionalStationAdapter(
        _source("regional-mbc", "https://www.mbceg.co.kr/schedule/cp_depart"), client=Client()
    )
    result = asyncio.run(adapter.collect(CollectionWindow(REGIONAL_DAY, REGIONAL_DAY)))

    channel_ids = {row.channel_id for row in result.schedules}
    assert channel_ids == {
        "mbc.sfm.gangneung",
        "mbc.fm4u.gangneung",
        "mbc.sfm.daegu",
        "mbc.fm4u.daegu",
        "mbc.sfm.jeju",
        "mbc.fm4u.jeju",
        "mbc.sfm.yeosu",
        "mbc.fm4u.yeosu",
        "mbc.sfm.mokpo",
        "mbc.fm4u.mokpo",
        "mbc.sfm.gwangju",
        "mbc.fm4u.gwangju",
        "mbc.sfm.wonju",
        "mbc.fm4u.wonju",
    }


def test_mbc_shared_cms_parser_reads_the_date_specific_schedule_page() -> None:
    text = (FIXTURES / "mbc-daegu.html").read_text()

    rows = _mbc_shared_cms(text, REGIONAL_DAY, "mbc.sfm.daegu")

    assert set(rows) == {"mbc.sfm.daegu"}
    assert rows["mbc.sfm.daegu"][0].title == "오늘의 대구문화방송"
    assert all(row.confidence == pytest.approx(1.0) for row in rows["mbc.sfm.daegu"])


def test_mbc_shared_cms_normalizes_times_that_wrap_past_midnight() -> None:
    text = (FIXTURES / "mbc-daegu-midnight-wrap.html").read_text()

    rows = _mbc_shared_cms(text, REGIONAL_DAY, "mbc.sfm.daegu")

    starts = [row.start for row in rows["mbc.sfm.daegu"]]
    assert starts == ["23:05", "24:00", "25:00"]
    assert rows["mbc.sfm.daegu"][-1].end == "30:00"


def test_cbs_regional_parser_reads_the_shared_appradio_api_response() -> None:
    text = (FIXTURES / "cbs-regional-busan.json").read_text()

    rows = _cbs_regional(text, REGIONAL_DAY, "cbs.sfm.busan")

    assert set(rows) == {"cbs.sfm.busan"}
    assert rows["cbs.sfm.busan"][0].title == "최정원의 당신을 향한 노래 (재)"
    assert rows["cbs.sfm.busan"][0].start == "00:00"


def test_regional_cbs_collects_every_configured_station_as_one_source() -> None:
    fixture = (FIXTURES / "cbs-regional-busan.json").read_text()

    class Client:
        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            return httpx.Response(200, text=fixture, request=httpx.Request("GET", url))

    adapter = AdditionalStationAdapter(
        _source("regional-cbs", "https://appradio.cbs.co.kr/51/GetInfo_ProgSchedule.asp"),
        client=Client(),
    )
    result = asyncio.run(adapter.collect(CollectionWindow(REGIONAL_DAY, REGIONAL_DAY)))

    channel_ids = {row.channel_id for row in result.schedules}
    assert "cbs.sfm.busan" in channel_ids
    assert "cbs.mfm.busan" in channel_ids
    assert "cbs.sfm.gwangju" in channel_ids
    assert "cbs.sfm.pohang" in channel_ids
    assert "cbs.sfm.ulsan" in channel_ids
    assert "cbs.sfm.daegu" in channel_ids
    assert "cbs.sfm.chuncheon" in channel_ids


def test_cpbc_regional_parser_reads_the_station_specific_endpoint_response() -> None:
    text = (FIXTURES / "cpbc-regional-daegu.json").read_text()

    rows = _cpbc_regional(text, DAY, "cpbc.main.daegu")

    assert set(rows) == {"cpbc.main.daegu"}
    assert rows["cpbc.main.daegu"][0].title == "매일미사"
    assert rows["cpbc.main.daegu"][-1].title == "오늘의 강론(대구)"
    assert rows["cpbc.main.daegu"][0].start == "05:00"


def test_cpbc_collects_main_and_regional_stations_as_one_source() -> None:
    main_fixture = (FIXTURES / "cpbc.json").read_text()
    regional_fixture = (FIXTURES / "cpbc-regional-daegu.json").read_text()

    class Client:
        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            fixture = regional_fixture if "/schedule/0" in url else main_fixture
            return httpx.Response(200, text=fixture, request=httpx.Request("GET", url))

    adapter = AdditionalStationAdapter(
        _source("cpbc", "https://www.cpbc.co.kr/schedule.html?channel=radio"), client=Client()
    )
    result = asyncio.run(adapter.collect(CollectionWindow(DAY, DAY)))

    channel_ids = {row.channel_id for row in result.schedules}
    assert channel_ids == {
        "cpbc.main.main",
        "cpbc.main.busan",
        "cpbc.main.daegu",
        "cpbc.main.gwangju",
    }


def test_sbs_affiliate_tbc_parser_reads_the_date_specific_schedule_page() -> None:
    text = (FIXTURES / "sbs-affiliate-tbc-daegu.html").read_text()

    rows = _sbs_affiliate_tbc(text, REGIONAL_DAY, "sbs.powerfm.daegu")

    assert set(rows) == {"sbs.powerfm.daegu"}
    assert rows["sbs.powerfm.daegu"][0].title == "이인권의 펀펀투데이 1부"


def test_regional_sbs_collects_tbc_knn_tjb_ubc_cjb_and_jibs() -> None:
    tbc_fixture = (FIXTURES / "sbs-affiliate-tbc-daegu.html").read_text()
    knn_fixture = (FIXTURES / "sbs-knn-busan.html").read_text()
    tjb_fixture = (FIXTURES / "sbs-tjb-daejeon.html").read_text()
    ubc_fixture = (FIXTURES / "sbs-ubc-ulsan.json").read_text()
    cjb_fixture = (FIXTURES / "cjb-cheongju.json").read_text()
    jibs_fixture = (FIXTURES / "jibs-jeju.html").read_text()

    class Client:
        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            if "knn.co.kr" in url:
                body = knn_fixture
            elif "tjb.co.kr" in url:
                body = tjb_fixture
            elif "ubc.co.kr" in url:
                body = ubc_fixture
            elif "cjb.co.kr" in url:
                body = cjb_fixture
            elif "jibs.co.kr" in url:
                body = jibs_fixture
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
        "sbs.powerfm.ulsan",
        "sbs.powerfm.cheongju",
        "sbs.powerfm.jeju",
    }


def test_ubc_ulsan_parser_uses_explicit_start_and_end_times() -> None:
    text = (FIXTURES / "sbs-ubc-ulsan.json").read_text()

    rows = _ubc_ulsan(text, REGIONAL_DAY, "sbs.powerfm.ulsan")

    assert set(rows) == {"sbs.powerfm.ulsan"}
    assert rows["sbs.powerfm.ulsan"][0].title == "뮤직하이"
    assert rows["sbs.powerfm.ulsan"][0].start == "00:00"
    assert rows["sbs.powerfm.ulsan"][0].end == "01:00"


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


def test_cjb_cheongju_parser_uses_explicit_start_and_end_times() -> None:
    text = (FIXTURES / "cjb-cheongju.json").read_text()

    rows = _cjb_cheongju(text, REGIONAL_DAY, "sbs.powerfm.cheongju")

    assert set(rows) == {"sbs.powerfm.cheongju"}
    starts = [row.start for row in rows["sbs.powerfm.cheongju"]]
    assert starts == ["05:00", "06:00", "07:00", "27:00", "28:00"]
    assert rows["sbs.powerfm.cheongju"][0].title == "새벽을 여는 친구"


def test_wonju_mbc_parser_picks_the_column_matching_the_requested_weekday() -> None:
    text = (FIXTURES / "wonju-mbc-fm4u.html").read_text()

    weekday_rows = _wonju_mbc(text, date(2026, 9, 7), "mbc.fm4u.wonju")
    weekend_rows = _wonju_mbc(text, date(2026, 9, 12), "mbc.fm4u.wonju")

    assert weekday_rows["mbc.fm4u.wonju"][1].title == "친한친구 (1,2부)"
    assert weekend_rows["mbc.fm4u.wonju"][1].title == "스포왕 고영배 (1,2부)"
    assert all(row.confidence == pytest.approx(0.7) for row in weekday_rows["mbc.fm4u.wonju"])

    # 표가 다음날 첫 시각(09:00)까지 이어붙어 있으므로, 그 반복 지점 이전에서 끊는다.
    # 자정을 넘긴 00:05는 24시간을 더해 단조 증가하도록 정규화되고, 마지막 항목의
    # 종료 시각은 "다음날 09:00"(33:00)이 되어야 한다.
    rows = weekday_rows["mbc.fm4u.wonju"]
    assert [row.start for row in rows] == ["09:00", "10:00", "11:00", "12:00", "23:00", "24:05"]
    assert rows[-1].end == "33:00"


def test_jibs_jeju_parser_strips_badges_and_normalizes_midnight_wrap() -> None:
    text = (FIXTURES / "jibs-jeju.html").read_text()

    rows = _jibs_jeju(text, REGIONAL_DAY, "sbs.powerfm.jeju")

    assert set(rows) == {"sbs.powerfm.jeju"}
    starts = [row.start for row in rows["sbs.powerfm.jeju"]]
    assert starts == ["05:00", "16:00", "23:00", "25:00"]
    assert rows["sbs.powerfm.jeju"][1].title == "이정민의 All4U"
    assert all(row.confidence == pytest.approx(0.7) for row in rows["sbs.powerfm.jeju"])


def test_befm_parser_picks_the_div_matching_the_requested_weekday() -> None:
    text = (FIXTURES / "befm.html").read_text()

    mon_rows = _befm(text, date(2026, 9, 7))  # Monday
    tue_rows = _befm(text, date(2026, 9, 8))  # Tuesday (tue-thu)

    assert mon_rows["befm.main.main"][0].title == "[ L ] World Classics (RE)"
    assert tue_rows["befm.main.main"][0].title == "[ L ] 4 My Busan (RE)"
    assert all(row.confidence == pytest.approx(0.7) for row in mon_rows["befm.main.main"])


def test_arirang_parser_computes_end_time_from_duration() -> None:
    text = (FIXTURES / "arirang.json").read_text()

    rows = _arirang(text, DAY)

    assert set(rows) == {"arirang.main.main"}
    # 중간 항목의 종료 시각은 _rows()가 다음 항목의 시작 시각으로 덮어써서 실제
    # duration과 다를 수 있다(정상 동작). 마지막 항목만 duration으로 계산한 값이 쓰인다.
    starts = [(row.start, row.end) for row in rows["arirang.main.main"]]
    assert starts == [("00:00", "02:00"), ("02:00", "22:00"), ("22:00", "24:00")]
    assert all(row.confidence == pytest.approx(0.7) for row in rows["arirang.main.main"])


def test_bbs_normalizes_times_that_wrap_past_midnight() -> None:
    text = (FIXTURES / "bbs-midnight-wrap.html").read_text()

    rows = _bbs(text, date(2026, 9, 6))

    starts = [row.start for row in rows["bbs.main.main"]]
    assert starts == ["22:00", "23:55", "24:00", "24:40", "25:00", "25:45"]
    assert rows["bbs.main.main"][-1].end == "30:00"


def test_ggn_collects_the_weekday_matching_template() -> None:
    fixture = (FIXTURES / "ggn.html").read_text()

    class Client:
        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            return httpx.Response(200, text=fixture, request=httpx.Request("GET", url))

    adapter = AdditionalStationAdapter(
        _source("ggn", "https://www.ggn.or.kr/sub/content.do?cno=14&menuNo=94"), client=Client()
    )
    result = asyncio.run(adapter.collect(CollectionWindow(REGIONAL_DAY, REGIONAL_DAY)))

    assert {row.channel_id for row in result.schedules} == {"ggn.main.main"}
    assert result.schedules[0].title == "GGN뉴스"
    assert all(row.confidence == pytest.approx(0.7) for row in result.schedules)


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
