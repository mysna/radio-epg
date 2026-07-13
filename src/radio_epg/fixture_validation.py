"""등록된 mapping과 축소 fixture의 parser 계약 검증."""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from radio_epg.adapters.cbs import parse_cbs_schedule
from radio_epg.adapters.ebs import parse_ebs_schedule
from radio_epg.adapters.html_schedule import catalog_channels, load_channel_mapping
from radio_epg.adapters.kbs import _load_mapping as load_kbs_mapping
from radio_epg.adapters.kbs import _parse_payload as parse_kbs_payload
from radio_epg.adapters.mbc import parse_mbc_schedule
from radio_epg.adapters.sbs import parse_sbs_current_schedule, parse_sbs_schedule
from radio_epg.adapters.tbn import parse_tbn_html, parse_tbn_schedule
from radio_epg.catalog import load_catalog

_ROOT = Path(__file__).parents[2]


@dataclass(frozen=True, slots=True)
class FixtureValidationResult:
    """검증한 mapping과 fixture family 수."""

    mapping_count: int
    fixture_family_count: int


def validate_fixtures(root: Path = _ROOT) -> FixtureValidationResult:
    """KBS와 전국 방송 5개 family의 mapping 및 reduced fixture를 검증한다."""
    mapping_root = root / "data" / "mappings"
    fixture_root = root / "tests" / "fixtures"
    catalog = load_catalog(root / "data" / "radio_channels.json")
    load_kbs_mapping(mapping_root / "kbs.json")
    for family in ("mbc", "sbs", "ebs", "cbs", "tbn"):
        catalog_channels(load_channel_mapping(mapping_root / f"{family}.json"), catalog)

    expected_date = date(2026, 7, 13)
    parse_kbs_payload(json.loads((fixture_root / "kbs" / "weekly.json").read_text()))
    parse_mbc_schedule(
        (fixture_root / "mbc" / "schedule.jsonp").read_text(),
        expected_date=expected_date,
    )
    parse_sbs_schedule(
        json.loads((fixture_root / "sbs" / "schedule.json").read_text()),
        expected_date=expected_date,
    )
    parse_sbs_current_schedule(
        json.loads((fixture_root / "sbs" / "current.json").read_text()),
        expected_date=expected_date,
        today=expected_date,
    )
    parse_ebs_schedule((fixture_root / "ebs" / "fm.html").read_text(), expected_date=expected_date)
    parse_ebs_schedule(
        (fixture_root / "ebs" / "bandi.html").read_text(), expected_date=expected_date
    )
    parse_cbs_schedule(
        (fixture_root / "cbs" / "schedule.html").read_text(), expected_date=expected_date
    )
    parse_tbn_schedule(
        json.loads((fixture_root / "tbn" / "schedule.json").read_text()),
        expected_date=expected_date,
    )
    parse_tbn_html(
        (fixture_root / "tbn" / "schedule.html").read_text(),
        expected_date=date(2026, 7, 14),
        station_code="main",
    )
    return FixtureValidationResult(mapping_count=6, fixture_family_count=6)
