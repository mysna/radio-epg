from datetime import date
from pathlib import Path

from radio_epg.adapters.afn import schedules_for_station
from radio_epg.adapters.community import load_community_mapping
from radio_epg.adapters.html_schedule import ScheduleRow

ROOT = Path(__file__).parents[2]
MAPPING = ROOT / "data" / "mappings" / "community.json"


def _row(event_id: str) -> ScheduleRow:
    return ScheduleRow(
        upstream_id=event_id,
        broadcast_date=date(2026, 7, 13),
        start="05:00",
        end="07:00",
        title=event_id,
    )


def test_mapping_accounts_for_three_afn_identities() -> None:
    mapping = load_community_mapping(MAPPING)

    assert {item.channel_id for item in mapping.channels if item.family == "afn"} == {
        "afn.main.daegu",
        "afn.main.humphreys",
        "afn.main.kunsan",
    }


def test_afn_common_schedule_does_not_claim_unverified_local_inserts() -> None:
    schedules = schedules_for_station(
        common=(_row("eagle"),),
        local_inserts={"afn.main.daegu": (_row("local"),)},
        channel_id="afn.main.daegu",
        local_evidence=False,
    )

    assert [row.upstream_id for row in schedules] == ["eagle"]
