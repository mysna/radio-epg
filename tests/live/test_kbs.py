import os
from datetime import date

import pytest

from radio_epg.adapters.base import CollectionWindow
from radio_epg.adapters.kbs import KbsAdapter
from radio_epg.config import SourceConfig

pytestmark = pytest.mark.skipif(
    os.environ.get("RADIO_EPG_LIVE_TESTS") != "1",
    reason="KBS live probe is opt-in",
)


def test_kbs_weekly_endpoint_live() -> None:
    source = SourceConfig(
        source_id="kbs",
        name="KBS 편성표",
        source_kind="official",
        source_url="https://schedule.kbs.co.kr/",
        priority=100,
        adapter="kbs",
    )
    adapter = KbsAdapter(source)
    today = date.today()

    import asyncio

    result = asyncio.run(adapter.collect(CollectionWindow(today, today)))

    assert result.schedules
