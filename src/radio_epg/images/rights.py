"""이미지 출처가 제공한 권리 메타데이터를 보존한다."""

from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup


@dataclass(frozen=True, slots=True)
class ImageRights:
    """자동 법률 판단 없이 원문에서 추출한 권리 정보."""

    status: str
    author: str | None = None
    license: str | None = None
    attribution: str | None = None


def _metadata_text(metadata: dict[str, Any], key: str) -> str | None:
    field = metadata.get(key)
    if not isinstance(field, dict) or not isinstance(field.get("value"), str):
        return None
    text = BeautifulSoup(field["value"], "html.parser").get_text(" ", strip=True)
    return text or None


def wikimedia_rights(metadata: dict[str, Any]) -> ImageRights:
    """Wikimedia extmetadata의 저자·라이선스·표시문을 안전한 text로 바꾼다."""
    author = _metadata_text(metadata, "Artist")
    license_name = _metadata_text(metadata, "LicenseShortName")
    attribution = _metadata_text(metadata, "Credit") or _metadata_text(metadata, "Attribution")
    status = "known" if license_name else "unknown"
    return ImageRights(
        status=status,
        author=author,
        license=license_name,
        attribution=attribution,
    )
