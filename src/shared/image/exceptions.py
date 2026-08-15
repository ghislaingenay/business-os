"""Exceptions for the image-processing technical capability."""


class ImageDecodeError(Exception):
    """Raised when image bytes can't be decoded (corrupt or unsupported data)."""
