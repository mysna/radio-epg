import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from radio_epg.adapters.base import CollectionWindow, ScheduleAdapter
from radio_epg.config import CollectorSettings, SourceConfig, load_sources
from radio_epg.models import AdapterResult
from radio_epg.registry import AdapterRegistry, default_registry


class FakeAdapter:
    source: SourceConfig

    def __init__(self, source: SourceConfig) -> None:
        self.source = source

    async def collect(self, window: CollectionWindow) -> AdapterResult:
        del window
        raise NotImplementedError


def fake_adapter_factory(source: SourceConfig) -> ScheduleAdapter:
    return FakeAdapter(source)


def _source(source_id: str, *, enabled: bool = True) -> SourceConfig:
    return SourceConfig(
        source_id=source_id,
        name=f"{source_id.upper()} 편성표",
        source_kind="official",
        source_url=f"https://{source_id}.example.test/",
        priority=100,
        adapter="fake",
        enabled=enabled,
    )


def test_registry_builds_selected_enabled_adapters() -> None:
    registry = AdapterRegistry()
    registry.register("fake", fake_adapter_factory)

    adapters = registry.build((_source("kbs"), _source("mbc"), _source("off", enabled=False)))
    selected = registry.build((_source("kbs"), _source("mbc")), source_ids={"mbc"})

    assert [adapter.source.source_id for adapter in adapters] == ["kbs", "mbc"]
    assert [adapter.source.source_id for adapter in selected] == ["mbc"]


def test_registry_rejects_unknown_adapter_names() -> None:
    registry = AdapterRegistry()

    with pytest.raises(LookupError, match="missing"):
        registry.build((_source("kbs").model_copy(update={"adapter": "missing"}),))


def test_source_file_is_strict_and_credentials_come_only_from_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "sources.json"
    source_path.write_text(
        json.dumps([_source("kbs").model_dump() | {"token": "must-not-live-here"}]),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_sources(source_path)

    monkeypatch.setenv("EPG_API_BASE_URL", "https://epg.example.test")
    monkeypatch.setenv("EPG_INGEST_TOKEN", "environment-secret")
    settings = CollectorSettings.from_env()

    assert settings.api_base_url == "https://epg.example.test"
    assert settings.ingest_token == "environment-secret"


def test_default_registry_builds_all_enabled_national_sources() -> None:
    root = Path(__file__).parents[1]
    sources = load_sources(root / "data" / "sources.json")

    adapters = default_registry().build(sources)

    assert [adapter.source.source_id for adapter in adapters] == [
        "kbs",
        "mbc",
        "sbs",
        "ebs",
        "cbs",
        "tbn",
        "obs",
        "ifm",
        "ytn",
        "tbs",
        "febc-seoul",
        "cpbc",
        "wbs",
        "gugak",
    ]


def test_additional_official_schedule_sources_are_registered_but_not_enabled_without_fixtures() -> (
    None
):
    root = Path(__file__).parents[1]
    sources = {item.source_id: item for item in load_sources(root / "data" / "sources.json")}
    expected = {
        "obs": "https://www.obs.co.kr/schedule/?type=radio",
        "ifm": "https://www.ifm.kr/schedule",
        "ytn": "https://radio.ytn.co.kr/schedule/daily.php",
        "tbs": "https://tbs.seoul.kr/fm/schedule.do",
        "febc-seoul": "https://seoul.febc.net/radio/schedule",
        "bbs": "https://www.bbs.or.kr/HOME2/?ACT=SCHEDULE",
        "cpbc": "https://www.cpbc.co.kr/schedule.html?channel=radio",
        "wbs": "https://wbsi.kr/schedule_radio.php",
        "kfn": "https://radio.dema.mil.kr/web/radio/timetable.do",
        "gugak": "https://www.igbf.kr/gugak_web/?sub_num=786",
        "afn-humphreys": "https://myafn.dodmedia.osd.mil/Radio.aspx",
    }

    assert {source_id: sources[source_id].source_url for source_id in expected} == expected
    disabled = {"bbs", "kfn", "afn-humphreys"}
    assert all(not sources[source_id].enabled for source_id in disabled)
    assert all(sources[source_id].enabled for source_id in expected.keys() - disabled)
