"""수집된 이미지 후보를 검증·변환하여 Worker 이미지 API에 게시한다."""

import asyncio
import base64
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from radio_epg.images.download import SafeImageDownloader
from radio_epg.images.transform import ImageVariant, transform_image
from radio_epg.models import ImageCandidate

_TRANSIENT_STATUSES = {408, 429, 500, 502, 503, 504}
_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=5.0)


class ImagePublishError(RuntimeError):
    """이미지 variant를 안전하게 게시할 수 없을 때 발생한다."""


@dataclass(frozen=True, slots=True)
class ImagePublishSummary:
    """비밀정보나 원본 URL을 포함하지 않는 이미지 게시 결과."""

    candidate_count: int
    uploaded_variant_count: int
    failed_candidate_count: int


def _hosts(candidates: tuple[ImageCandidate, ...]) -> set[str]:
    hosts: set[str] = set()
    for candidate in candidates:
        parsed = httpx.URL(candidate.source_url)
        if parsed.scheme == "https" and parsed.host:
            hosts.add(parsed.host)
    return hosts


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _payload(
    candidate: ImageCandidate,
    variant: ImageVariant,
    *,
    source_id: str,
    content_hash: str,
    verified_at: datetime,
) -> dict[str, Any]:
    return {
        "asset": {
            "source_id": source_id,
            "entity_type": candidate.entity_type,
            "entity_id": candidate.entity_id,
            "content_hash": content_hash,
            "rights_status": candidate.rights_status,
            "source_url": candidate.source_url,
            "source_page_url": candidate.source_page_url,
            "author": candidate.author,
            "license": candidate.license,
            "attribution": candidate.attribution,
            "verified_at": _timestamp(verified_at),
        },
        "variant": {
            "name": variant.name,
            "mime_type": variant.mime_type,
            "width": variant.width,
            "height": variant.height,
            "byte_size": len(variant.content),
            "content_base64": base64.b64encode(variant.content).decode("ascii"),
        },
    }


async def _post_variant(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
    *,
    max_retries: int,
    retry_base_delay: float,
) -> None:
    for attempt in range(max_retries + 1):
        try:
            response = await client.post("/v1/admin/images", json=payload)
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            if attempt >= max_retries:
                raise ImagePublishError("image ingestion request failed") from error
        else:
            if response.status_code not in _TRANSIENT_STATUSES:
                if response.is_error:
                    raise ImagePublishError(
                        f"image ingestion request failed with HTTP {response.status_code}"
                    )
                return
            if attempt >= max_retries:
                raise ImagePublishError(
                    f"image ingestion request failed with HTTP {response.status_code}"
                )
        await asyncio.sleep(retry_base_delay * (2**attempt))


async def publish_images(
    candidates: tuple[ImageCandidate, ...],
    *,
    source_id: str,
    base_url: str,
    token: str,
    max_retries: int = 2,
    retry_base_delay: float = 0.25,
    downloader: Any | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ImagePublishSummary:
    """후보별 실패를 격리하며 이미지 variant를 전용 API에 게시한다."""
    if not candidates:
        return ImagePublishSummary(0, 0, 0)
    if not source_id or not base_url.strip() or not token:
        raise ValueError("image publication settings must not be empty")
    if max_retries < 0 or retry_base_delay < 0:
        raise ValueError("image publication retry settings must not be negative")

    allowed_hosts = _hosts(candidates)
    if downloader is None and not allowed_hosts:
        return ImagePublishSummary(len(candidates), 0, len(candidates))
    image_downloader = downloader or SafeImageDownloader(allowed_hosts)
    uploaded = 0
    failed = 0
    headers = {"Authorization": f"Bearer {token}"}
    async with image_downloader, httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers=headers,
        timeout=_TIMEOUT,
        transport=transport,
    ) as client:
        for candidate in candidates:
            try:
                downloaded = await image_downloader.download(candidate.source_url)
                transformed = transform_image(downloaded)
                verified_at = now()
                for variant in transformed.variants:
                    await _post_variant(
                        client,
                        _payload(
                            candidate,
                            variant,
                            source_id=source_id,
                            content_hash=transformed.content_hash,
                            verified_at=verified_at,
                        ),
                        max_retries=max_retries,
                        retry_base_delay=retry_base_delay,
                    )
                    uploaded += 1
            except Exception:  # 후보 하나의 실패가 편성이나 다른 후보를 막지 않는다.
                failed += 1

    return ImagePublishSummary(len(candidates), uploaded, failed)
