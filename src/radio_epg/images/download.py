"""allowlist와 크기 제한을 적용하여 외부 이미지를 안전하게 내려받는다."""

import warnings
from dataclasses import dataclass
from io import BytesIO

import httpx
from defusedxml import ElementTree
from PIL import Image, UnidentifiedImageError


class ImageDownloadError(ValueError):
    """외부 이미지가 안전한 download 계약을 충족하지 않을 때 발생한다."""


@dataclass(frozen=True, slots=True)
class DownloadedImage:
    """signature와 decode 크기가 확인된 원본 이미지."""

    content: bytes
    mime_type: str
    final_url: str
    width: int | None
    height: int | None


def _sniff_mime(content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    stripped = content.lstrip(b"\xef\xbb\xbf\x00\t\r\n ")
    if stripped.startswith((b"<svg", b"<?xml")):
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError as error:
            raise ImageDownloadError("invalid SVG image format") from error
        if root.tag.rsplit("}", 1)[-1] == "svg":
            return "image/svg+xml"
    raise ImageDownloadError("unsupported image format")


def _svg_dimensions(content: bytes) -> tuple[int | None, int | None]:
    root = ElementTree.fromstring(content)

    def dimension(name: str) -> int | None:
        value = root.attrib.get(name, "")
        numeric = value.removesuffix("px")
        try:
            parsed = float(numeric)
        except ValueError:
            return None
        return round(parsed) if parsed > 0 else None

    width, height = dimension("width"), dimension("height")
    view_box = root.attrib.get("viewBox", "").replace(",", " ").split()
    if len(view_box) != 4:
        return width, height
    try:
        view_width, view_height = float(view_box[2]), float(view_box[3])
    except ValueError:
        return width, height
    if view_width <= 0 or view_height <= 0:
        return width, height
    if width is None and height is None:
        return round(view_width), round(view_height)
    if width is None and height is not None:
        width = round(height * view_width / view_height)
    if height is None and width is not None:
        height = round(width * view_height / view_width)
    return width, height


def _raster_dimensions(content: bytes, max_pixels: int) -> tuple[int, int]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content), formats=("PNG", "JPEG", "WEBP", "GIF")) as image:
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > max_pixels:
                    raise ImageDownloadError("image exceeds decompressed pixel limit")
                image.load()
                return width, height
    except ImageDownloadError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ImageDownloadError("image exceeds decompressed pixel limit") from error
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ImageDownloadError("invalid raster image format") from error


class SafeImageDownloader:
    """매 redirect마다 exact host를 검사하고 byte·pixel cap을 적용한다."""

    def __init__(
        self,
        allowed_hosts: set[str],
        *,
        max_bytes: int = 5_000_000,
        max_pixels: int = 16_000_000,
        max_redirects: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not allowed_hosts or max_bytes <= 0 or max_pixels <= 0 or max_redirects < 0:
            raise ValueError("image download limits and allowlist must be valid")
        self._allowed_hosts = {host.lower() for host in allowed_hosts}
        self._max_bytes = max_bytes
        self._max_pixels = max_pixels
        self._max_redirects = max_redirects
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=5.0),
            follow_redirects=False,
            transport=transport,
        )

    async def __aenter__(self) -> "SafeImageDownloader":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self._client.aclose()

    def _validate_url(self, url: str) -> httpx.URL:
        parsed = httpx.URL(url)
        if parsed.scheme != "https" or parsed.host is None:
            raise ImageDownloadError("image URL must use HTTPS with a host")
        if parsed.host.lower() not in self._allowed_hosts:
            raise ImageDownloadError("image host is not allowlisted")
        if parsed.userinfo:
            raise ImageDownloadError("image URL must not contain user information")
        return parsed

    async def download(self, url: str) -> DownloadedImage:
        """허용된 URL에서 image bytes를 제한적으로 읽고 decode 크기를 확인한다."""
        current = self._validate_url(url)
        for redirect_count in range(self._max_redirects + 1):
            async with self._client.stream("GET", current) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if location is None or redirect_count >= self._max_redirects:
                        raise ImageDownloadError("image redirect limit exceeded")
                    current = self._validate_url(str(response.url.join(location)))
                    continue
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    raise ImageDownloadError("image request failed") from error

                content_length = response.headers.get("Content-Length")
                if (
                    content_length
                    and content_length.isdigit()
                    and int(content_length) > self._max_bytes
                ):
                    raise ImageDownloadError("image exceeds byte limit")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self._max_bytes:
                        raise ImageDownloadError("image exceeds byte limit")
                    chunks.append(chunk)

            content = b"".join(chunks)
            mime_type = _sniff_mime(content)
            if mime_type == "image/svg+xml":
                width, height = _svg_dimensions(content)
                if width and height and width * height > self._max_pixels:
                    raise ImageDownloadError("image exceeds decompressed pixel limit")
            else:
                width, height = _raster_dimensions(content, self._max_pixels)
            return DownloadedImage(
                content=content,
                mime_type=mime_type,
                final_url=str(current),
                width=width,
                height=height,
            )

        raise ImageDownloadError("image redirect limit exceeded")
