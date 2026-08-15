"""Pillow-based image conversion (TD-004 §3, §6).

Business-agnostic: pure byte-in/byte-out transforms with no knowledge of
files, storage keys, or upload domain concepts (TD-004's "New Components").
"""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

from shared.image.exceptions import ImageDecodeError


def to_webp(image_bytes: bytes, *, quality: int) -> bytes:
    """Convert an image to WebP, preserving aspect ratio (FR-1)."""
    image = _open(image_bytes)
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="WEBP", quality=quality)
    return buffer.getvalue()


def to_thumbnail(image_bytes: bytes, *, size: tuple[int, int], quality: int) -> bytes:
    """Generate a letterboxed JPEG thumbnail that fits within `size` (FR-2).

    Uses `ImageOps.pad` rather than `Image.thumbnail` so the output is always
    exactly `size`, centered with black letterboxing — "fit, not crop" per
    FR-2's requirement — instead of a variably-sized image that merely fits
    within the bounds.
    """
    image = _open(image_bytes).convert("RGB")
    padded = ImageOps.pad(image, size, color=(0, 0, 0))
    buffer = io.BytesIO()
    padded.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def _open(image_bytes: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
        return image
    except UnidentifiedImageError as exc:
        raise ImageDecodeError(f"Could not decode image: {exc}") from exc
