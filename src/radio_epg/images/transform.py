"""검증된 이미지를 안전한 PNG variant로 재인코딩한다."""

import hashlib
from dataclasses import dataclass
from io import BytesIO

import cairosvg
from defusedxml import ElementTree
from PIL import Image

from radio_epg.images.download import DownloadedImage


@dataclass(frozen=True, slots=True)
class ImageVariant:
    """R2에 올릴 하나의 고정 variant."""

    name: str
    mime_type: str
    width: int
    height: int
    content: bytes


@dataclass(frozen=True, slots=True)
class TransformedImage:
    """원본 content hash와 재인코딩된 variant 묶음."""

    content_hash: str
    variants: tuple[ImageVariant, ...]


def _open_source(image: DownloadedImage, original_max: int) -> Image.Image:
    if image.mime_type == "image/svg+xml":
        ElementTree.fromstring(image.content)
        width = min(image.width or original_max, original_max)
        height = min(image.height or original_max, original_max)
        png = cairosvg.svg2png(
            bytestring=image.content,
            output_width=width,
            output_height=height,
            unsafe=False,
        )
        with Image.open(BytesIO(png), formats=("PNG",)) as decoded:
            decoded.load()
            return decoded.convert("RGBA")

    with Image.open(BytesIO(image.content), formats=("PNG", "JPEG", "WEBP", "GIF")) as decoded:
        decoded.load()
        source = decoded.convert("RGBA")
    source.thumbnail((original_max, original_max), Image.Resampling.LANCZOS)
    return source


def _variant(source: Image.Image, name: str, maximum: int) -> ImageVariant:
    image = source.copy()
    image.thumbnail((maximum, maximum), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return ImageVariant(
        name=name,
        mime_type="image/png",
        width=image.width,
        height=image.height,
        content=output.getvalue(),
    )


def transform_image(
    image: DownloadedImage,
    *,
    small_max: int = 256,
    medium_max: int = 768,
    original_max: int = 2048,
) -> TransformedImage:
    """aspect ratio와 alpha를 보존하며 small·medium·original PNG를 만든다."""
    if not 0 < small_max <= medium_max <= original_max:
        raise ValueError("image variant dimensions must be positive and ordered")
    source = _open_source(image, original_max)
    variants = (
        _variant(source, "small", small_max),
        _variant(source, "medium", medium_max),
        _variant(source, "original", original_max),
    )
    return TransformedImage(
        content_hash=hashlib.sha256(image.content).hexdigest(),
        variants=variants,
    )


def deduplicate_by_hash(images: tuple[TransformedImage, ...]) -> tuple[TransformedImage, ...]:
    """같은 원본 bytes에서 생성된 변환 결과를 첫 항목 하나로 접는다."""
    unique: dict[str, TransformedImage] = {}
    for image in images:
        unique.setdefault(image.content_hash, image)
    return tuple(unique.values())
