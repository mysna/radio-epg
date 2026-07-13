"""검증된 import batch를 인증된 Worker ingestion API로 전송한다."""

import asyncio
from typing import Any

import httpx

from radio_epg.models import ImportBatch

_TRANSIENT_STATUSES = {408, 429, 500, 502, 503, 504}
_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=5.0)


class PublishError(RuntimeError):
    """배치를 안전하게 게시할 수 없을 때 발생한다."""


def _publish_error(status_code: int) -> PublishError:
    """응답 본문이나 인증 정보를 노출하지 않는 게시 오류를 만든다."""
    return PublishError(f"ingestion request failed with HTTP {status_code}")


async def publish_batch(
    batch: ImportBatch,
    *,
    base_url: str,
    token: str,
    max_retries: int = 2,
    retry_base_delay: float = 0.25,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """일시적 실패만 제한적으로 재시도하며 batch를 게시한다."""
    if max_retries < 0:
        raise ValueError("max_retries must not be negative")
    if not token:
        raise ValueError("token must not be empty")

    url = f"{base_url.rstrip('/')}/v1/admin/import"
    headers = {"Authorization": f"Bearer {token}"}
    payload = batch.model_dump(mode="json")

    async with httpx.AsyncClient(timeout=_TIMEOUT, transport=transport) as client:
        for attempt in range(max_retries + 1):
            try:
                response = await client.post(url, headers=headers, json=payload)
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                if attempt >= max_retries:
                    message = "ingestion request failed after transient network errors"
                    raise PublishError(message) from error
                await asyncio.sleep(retry_base_delay * (2**attempt))
                continue

            if response.status_code in _TRANSIENT_STATUSES and attempt < max_retries:
                await asyncio.sleep(retry_base_delay * (2**attempt))
                continue
            if response.is_error:
                raise _publish_error(response.status_code)

            try:
                result = response.json()
            except ValueError as error:
                raise PublishError("ingestion response must be a JSON object") from error
            if not isinstance(result, dict):
                raise PublishError("ingestion response must be a JSON object")
            return result

    raise PublishError("ingestion request exhausted its retry budget")
