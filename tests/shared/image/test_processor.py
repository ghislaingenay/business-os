import io

import pytest
from PIL import Image

from shared.image.exceptions import ImageDecodeError
from shared.image.processor import to_thumbnail, to_webp


def _make_image_bytes(size: tuple[int, int], fmt: str = "JPEG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(255, 0, 0)).save(buffer, format=fmt)
    return buffer.getvalue()


def test_to_webp_produces_valid_webp_image() -> None:
    original = _make_image_bytes((100, 50))

    result = to_webp(original, quality=85)

    image = Image.open(io.BytesIO(result))
    assert image.format == "WEBP"


def test_to_webp_preserves_aspect_ratio() -> None:
    original = _make_image_bytes((200, 100))

    result = to_webp(original, quality=85)

    image = Image.open(io.BytesIO(result))
    assert image.size == (200, 100)


def test_to_webp_raises_on_corrupt_bytes() -> None:
    with pytest.raises(ImageDecodeError):
        to_webp(b"not an image", quality=85)


def test_to_thumbnail_produces_exact_target_size() -> None:
    original = _make_image_bytes((800, 400))

    result = to_thumbnail(original, size=(256, 256), quality=80)

    image = Image.open(io.BytesIO(result))
    assert image.format == "JPEG"
    assert image.size == (256, 256)


def test_to_thumbnail_letterboxes_non_square_source() -> None:
    # A wide source should letterbox top/bottom (black bars) rather than crop.
    original = _make_image_bytes((800, 200))

    result = to_thumbnail(original, size=(256, 256), quality=80)

    image = Image.open(io.BytesIO(result)).convert("RGB")
    assert image.size == (256, 256)
    # Corner pixel falls in the letterbox band for an 800x200 -> 256x256 fit.
    assert image.getpixel((0, 0)) == (0, 0, 0)


def test_to_thumbnail_raises_on_corrupt_bytes() -> None:
    with pytest.raises(ImageDecodeError):
        to_thumbnail(b"not an image", size=(256, 256), quality=80)
