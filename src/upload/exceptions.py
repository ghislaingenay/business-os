"""Domain exceptions for the upload domain."""


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
