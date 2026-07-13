"""검증된 import batch를 인증된 Worker ingestion API로 전송한다."""

import asyncio
import hashlib
import json
import re
from typing import Any

import httpx

from radio_epg.models import ImportBatch, ScheduleCandidate

_TRANSIENT_STATUSES = {408, 429, 500, 502, 503, 504}
_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=5.0)
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_IMPORT_BYTES = 900_000
_MAX_SCHEDULES = 2_000
_MAX_IDEMPOTENCY_KEY_LENGTH = 200


class PublishError(RuntimeError):
    """배치를 안전하게 게시할 수 없을 때 발생한다."""


def _publish_error(response: httpx.Response) -> PublishError:
    """응답 본문이나 인증 정보를 노출하지 않는 게시 오류를 만든다."""
    message = f"ingestion request failed with HTTP {response.status_code}"
    try:
        payload: object = response.json()
    except ValueError:
        return PublishError(message)
    if not isinstance(payload, dict):
        return PublishError(message)
    error = payload.get("error")
    if not isinstance(error, dict):
        return PublishError(message)
    code = error.get("code")
    if isinstance(code, str) and _ERROR_CODE.fullmatch(code):
        message = f"{message} ({code})"
    return PublishError(message)


def _payload(batch: ImportBatch) -> dict[str, Any]:
    return batch.model_dump(mode="json", exclude={"images"})


def _payload_size(batch: ImportBatch) -> int:
    encoded = json.dumps(_payload(batch), ensure_ascii=False, separators=(",", ":"))
    return len(encoded.encode())


def _part_key(base: str, index: int, total: int) -> str:
    suffix = f":part:{index:04d}-of-{total:04d}"
    if len(base) + len(suffix) <= _MAX_IDEMPOTENCY_KEY_LENGTH:
        return f"{base}{suffix}"
    digest = hashlib.sha256(base.encode()).hexdigest()[:12]
    suffix = f":{digest}{suffix}"
    return f"{base[: _MAX_IDEMPOTENCY_KEY_LENGTH - len(suffix)]}{suffix}"


def _subset_batch(
    batch: ImportBatch,
    schedules: tuple[ScheduleCandidate, ...],
    *,
    idempotency_key: str,
) -> ImportBatch:
    program_ids = {schedule.program_id for schedule in schedules if schedule.program_id is not None}
    return batch.model_copy(
        update={
            "idempotency_key": idempotency_key,
            "programs": tuple(
                program for program in batch.programs if program.program_id in program_ids
            ),
            "schedules": schedules,
            "images": (),
        }
    )


def _partition_batch(batch: ImportBatch) -> tuple[ImportBatch, ...]:
    if len(batch.schedules) <= _MAX_SCHEDULES and _payload_size(batch) <= _MAX_IMPORT_BYTES:
        return (batch,)

    grouped: dict[tuple[str, str, object], list[ScheduleCandidate]] = {}
    for schedule in batch.schedules:
        scope = (schedule.source_id, schedule.channel_id, schedule.broadcast_date)
        grouped.setdefault(scope, []).append(schedule)

    placeholder = _part_key(batch.idempotency_key, 9_999, 9_999)
    partitions: list[tuple[ScheduleCandidate, ...]] = []
    current: tuple[ScheduleCandidate, ...] = ()
    for scope_schedules in grouped.values():
        candidate = (*current, *scope_schedules)
        candidate_batch = _subset_batch(batch, candidate, idempotency_key=placeholder)
        exceeds_limit = (
            len(candidate) > _MAX_SCHEDULES or _payload_size(candidate_batch) > _MAX_IMPORT_BYTES
        )
        if exceeds_limit and current:
            partitions.append(current)
            current = tuple(scope_schedules)
            candidate_batch = _subset_batch(batch, current, idempotency_key=placeholder)
            exceeds_limit = (
                len(current) > _MAX_SCHEDULES or _payload_size(candidate_batch) > _MAX_IMPORT_BYTES
            )
        else:
            current = candidate
        if exceeds_limit:
            raise PublishError("one schedule scope exceeds ingestion limits")
    if current:
        partitions.append(current)

    total = len(partitions)
    return tuple(
        _subset_batch(
            batch,
            schedules,
            idempotency_key=_part_key(batch.idempotency_key, index, total),
        )
        for index, schedules in enumerate(partitions, start=1)
    )


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
    batches = _partition_batch(batch)
    results: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT, transport=transport) as client:
        for part in batches:
            payload = _payload(part)
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
                    raise _publish_error(response)

                try:
                    result = response.json()
                except ValueError as error:
                    raise PublishError("ingestion response must be a JSON object") from error
                if not isinstance(result, dict):
                    raise PublishError("ingestion response must be a JSON object")
                results.append(result)
                break

    if len(results) == 1:
        return results[0]
    status = (
        "already_applied"
        if all(result.get("status") == "already_applied" for result in results)
        else "applied"
    )
    return {"status": status, "part_count": len(results)}
