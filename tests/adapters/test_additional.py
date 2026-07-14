from datetime import date
from pathlib import Path

import pytest

from radio_epg.adapters.additional import parse_station_schedule

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
