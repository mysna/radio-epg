"""편성 소스를 위한 timeout, 재시도, host별 지연 HTTP client."""

import asyncio
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

import httpx

USER_AGENT = "radio-epg/0.1 (+https://github.com/mysna/radio-epg; schedule collector)"
_TRANSIENT_STATUSES = {408, 429, 500, 502, 503, 504}
_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=5.0)
DUMP_DIR_ENV = "EPG_RESPONSE_DUMP_DIR"
_SLUG_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")
_SLUG_LIMIT = 80
_EXTENSIONS = {
    "application/json": "json",
    "application/xml": "xml",
    "text/html": "html",
    "text/xml": "xml",
    "text/plain": "txt",
    "image/jpeg": "jpg",
    "image/png": "png",
    "application/pdf": "pdf",
}


def dump_dir_from_env(environ: Mapping[str, str] | None = None) -> Path | None:
    """덤프 경로가 설정된 경우에만 응답 본문을 기록한다."""
    values = os.environ if environ is None else environ
    configured = values.get(DUMP_DIR_ENV, "").strip()
    return Path(configured) if configured else None


def _response_filename(sequence: int, url: str, response: httpx.Response) -> str:
    """요청 순서와 URL, content type으로 충돌하지 않는 파일 이름을 만든다."""
    parsed = httpx.URL(url)
    slug = _SLUG_PATTERN.sub("-", f"{parsed.host}{parsed.path}").strip("-")
    media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    extension = _EXTENSIONS.get(media_type, "bin")
    return f"{sequence:03d}-{slug[:_SLUG_LIMIT]}.{extension}"


class PoliteHttpClient:
    """동일 host 요청을 제한하고 일시적 오류만 제한적으로 재시도한다."""

    def __init__(
        self,
        *,
        per_host_delay: float = 1.0,
        max_retries: int = 2,
        retry_base_delay: float = 0.25,
        transport: httpx.AsyncBaseTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        dump_dir: Path | None = None,
    ) -> None:
        if per_host_delay < 0 or max_retries < 0 or retry_base_delay < 0:
            raise ValueError("HTTP delay and retry settings must not be negative")
        self._dump_dir = dump_dir if dump_dir is not None else dump_dir_from_env()
        self._dumped = 0
        self._per_host_delay = per_host_delay
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._monotonic = monotonic
        self._sleep = sleep
        self._last_request: dict[str, float] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=_TIMEOUT,
            transport=transport,
            follow_redirects=False,
        )

    async def __aenter__(self) -> "PoliteHttpClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """연결 pool을 닫는다."""
        await self._client.aclose()

    def _dump(self, url: str, response: httpx.Response) -> None:
        """상류 응답을 그대로 남겨 실패한 수집을 나중에 재현한다."""
        if self._dump_dir is None:
            return
        self._dumped += 1
        self._dump_dir.mkdir(parents=True, exist_ok=True)
        path = self._dump_dir / _response_filename(self._dumped, url, response)
        path.write_bytes(response.content)

    async def _wait_for_host(self, host: str) -> None:
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            if host in self._last_request:
                elapsed = self._monotonic() - self._last_request[host]
                remaining = self._per_host_delay - elapsed
                if remaining > 0:
                    await self._sleep(remaining)
            self._last_request[host] = self._monotonic()

    async def get(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> httpx.Response:
        """조건부 header를 적용하여 GET 요청을 보낸다."""
        headers: dict[str, str] = {}
        if etag is not None:
            headers["If-None-Match"] = etag
        if last_modified is not None:
            headers["If-Modified-Since"] = last_modified

        host = httpx.URL(url).host
        if not host:
            raise ValueError("HTTP URL must include a host")

        for attempt in range(self._max_retries + 1):
            await self._wait_for_host(host)
            try:
                response = await self._client.get(url, headers=headers)
            except httpx.TransportError:
                if attempt >= self._max_retries:
                    raise
            else:
                if response.status_code not in _TRANSIENT_STATUSES:
                    response.raise_for_status()
                    self._dump(url, response)
                    return response
                if attempt >= self._max_retries:
                    response.raise_for_status()

            await self._sleep(self._retry_base_delay * (2**attempt))

        raise RuntimeError("HTTP request exhausted its retry budget")
