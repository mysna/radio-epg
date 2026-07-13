from datetime import date
from pathlib import Path

from radio_epg.adapters.community import (
    SourcedScheduleRow,
    load_community_mapping,
    merge_schedule_rows,
)
from radio_epg.adapters.html_schedule import ScheduleRow
from radio_epg.coverage import build_coverage

ROOT = Path(__file__).parents[2]
MAPPING = ROOT / "data" / "mappings" / "community.json"


def _row(event_id: str, start: str, end: str, *, confidence: float = 1) -> ScheduleRow:
    return ScheduleRow(
        upstream_id=event_id,
        broadcast_date=date(2026, 7, 13),
        start=start,
        end=end,
        title=event_id,
        confidence=confidence,
    )


def test_mapping_accounts_for_all_23_community_identities() -> None:
    mapping = load_community_mapping(MAPPING)
    community = tuple(item for item in mapping.channels if item.family == "community")

    assert len(community) == 23
    assert all(item.status in {"enabled", "unsupported"} for item in community)
    assert all(item.primary_source.startswith("https://") for item in community)


def test_official_rows_win_and_fallback_only_fills_uncovered_ranges() -> None:
    official = [SourcedScheduleRow(_row("official", "05:00", "07:00"), "official")]
    fallback = [
        SourcedScheduleRow(_row("overlap", "06:00", "08:00", confidence=0.7), "wiki"),
        SourcedScheduleRow(_row("gap", "07:00", "09:00", confidence=0.7), "inferred"),
    ]

    merged = merge_schedule_rows(official, fallback)

    assert [item.row.upstream_id for item in merged] == ["official", "gap"]
    assert merged[1].source_kind == "inferred"


def test_task_12_mapping_completes_all_194_catalog_identities() -> None:
    report = build_coverage(ROOT, require_accounted=True)

    assert report.accounted_count == report.catalog_count == 194
    assert report.pending_count == 0
