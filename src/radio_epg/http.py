"""편성 소스를 위한 timeout, 재시도, host별 지연 HTTP client."""

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx

USER_AGENT = "radio-epg/0.1 (+https://github.com/mysna/radio-epg; schedule collector)"
_TRANSIENT_STATUSES = {408, 429, 500, 502, 503, 504}
_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=5.0)


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
    ) -> None:
        if per_host_delay < 0 or max_retries < 0 or retry_base_delay < 0:
            raise ValueError("HTTP delay and retry settings must not be negative")
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
                    return response
                if attempt >= self._max_retries:
                    response.raise_for_status()

            await self._sleep(self._retry_base_delay * (2**attempt))

        raise RuntimeError("HTTP request exhausted its retry budget")
