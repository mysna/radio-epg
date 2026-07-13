import asyncio

import httpx

from radio_epg.http import PoliteHttpClient


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.value += delay


def test_http_client_sets_identity_timeouts_and_conditional_headers() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["user_agent"] = request.headers["User-Agent"]
        observed["etag"] = request.headers["If-None-Match"]
        observed["modified"] = request.headers["If-Modified-Since"]
        observed["timeout"] = request.extensions["timeout"]
        return httpx.Response(200, json={"ok": True})

    async def scenario() -> None:
        async with PoliteHttpClient(
            transport=httpx.MockTransport(handler),
            per_host_delay=0,
        ) as client:
            await client.get(
                "https://schedule.example.test/weekly",
                etag='"schedule-v1"',
                last_modified="Mon, 13 Jul 2026 00:00:00 GMT",
            )

    asyncio.run(scenario())

    assert str(observed["user_agent"]).startswith("radio-epg/0.1")
    assert observed["etag"] == '"schedule-v1"'
    assert observed["modified"] == "Mon, 13 Jul 2026 00:00:00 GMT"
    assert observed["timeout"] == {
        "connect": 5.0,
        "read": 20.0,
        "write": 20.0,
        "pool": 5.0,
    }


def test_http_client_applies_delay_only_between_requests_to_the_same_host() -> None:
    clock = FakeClock()

    async def scenario() -> None:
        async with PoliteHttpClient(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200)),
            per_host_delay=1.5,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        ) as client:
            await client.get("https://a.example.test/first")
            await client.get("https://b.example.test/first")
            await client.get("https://a.example.test/second")

    asyncio.run(scenario())

    assert clock.sleeps == [1.5]


def test_http_client_retries_transient_failures_with_a_bounded_backoff() -> None:
    clock = FakeClock()
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    async def scenario() -> httpx.Response:
        async with PoliteHttpClient(
            transport=httpx.MockTransport(handler),
            per_host_delay=0,
            max_retries=2,
            retry_base_delay=0.25,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        ) as client:
            return await client.get("https://schedule.example.test/weekly")

    response = asyncio.run(scenario())

    assert response.status_code == 200
    assert attempts == 3
    assert clock.sleeps == [0.25, 0.5]
