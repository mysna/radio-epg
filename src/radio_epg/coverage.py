"""canonical channel의 source 조사 상태를 결정적으로 집계한다."""

import json
from dataclasses import dataclass
from pathlib import Path

from radio_epg.adapters.community import load_community_mapping
from radio_epg.adapters.html_schedule import load_channel_mapping
from radio_epg.catalog import load_catalog
from radio_epg.regional_mapping import load_regional_mapping, validate_regional_catalog


class CoverageError(ValueError):
    """mapping 누락, 중복 또는 catalog 외 identity가 있을 때 발생한다."""


@dataclass(frozen=True, slots=True)
class CoverageEntry:
    """한 canonical identity의 지원 또는 미지원 상태."""

    channel_id: str
    status: str
    owner: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """전체 catalog 대비 mapping accounting 결과."""

    catalog_count: int
    accounted_count: int
    pending_count: int
    pending_ids: tuple[str, ...]
    entries: tuple[CoverageEntry, ...]


def _national_entries(root: Path) -> list[CoverageEntry]:
    entries: list[CoverageEntry] = []
    kbs = json.loads((root / "data" / "mappings" / "kbs.json").read_text())
    entries.extend(CoverageEntry(item["channel_id"], "enabled", "kbs") for item in kbs["channels"])
    for family in ("mbc", "sbs", "ebs", "cbs", "tbn"):
        mapping = load_channel_mapping(root / "data" / "mappings" / f"{family}.json")
        entries.extend(
            CoverageEntry(item.channel_id, "enabled", family) for item in mapping.channels
        )
        entries.extend(
            CoverageEntry(item.channel_id, "unsupported", family, item.reason)
            for item in mapping.unsupported
        )
    return entries


def _regional_entries(root: Path) -> list[CoverageEntry]:
    mapping_path = root / "data" / "mappings" / "regional.json"
    if not mapping_path.exists():
        return []
    mapping = load_regional_mapping(mapping_path)
    catalog = load_catalog(root / "data" / "radio_channels.json")
    validate_regional_catalog(mapping, catalog)
    return [
        CoverageEntry(item.channel_id, item.status, item.family, item.reason)
        for item in mapping.channels
    ]


def _community_entries(root: Path) -> list[CoverageEntry]:
    path = root / "data" / "mappings" / "community.json"
    if not path.exists():
        return []
    mapping = load_community_mapping(path)
    return [
        CoverageEntry(item.channel_id, item.status, item.family, item.reason)
        for item in mapping.channels
    ]


def build_coverage(root: Path, *, require_accounted: bool = False) -> CoverageReport:
    """모든 mapping을 합쳐 누락과 중복을 검증한다."""
    catalog = load_catalog(root / "data" / "radio_channels.json")
    entries = [*_national_entries(root), *_regional_entries(root), *_community_entries(root)]
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.channel_id] = counts.get(entry.channel_id, 0) + 1
    duplicates = sorted(channel_id for channel_id, count in counts.items() if count != 1)
    if duplicates:
        raise CoverageError(f"duplicate channel ownership: {duplicates!r}")
    unknown = set(counts) - set(catalog.channels)
    if unknown:
        raise CoverageError(f"mapping contains unknown channels: {sorted(unknown)!r}")
    pending = tuple(sorted(set(catalog.channels) - set(counts)))
    if require_accounted:
        allowed_task_12 = all(
            channel_id.startswith(("community.", "afn.")) for channel_id in pending
        )
        community_mapping_exists = (root / "data" / "mappings" / "community.json").exists()
        if pending and (community_mapping_exists or not allowed_task_12):
            raise CoverageError(f"unaccounted catalog channels: {pending!r}")
    ordered_entries = tuple(sorted(entries, key=lambda entry: entry.channel_id))
    return CoverageReport(
        catalog_count=len(catalog.channels),
        accounted_count=len(ordered_entries),
        pending_count=len(pending),
        pending_ids=pending,
        entries=ordered_entries,
    )


def render_coverage_markdown(report: CoverageReport) -> str:
    """coverage 상태를 canonical ID 순서의 Markdown 표로 만든다."""
    lines = [
        "# Radio EPG Source Coverage",
        "",
        f"- Catalog: {report.catalog_count}",
        f"- Accounted: {report.accounted_count}",
        f"- Pending: {report.pending_count}",
        "",
        "| Channel | Status | Owner | Reason |",
        "| --- | --- | --- | --- |",
    ]
    for entry in report.entries:
        lines.append(
            f"| `{entry.channel_id}` | {entry.status} | {entry.owner} | {entry.reason or ''} |"
        )
    for channel_id in report.pending_ids:
        lines.append(f"| `{channel_id}` | pending | Task 12 | |")
    return "\n".join(lines) + "\n"
