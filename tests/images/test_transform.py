from io import BytesIO

from PIL import Image

from radio_epg.images.download import DownloadedImage
from radio_epg.images.transform import deduplicate_by_hash, transform_image


def _transparent_png() -> bytes:
    output = BytesIO()
    Image.new("RGBA", (40, 20), (255, 0, 0, 0)).save(output, format="PNG")
    return output.getvalue()


def test_transform_reencodes_three_variants_with_aspect_ratio_and_transparency() -> None:
    downloaded = DownloadedImage(
        content=_transparent_png(),
        mime_type="image/png",
        final_url="https://images.example.test/logo.png",
        width=40,
        height=20,
    )

    transformed = transform_image(downloaded, small_max=16, medium_max=32, original_max=64)

    assert [variant.name for variant in transformed.variants] == ["small", "medium", "original"]
    assert [(variant.width, variant.height) for variant in transformed.variants] == [
        (16, 8),
        (32, 16),
        (40, 20),
    ]
    for variant in transformed.variants:
        with Image.open(BytesIO(variant.content)) as image:
            assert image.format == "PNG"
            assert image.mode == "RGBA"
            pixel = image.getpixel((0, 0))
            assert isinstance(pixel, tuple)
            assert pixel[3] == 0


def test_transform_rasterizes_svg_before_serving() -> None:
    svg = b"""<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10">
      <rect width="10" height="10" fill="red"/>
    </svg>"""
    downloaded = DownloadedImage(
        content=svg,
        mime_type="image/svg+xml",
        final_url="https://images.example.test/logo.svg",
        width=20,
        height=10,
    )

    transformed = transform_image(downloaded, small_max=10, medium_max=20, original_max=20)

    assert all(variant.mime_type == "image/png" for variant in transformed.variants)
    assert all(variant.content.startswith(b"\x89PNG\r\n\x1a\n") for variant in transformed.variants)


def test_content_hash_deduplicates_identical_source_images() -> None:
    downloaded = DownloadedImage(
        content=_transparent_png(),
        mime_type="image/png",
        final_url="https://images.example.test/logo.png",
        width=40,
        height=20,
    )
    first = transform_image(downloaded)
    second = transform_image(downloaded)

    assert first.content_hash == second.content_hash
    assert deduplicate_by_hash((first, second)) == (first,)
