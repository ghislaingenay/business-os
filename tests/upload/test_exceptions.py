from upload.exceptions import (
    FileTooLargeError,
    FileTooSmallError,
    InvalidFileTypeError,
    MimeMismatchError,
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
