from datetime import date
from pathlib import Path

import pytest

from radio_epg.adapters.wiki_fallback import WikiFallbackError, parse_wiki_schedule

ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "community" / "wiki.html"


def test_wiki_requires_an_exact_declared_page_and_fresh_revision() -> None:
    rows = parse_wiki_schedule(
        FIXTURE.read_text(),
        page_url="https://ko.wikipedia.org/wiki/마포FM",
        declared_page_url="https://ko.wikipedia.org/wiki/마포FM",
        revision_date=date(2026, 7, 1),
        as_of=date(2026, 7, 13),
        max_age_days=30,
        expected_date=date(2026, 7, 13),
    )

    assert rows["community.mapofm.main"][0].confidence < 1


def test_wiki_rejects_undeclared_and_stale_pages() -> None:
    with pytest.raises(WikiFallbackError, match="stale"):
        parse_wiki_schedule(
            FIXTURE.read_text(),
            page_url="https://ko.wikipedia.org/wiki/마포FM",
            declared_page_url="https://ko.wikipedia.org/wiki/마포FM",
            revision_date=date(2026, 5, 1),
            as_of=date(2026, 7, 13),
            max_age_days=30,
            expected_date=date(2026, 7, 13),
        )
    with pytest.raises(WikiFallbackError, match="declared"):
        parse_wiki_schedule(
            FIXTURE.read_text(),
            page_url="https://example.com/",
            declared_page_url="https://ko.wikipedia.org/wiki/마포FM",
            revision_date=date(2026, 7, 1),
            as_of=date(2026, 7, 13),
            max_age_days=30,
            expected_date=date(2026, 7, 13),
        )
