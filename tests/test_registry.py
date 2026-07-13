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
    ]
