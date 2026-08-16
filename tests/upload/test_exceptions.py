import uuid
from datetime import UTC, datetime

from upload.exceptions import (
    FileTooLargeError,
    FileTooSmallError,
    FileTooSmallForMultipartError,
    IncompletePartsError,
    InvalidFileTypeError,
    InvalidPartNumberError,
    MimeMismatchError,
    MultipartSessionExpiredError,
    MultipartSessionNotFoundError,
    UploadError,
)


def test_file_too_large_error_carries_size_and_max_size() -> None:
    error = FileTooLargeError(size=3_000_000, max_size=2_097_152)

    assert isinstance(error, UploadError)
    assert error.size == 3_000_000
    assert error.max_size == 2_097_152
    assert "3000000" in str(error)
    assert "2097152" in str(error)


def test_file_too_small_error_carries_size_and_max_size() -> None:
    error = FileTooSmallError(size=1024, max_size=2_097_152)

    assert isinstance(error, UploadError)
    assert error.size == 1024
    assert error.max_size == 2_097_152
    assert "1024" in str(error)


def test_invalid_file_type_error_carries_mime_type_and_allowed_types() -> None:
    error = InvalidFileTypeError(
        mime_type="application/x-msdownload", allowed_types=("image/jpeg", "image/png")
    )

    assert isinstance(error, UploadError)
    assert error.mime_type == "application/x-msdownload"
    assert error.allowed_types == ("image/jpeg", "image/png")
    assert "application/x-msdownload" in str(error)


def test_mime_mismatch_error_carries_filename_and_mime_type() -> None:
    error = MimeMismatchError(filename="fake.png", mime_type="image/jpeg")

    assert isinstance(error, UploadError)
    assert error.filename == "fake.png"
    assert error.mime_type == "image/jpeg"
    assert "fake.png" in str(error)
    assert "image/jpeg" in str(error)


def test_file_too_small_for_multipart_error_carries_size_and_min_size() -> None:
    error = FileTooSmallForMultipartError(size=1024, min_size=104_857_600)

    assert isinstance(error, UploadError)
    assert error.size == 1024
    assert error.min_size == 104_857_600
    assert "1024" in str(error)


def test_multipart_session_not_found_error_carries_upload_id() -> None:
    upload_id = uuid.uuid4()

    error = MultipartSessionNotFoundError(upload_id)

    assert isinstance(error, UploadError)
    assert error.upload_id == upload_id
    assert str(upload_id) in str(error)


def test_multipart_session_expired_error_carries_upload_id_and_expiry() -> None:
    upload_id = uuid.uuid4()
    expired_at = datetime(2026, 8, 15, 10, 0, 0, tzinfo=UTC)

    error = MultipartSessionExpiredError(upload_id, expired_at)

    assert isinstance(error, UploadError)
    assert error.upload_id == upload_id
    assert error.expired_at == expired_at


def test_invalid_part_number_error_carries_part_number_and_total_parts() -> None:
    error = InvalidPartNumberError(part_number=99, total_parts=20)

    assert isinstance(error, UploadError)
    assert error.part_number == 99
    assert error.total_parts == 20
    assert "99" in str(error)
    assert "20" in str(error)


def test_incomplete_parts_error_carries_upload_id_and_missing_parts() -> None:
    upload_id = uuid.uuid4()

    error = IncompletePartsError(upload_id, missing_parts=[3, 7])

    assert isinstance(error, UploadError)
    assert error.upload_id == upload_id
    assert error.missing_parts == [3, 7]
