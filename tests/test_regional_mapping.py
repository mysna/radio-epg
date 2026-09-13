import asyncio
from pathlib import Path

import httpx
import pytest

from radio_epg.adapters.base import CollectionWindow
from radio_epg.adapters.cbs_regional import CbsRegionalAdapter
from radio_epg.adapters.mbc_regional import (
    MbcBusanAdapter,
    MbcPohangAdapter,
    MbcRegionalAdapter,
    MbcWonjuAdapter,
)
from radio_epg.adapters.sbs_regional import KnnAdapter, TbcAdapter
from radio_epg.config import SourceConfig
from radio_epg.regional_mapping import _BROWSER_UA_SOURCE_IDS, _INSECURE_SOURCE_IDS

FIXTURES = Path(__file__).parent / "fixtures" / "additional"
REGIONAL_DAY = "2026-09-05"


def _source(source_id: str, adapter: str, url: str) -> SourceConfig:
    return SourceConfig(
        source_id=source_id,
        name=source_id,
        source_kind="official",
        source_url=url,
        priority=100,
        adapter=adapter,
    )


def _window() -> CollectionWindow:
    from datetime import date

    day = date.fromisoformat(REGIONAL_DAY)
    return CollectionWindow(day, day)


def test_mbc_regional_collects_every_configured_station_as_one_source() -> None:
    am_fixture = (FIXTURES / "mbc-gangneung-am.html").read_text()
    fm_fixture = (FIXTURES / "mbc-gangneung-fm.html").read_text()
    shared_cms_fixture = (FIXTURES / "mbc-daegu.html").read_text()

    class Client:
        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            if "g=am" in url:
                fixture = am_fixture
            elif "g=fm" in url:
                fixture = fm_fixture
            else:
                fixture = shared_cms_fixture
            return httpx.Response(200, text=fixture, request=httpx.Request("GET", url))

    adapter = MbcRegionalAdapter(
        _source("mbc-regional", "mbc_regional", "https://www.mbceg.co.kr/schedule/cp_depart"),
        client=Client(),
    )
    result = asyncio.run(adapter.collect(_window()))

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
    }


def test_mbc_wonju_is_a_separate_source_from_the_rest_of_regional_mbc() -> None:
    wonju_fixture = (FIXTURES / "wonju-mbc-fm4u.html").read_text()

    class Client:
        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            return httpx.Response(200, text=wonju_fixture, request=httpx.Request("GET", url))

    adapter = MbcWonjuAdapter(
        _source("mbc-wonju", "mbc_wonju", "https://www.wjmbc.co.kr/radio/am.html"),
        client=Client(),
    )
    result = asyncio.run(adapter.collect(_window()))

    channel_ids = {row.channel_id for row in result.schedules}
    assert channel_ids == {"mbc.sfm.wonju", "mbc.fm4u.wonju"}


def test_mbc_pohang_is_a_separate_source_from_the_rest_of_regional_mbc() -> None:
    am_fixture = (FIXTURES / "mbc-pohang-am.html").read_text()
    fm_fixture = (FIXTURES / "mbc-pohang-fm.html").read_text()

    class Client:
        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            fixture = fm_fixture if "scheduler_fm4u" in url else am_fixture
            return httpx.Response(200, text=fixture, request=httpx.Request("GET", url))

    adapter = MbcPohangAdapter(
        _source(
            "mbc-pohang", "mbc_pohang", "https://www.phmbc.co.kr/www/support/scheduler/scheduler_fm"
        ),
        client=Client(),
    )
    from datetime import date

    # 두 fixture는 실제로 캡처한 서로 다른 날짜를 대표한다(표준FM=09-12,
    # FM4U=09-13) - phmbc()가 "on" 마커로 날짜 일치를 검증하므로 window를
    # 이틀로 잡아야 둘 다 잡힌다.
    result = asyncio.run(adapter.collect(CollectionWindow(date(2026, 9, 12), date(2026, 9, 13))))

    channel_ids = {row.channel_id for row in result.schedules}
    assert channel_ids == {"mbc.sfm.pohang", "mbc.fm4u.pohang"}


def test_mbc_busan_fetches_the_weekly_pdf_link_from_the_schedule_page_first() -> None:
    sfm_page = (FIXTURES / "busan-mbc-sfm-page.html").read_text()
    fm4u_page = (FIXTURES / "busan-mbc-fm4u-page.html").read_text()
    sfm_pdf = (FIXTURES / "busan-mbc-sfm.pdf").read_bytes()
    fm4u_pdf = (FIXTURES / "busan-mbc-fm4u.pdf").read_bytes()
    requested_urls: list[str] = []

    class Client:
        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            requested_urls.append(url)
            if url.endswith("oar05.asp"):
                return httpx.Response(200, text=sfm_page, request=httpx.Request("GET", url))
            if url.endswith("oar06.asp"):
                return httpx.Response(200, text=fm4u_page, request=httpx.Request("GET", url))
            if "sfm-test.pdf" in url:
                return httpx.Response(200, content=sfm_pdf, request=httpx.Request("GET", url))
            if "fm4u-test.pdf" in url:
                return httpx.Response(200, content=fm4u_pdf, request=httpx.Request("GET", url))
            raise AssertionError(f"unexpected url: {url}")

    adapter = MbcBusanAdapter(
        _source("mbc-busan", "mbc_busan", "https://busanmbc.co.kr/06_oar/oar05.asp"),
        client=Client(),
    )
    from datetime import date

    day = date(2026, 9, 14)
    result = asyncio.run(adapter.collect(CollectionWindow(day, day)))

    channel_ids = {row.channel_id for row in result.schedules}
    assert channel_ids == {"mbc.sfm.busan", "mbc.fm4u.busan"}
    # 페이지를 먼저 읽어 그 안의 PDF 링크를 알아낸 뒤에야 실제 PDF를 받아야 한다.
    assert any(url.endswith("oar05.asp") for url in requested_urls)
    assert any("sfm-test.pdf" in url for url in requested_urls)


def test_mbc_pohang_and_mbc_busan_are_the_only_sources_with_tls_verification_disabled() -> None:
    assert {"mbc-pohang", "mbc-busan"} == _INSECURE_SOURCE_IDS


def test_mbc_wonju_is_the_only_source_using_a_browser_user_agent() -> None:
    assert {"mbc-wonju"} == _BROWSER_UA_SOURCE_IDS


def test_cbs_regional_collects_every_configured_station_as_one_source() -> None:
    fixture = (FIXTURES / "cbs-regional-busan.json").read_text()
    youngdong_fixture = (FIXTURES / "cbs-youngdong.html").read_text()

    class Client:
        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            body = youngdong_fixture if "yd.local.cbs.co.kr" in url else fixture
            return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    adapter = CbsRegionalAdapter(
        _source(
            "cbs-regional",
            "cbs_regional",
            "https://appradio.cbs.co.kr/51/GetInfo_ProgSchedule.asp",
        ),
        client=Client(),
    )
    result = asyncio.run(adapter.collect(_window()))

    channel_ids = {row.channel_id for row in result.schedules}
    assert "cbs.sfm.busan" in channel_ids
    assert "cbs.mfm.busan" in channel_ids
    assert "cbs.sfm.gwangju" in channel_ids
    assert "cbs.mfm.gwangju" in channel_ids
    assert "cbs.sfm.pohang" in channel_ids
    assert "cbs.sfm.ulsan" in channel_ids
    assert "cbs.sfm.daegu" in channel_ids
    assert "cbs.sfm.chuncheon" in channel_ids
    assert "cbs.sfm.youngdong" in channel_ids


def test_tbc_is_its_own_broadcaster_source_not_a_shared_sbs_affiliate_bucket() -> None:
    fixture = (FIXTURES / "sbs-affiliate-tbc-daegu.html").read_text()

    class Client:
        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            return httpx.Response(200, text=fixture, request=httpx.Request("GET", url))

    adapter = TbcAdapter(_source("tbc", "tbc", "https://tbc.co.kr/schedule/"), client=Client())
    result = asyncio.run(adapter.collect(_window()))

    assert {row.channel_id for row in result.schedules} == {"sbs.powerfm.daegu"}


def test_knn_collects_both_channels_from_the_shared_response() -> None:
    fixture = (FIXTURES / "sbs-knn-busan.html").read_text()

    class Client:
        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            return httpx.Response(200, text=fixture, request=httpx.Request("GET", url))

    adapter = KnnAdapter(
        _source("knn", "knn", "https://www.knn.co.kr/schedule/schedule.do"), client=Client()
    )
    result = asyncio.run(adapter.collect(_window()))

    assert {row.channel_id for row in result.schedules} == {
        "sbs.powerfm.busan",
        "sbs.lovefm.busan",
    }


def test_unsupported_channels_are_not_collected() -> None:
    with pytest.raises(Exception, match="no enabled channels"):

        class NeverCalledClient:
            async def get(self, url: str, **_kwargs: object) -> httpx.Response:
                raise AssertionError("unsupported family should never fetch")

        from radio_epg.regional_mapping import ConfiguredRegionalAdapter

        class GhostAdapter(ConfiguredRegionalAdapter):
            family = "does-not-exist"

        adapter = GhostAdapter(
            _source("ghost", "ghost", "https://example.test"), client=NeverCalledClient()
        )
        asyncio.run(adapter.collect(_window()))
