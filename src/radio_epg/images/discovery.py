"""Wikimedia와 HTML page에서 provenance를 가진 이미지 후보를 찾는다."""

from collections.abc import Iterable
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from radio_epg.images.rights import wikimedia_rights
from radio_epg.models import ImageCandidate

EntityType = Literal["broadcaster", "channel", "program"]


def _web_url(value: object, *, base_url: str | None = None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    resolved = urljoin(base_url, value.strip()) if base_url else value.strip()
    parsed = urlparse(resolved)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return resolved


def discover_wikimedia_image(
    payload: dict[str, Any],
    *,
    entity_type: EntityType,
    entity_id: str,
) -> ImageCandidate | None:
    """MediaWiki imageinfo 응답의 첫 유효한 파일과 extmetadata를 보존한다."""
    query = payload.get("query")
    pages = query.get("pages") if isinstance(query, dict) else None
    if not isinstance(pages, dict):
        return None

    for page in pages.values():
        image_info = page.get("imageinfo") if isinstance(page, dict) else None
        if (
            not isinstance(image_info, list)
            or not image_info
            or not isinstance(image_info[0], dict)
        ):
            continue
        info = image_info[0]
        source_url = _web_url(info.get("url"))
        source_page_url = _web_url(info.get("descriptionurl"))
        if source_url is None or source_page_url is None:
            continue
        metadata = info.get("extmetadata")
        rights = wikimedia_rights(metadata if isinstance(metadata, dict) else {})
        return ImageCandidate(
            entity_type=entity_type,
            entity_id=entity_id,
            source_url=source_url,
            source_page_url=source_page_url,
            rights_status=rights.status,
            author=rights.author,
            license=rights.license,
            attribution=rights.attribution,
        )
    return None


def discover_html_image(
    html: str,
    *,
    page_url: str,
    entity_type: EntityType,
    entity_id: str,
) -> ImageCandidate | None:
    """Namuwiki나 공식 HTML의 `og:image`를 unknown-rights 후보로 만든다."""
    soup = BeautifulSoup(html, "html.parser")
    element = soup.find("meta", attrs={"property": "og:image"})
    if element is None:
        element = soup.find("meta", attrs={"name": "og:image"})
    source_url = _web_url(element.get("content") if element else None, base_url=page_url)
    source_page_url = _web_url(page_url)
    if source_url is None or source_page_url is None:
        return None
    return ImageCandidate(
        entity_type=entity_type,
        entity_id=entity_id,
        source_url=source_url,
        source_page_url=source_page_url,
        rights_status="unknown",
    )


def first_discovered_image(
    candidates: Iterable[ImageCandidate | None],
) -> ImageCandidate | None:
    """Wikimedia, Namuwiki, 공식 page 순서로 첫 후보를 선택한다."""
    return next((candidate for candidate in candidates if candidate is not None), None)
