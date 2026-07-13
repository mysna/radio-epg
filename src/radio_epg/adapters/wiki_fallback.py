"""mapping allowlist와 revision freshness를 요구하는 wiki fallback."""

from dataclasses import replace
from datetime import date

from radio_epg.adapters.html_schedule import ScheduleRow, parse_html_schedule


class WikiFallbackError(ValueError):
    """선언되지 않았거나 오래된 wiki page를 거부할 때 발생한다."""


def parse_wiki_schedule(
    text: str,
    *,
    page_url: str,
    declared_page_url: str,
    revision_date: date,
    as_of: date,
    max_age_days: int,
    expected_date: date,
) -> dict[str, tuple[ScheduleRow, ...]]:
    """정확히 선언된 최신 page의 구조화된 편성만 낮은 confidence로 반환한다."""
    if max_age_days < 0:
        raise WikiFallbackError("wiki maximum age must not be negative")
    if page_url != declared_page_url:
        raise WikiFallbackError("wiki page is not the exact declared page")
    age = (as_of - revision_date).days
    if age < 0 or age > max_age_days:
        raise WikiFallbackError("wiki page revision is stale")
    rows = parse_html_schedule(text, expected_date=expected_date)
    if not rows or not all(rows.values()):
        raise WikiFallbackError("wiki schedule is empty")
    return {
        channel_id: tuple(replace(row, confidence=0.65) for row in channel_rows)
        for channel_id, channel_rows in rows.items()
    }
