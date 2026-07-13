import asyncio
from io import BytesIO

import httpx
import pytest
from PIL import Image

from radio_epg.images.download import ImageDownloadError, SafeImageDownloader


def _png(width: int = 2, height: int = 2) -> bytes:
    output = BytesIO()
    Image.new("RGBA", (width, height), (255, 0, 0, 0)).save(output, format="PNG")
    return output.getvalue()


def test_downloader_allowlists_hosts_and_sniffs_mime_from_bytes() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_png(),
            headers={"Content-Type": "application/octet-stream"},
        )

    async def scenario():
        async with SafeImageDownloader(
            {"images.example.test"},
            transport=httpx.MockTransport(handler),
        ) as downloader:
            return await downloader.download("https://images.example.test/logo")

    downloaded = asyncio.run(scenario())

    assert downloaded.mime_type == "image/png"
    assert (downloaded.width, downloaded.height) == (2, 2)


def test_downloader_revalidates_every_redirect_host() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.host)
        return httpx.Response(302, headers={"Location": "https://blocked.example.test/logo.png"})

    async def scenario() -> None:
        async with SafeImageDownloader(
            {"images.example.test"},
            transport=httpx.MockTransport(handler),
        ) as downloader:
            await downloader.download("https://images.example.test/logo")

    with pytest.raises(ImageDownloadError, match="allowlisted"):
        asyncio.run(scenario())

    assert requested == ["images.example.test"]


def test_downloader_rejects_html_masquerading_as_an_image() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<html>not an image</html>",
            headers={"Content-Type": "image/png"},
        )

    async def scenario() -> None:
        async with SafeImageDownloader(
            {"images.example.test"},
            transport=httpx.MockTransport(handler),
        ) as downloader:
            await downloader.download("https://images.example.test/logo.png")

    with pytest.raises(ImageDownloadError, match="image format"):
        asyncio.run(scenario())


def test_downloader_rejects_images_over_the_decompressed_pixel_limit() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_png(11, 11))

    async def scenario() -> None:
        async with SafeImageDownloader(
            {"images.example.test"},
            max_pixels=100,
            transport=httpx.MockTransport(handler),
        ) as downloader:
            await downloader.download("https://images.example.test/large.png")

    with pytest.raises(ImageDownloadError, match="pixel limit"):
        asyncio.run(scenario())


def test_downloader_rejects_images_over_the_compressed_byte_limit() -> None:
    content = _png()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    async def scenario() -> None:
        async with SafeImageDownloader(
            {"images.example.test"},
            max_bytes=len(content) - 1,
            transport=httpx.MockTransport(handler),
        ) as downloader:
            await downloader.download("https://images.example.test/logo.png")

    with pytest.raises(ImageDownloadError, match="byte limit"):
        asyncio.run(scenario())


def test_downloader_uses_svg_viewbox_as_safe_dimensions() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10"></svg>'

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=svg)

    async def scenario():
        async with SafeImageDownloader(
            {"images.example.test"},
            transport=httpx.MockTransport(handler),
        ) as downloader:
            return await downloader.download("https://images.example.test/logo.svg")

    downloaded = asyncio.run(scenario())

    assert (downloaded.width, downloaded.height) == (20, 10)
