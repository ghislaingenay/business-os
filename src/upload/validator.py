"""File validation utilities: size, allowed type, and MIME/extension agreement."""

import mimetypes

from upload.config import UploadSettings
from upload.exceptions import (
    FileTooLargeError,
    FileTooSmallError,
    InvalidFileTypeError,
    MimeMismatchError,
)


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
