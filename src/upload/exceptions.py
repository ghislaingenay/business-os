"""Domain exceptions for the upload domain."""

import uuid
from datetime import datetime


class UploadError(Exception):
    """Base exception for all upload validation failures."""


class FileTooLargeError(UploadError):
    """Raised when a file exceeds the mediated-upload size threshold."""

    def __init__(self, size: int, max_size: int) -> None:
        self.size = size
        self.max_size = max_size
        super().__init__(f"File size ({size} bytes) exceeds {max_size} byte limit")


class FileTooSmallError(UploadError):
    """Raised when a file is at or under the threshold but requests the presigned path."""

    def __init__(self, size: int, max_size: int) -> None:
        self.size = size
        self.max_size = max_size
        super().__init__(f"File size ({size} bytes) is <= {max_size} byte limit")


class InvalidFileTypeError(UploadError):
    """Raised when a file's MIME type is not in the configured allowlist."""

    def __init__(self, mime_type: str, allowed_types: tuple[str, ...]) -> None:
        self.mime_type = mime_type
        self.allowed_types = allowed_types
        super().__init__(f"File type {mime_type!r} is not allowed")


class MimeMismatchError(UploadError):
    """Raised when a file's declared MIME type doesn't match its filename extension."""

    def __init__(self, filename: str, mime_type: str) -> None:
        self.filename = filename
        self.mime_type = mime_type
        super().__init__(f"MIME type {mime_type!r} does not match file extension of {filename!r}")


class UploadNotFoundError(UploadError):
    """Raised when `upload_id` has no matching non-finalized upload session.

    Covers both a genuinely unknown `upload_id` and one that was already
    finalized by an earlier call — re-finalizing isn't a valid new-file
    creation path, so the repository lookup treats both cases the same way
    (TD-002 doesn't define separate behavior for a repeat finalize call).
    """

    def __init__(self, upload_id: uuid.UUID) -> None:
        self.upload_id = upload_id
        super().__init__(f"Upload session not found or already finalized: {upload_id}")


class PresignedUrlExpiredError(UploadError):
    """Raised when `/upload/finalize` is called after the session's presigned URL expired."""

    def __init__(self, upload_id: uuid.UUID, expired_at: datetime) -> None:
        self.upload_id = upload_id
        self.expired_at = expired_at
        super().__init__(
            f"Presigned URL for upload {upload_id} expired at {expired_at.isoformat()}"
        )


class UploadIncompleteError(UploadError):
    """Raised when finalize is called but no object exists at the session's storage key."""

    def __init__(self, storage_key: str) -> None:
        self.storage_key = storage_key
        super().__init__(f"File not found in storage at key: {storage_key}")


class FileTooSmallForMultipartError(UploadError):
    """Raised when `multipart: true` is requested for a file at or under
    FEAT-005's own multipart threshold (distinct from the mediated/presigned
    threshold in `FileTooSmallError`/`FileTooLargeError`).
    """

    def __init__(self, size: int, min_size: int) -> None:
        self.size = size
        self.min_size = min_size
        super().__init__(f"File size ({size} bytes) is <= {min_size} byte multipart threshold")


class MultipartSessionNotFoundError(UploadError):
    """Raised when `upload_id` has no matching non-finalized multipart session.

    Covers both an unknown `upload_id` and one already finalized, mirroring
    `UploadNotFoundError`'s treatment of the equivalent presigned-session case.
    """

    def __init__(self, upload_id: uuid.UUID) -> None:
        self.upload_id = upload_id
        super().__init__(f"Multipart session not found or already finalized: {upload_id}")


class MultipartSessionExpiredError(UploadError):
    """Raised when a multipart operation is attempted after the session's 24h TTL."""

    def __init__(self, upload_id: uuid.UUID, expired_at: datetime) -> None:
        self.upload_id = upload_id
        self.expired_at = expired_at
        super().__init__(f"Multipart session {upload_id} expired at {expired_at.isoformat()}")


class InvalidPartNumberError(UploadError):
    """Raised when a requested part number falls outside `[1, total_parts]`."""

    def __init__(self, part_number: int, total_parts: int) -> None:
        self.part_number = part_number
        self.total_parts = total_parts
        super().__init__(f"Part number {part_number} is outside the valid range [1, {total_parts}]")


class IncompletePartsError(UploadError):
    """Raised when `/upload/finalize` is called with gaps in the part sequence."""

    def __init__(self, upload_id: uuid.UUID, missing_parts: list[int]) -> None:
        self.upload_id = upload_id
        self.missing_parts = missing_parts
        super().__init__(f"Multipart upload {upload_id} is missing parts: {missing_parts}")


class EtagMismatchError(UploadError):
    """Raised when the client-supplied ETag doesn't match storage's reported ETag.

    Resolves TD-002 §13's open question on ETag integrity verification: the
    client-reported value from its direct PUT is checked against what
    `storage.head()` actually reports before the upload is accepted as valid.
    """

    def __init__(self, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"ETag mismatch: client reported {expected!r}, storage reports {actual!r}")
