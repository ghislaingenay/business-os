"""File validation utilities: size, allowed type, and MIME/extension agreement."""

import mimetypes
import re
import unicodedata
from pathlib import Path

from upload.config import UploadSettings
from upload.exceptions import (
    FileTooLargeError,
    FileTooSmallError,
    InvalidFileTypeError,
    MimeMismatchError,
)

_FALLBACK_FILENAME = "upload"


def sanitize_filename(filename: str) -> str:
    """Return a safe filename, falling back to a default if the input is empty."""
    filename = Path(filename).name

    # Normalize Unicode characters to standard ASCII forms
    filename = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")

    # Whitelist: keep only alphanumeric characters, dashes, underscores, periods, and spaces
    filename = re.sub(r"[^a-zA-Z0-9\s\-_.]", "", filename)

    # Remove leading/trailing whitespace or periods
    filename = filename.strip(" .")

    # Provide a deterministic fallback if the filename ends up completely empty
    if not filename:
        filename = _FALLBACK_FILENAME

    # Truncate to a conservative safe length (typical filesystem limit is 255 bytes)
    return filename[:200]


class UploadValidator:
    """Validates file size, allowed MIME type, and MIME/extension agreement.

    Size direction (too large vs. too small) is checked against
    `settings.max_small_file_size`, but *which* boundary applies depends on
    the upload path — callers pick `validate_for_mediated_upload` or
    `validate_for_presigned_upload` rather than a single ambiguous `validate`.
    """

    def __init__(self, settings: UploadSettings) -> None:
        self.settings = settings

    def validate_for_mediated_upload(self, filename: str, size: int, mime_type: str) -> None:
        if size > self.settings.max_small_file_size:
            raise FileTooLargeError(size, self.settings.max_small_file_size)
        self._validate_type_and_mime(filename, mime_type)

    def validate_for_presigned_upload(self, filename: str, size: int, mime_type: str) -> None:
        if size <= self.settings.max_small_file_size:
            raise FileTooSmallError(size, self.settings.max_small_file_size)
        self._validate_type_and_mime(filename, mime_type)

    def _validate_type_and_mime(self, filename: str, mime_type: str) -> None:
        if mime_type not in self.settings.allowed_file_types:
            raise InvalidFileTypeError(mime_type, self.settings.allowed_file_types)

        guessed_mime_type, _ = mimetypes.guess_type(filename)
        if guessed_mime_type is not None and guessed_mime_type != mime_type:
            raise MimeMismatchError(filename, mime_type)
