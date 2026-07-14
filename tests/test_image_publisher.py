import asyncio
import base64
import json
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import httpx
from PIL import Image

from radio_epg.image_publisher import ImagePublishSummary, publish_images
from radio_epg.images.download import DownloadedImage, ImageDownloadError
from radio_epg.models import ImageCandidate


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 4), "red").save(output, format="PNG")
    return output.getvalue()


def _candidate(entity_id: str = "kbs:news") -> ImageCandidate:
    return ImageCandidate(
        entity_type="program",
        entity_id=entity_id,
        source_url="https://images.example.test/news.png",
        source_page_url="https://schedule.example.test/news",
        rights_status="unknown",
    )


class FakeDownloader:
    def __init__(self, content: bytes, *, failing_ids: set[str] | None = None) -> None:
        self.content = content
        self.failing_ids = failing_ids or set()
        self.urls: list[str] = []

    async def __aenter__(self) -> "FakeDownloader":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def download(self, url: str) -> DownloadedImage:
        self.urls.append(url)
        if url in self.failing_ids:
            raise ImageDownloadError("failed")
        return DownloadedImage(
            content=self.content,
            mime_type="image/png",
            final_url=url,
            width=8,
            height=4,
        )


def test_publish_images_uploads_three_authenticated_variants() -> None:
    requests: list[dict[str, Any]] = []
    authorizations: list[str] = []
    downloader = FakeDownloader(_png())

    def handler(request: httpx.Request) -> httpx.Response:
        authorizations.append(request.headers["Authorization"])
        requests.append(json.loads(request.read()))
        return httpx.Response(201, json={"status": "stored"})

    summary = asyncio.run(
        publish_images(
            (_candidate(),),
            source_id="kbs",
            base_url="https://epg.example.test",
            token="secret-token",
            downloader=downloader,
            transport=httpx.MockTransport(handler),
            now=lambda: datetime(2026, 7, 14, tzinfo=UTC),
        )
    )

    assert summary == ImagePublishSummary(1, 3, 0)
    assert authorizations == ["Bearer secret-token"] * 3
    assert {request["variant"]["name"] for request in requests} == {
        "small",
        "medium",
        "original",
    }
    assert all(request["asset"]["source_id"] == "kbs" for request in requests)
    assert all(request["asset"]["entity_id"] == "kbs:news" for request in requests)
    assert all(request["asset"]["verified_at"] == "2026-07-14T00:00:00Z" for request in requests)
    assert all(
        base64.b64decode(request["variant"]["content_base64"])
        for request in requests
    )
    assert len({request["asset"]["content_hash"] for request in requests}) == 1


def test_publish_images_links_identical_content_to_each_entity() -> None:
    entity_ids: list[str] = []
    hashes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        entity_ids.append(payload["asset"]["entity_id"])
        hashes.append(payload["asset"]["content_hash"])
        return httpx.Response(201, json={"status": "stored"})

    summary = asyncio.run(
        publish_images(
            (_candidate("program:one"), _candidate("program:two")),
            source_id="kbs",
            base_url="https://epg.example.test",
            token="token",
            downloader=FakeDownloader(_png()),
            transport=httpx.MockTransport(handler),
        )
    )

    assert summary == ImagePublishSummary(2, 6, 0)
    assert set(entity_ids) == {"program:one", "program:two"}
    assert len(set(hashes)) == 1


def test_publish_images_retries_transient_api_failures() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503 if attempts == 1 else 201, json={"status": "stored"})

    summary = asyncio.run(
        publish_images(
            (_candidate(),),
            source_id="kbs",
            base_url="https://epg.example.test",
            token="token",
            downloader=FakeDownloader(_png()),
            transport=httpx.MockTransport(handler),
            retry_base_delay=0,
        )
    )

    assert summary == ImagePublishSummary(1, 3, 0)
    assert attempts == 4


def test_publish_images_skips_failed_candidate_and_continues() -> None:
    failed_url = "https://images.example.test/failed.png"
    failed = _candidate("program:failed").model_copy(update={"source_url": failed_url})
    stored_entities: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        stored_entities.append(json.loads(request.read())["asset"]["entity_id"])
        return httpx.Response(201, json={"status": "stored"})

    summary = asyncio.run(
        publish_images(
            (failed, _candidate("program:ok")),
            source_id="kbs",
            base_url="https://epg.example.test",
            token="token",
            downloader=FakeDownloader(_png(), failing_ids={failed_url}),
            transport=httpx.MockTransport(handler),
        )
    )

    assert summary == ImagePublishSummary(2, 3, 1)
    assert set(stored_entities) == {"program:ok"}


def test_publish_images_accepts_an_empty_candidate_tuple() -> None:
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(201)

    summary = asyncio.run(
        publish_images(
            (),
            source_id="kbs",
            base_url="https://epg.example.test",
            token="token",
            transport=httpx.MockTransport(handler),
        )
    )

    assert summary == ImagePublishSummary(0, 0, 0)
    assert requests == 0
