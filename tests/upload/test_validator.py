import pytest

from upload.config import UploadSettings
from upload.exceptions import (
    FileTooLargeError,
    FileTooSmallError,
    InvalidFileTypeError,
    MimeMismatchError,
)
from upload.validator import UploadValidator, sanitize_filename

_MAX_SMALL_FILE_SIZE = 2_097_152


@pytest.fixture()
def validator() -> UploadValidator:
    settings = UploadSettings(
        max_small_file_size=_MAX_SMALL_FILE_SIZE,
        allowed_file_types=("image/jpeg", "image/png", "video/mp4"),
    )
    return UploadValidator(settings)


def test_mediated_upload_accepts_file_at_threshold(validator: UploadValidator) -> None:
    validator.validate_for_mediated_upload("profile.jpg", _MAX_SMALL_FILE_SIZE, "image/jpeg")


def test_mediated_upload_rejects_file_over_threshold(validator: UploadValidator) -> None:
    with pytest.raises(FileTooLargeError) as exc_info:
        validator.validate_for_mediated_upload(
            "profile.jpg", _MAX_SMALL_FILE_SIZE + 1, "image/jpeg"
        )

    assert exc_info.value.size == _MAX_SMALL_FILE_SIZE + 1
    assert exc_info.value.max_size == _MAX_SMALL_FILE_SIZE


def test_presigned_upload_accepts_file_over_threshold(validator: UploadValidator) -> None:
    validator.validate_for_presigned_upload("video.mp4", _MAX_SMALL_FILE_SIZE + 1, "video/mp4")


def test_presigned_upload_rejects_file_at_or_under_threshold(
    validator: UploadValidator,
) -> None:
    with pytest.raises(FileTooSmallError) as exc_info:
        validator.validate_for_presigned_upload("video.mp4", _MAX_SMALL_FILE_SIZE, "video/mp4")

    assert exc_info.value.size == _MAX_SMALL_FILE_SIZE
    assert exc_info.value.max_size == _MAX_SMALL_FILE_SIZE


def test_rejects_file_type_not_in_allowlist(validator: UploadValidator) -> None:
    with pytest.raises(InvalidFileTypeError) as exc_info:
        validator.validate_for_mediated_upload("virus.exe", 1024, "application/x-msdownload")

    assert exc_info.value.mime_type == "application/x-msdownload"
    assert exc_info.value.allowed_types == ("image/jpeg", "image/png", "video/mp4")


def test_rejects_mime_type_not_matching_filename_extension(
    validator: UploadValidator,
) -> None:
    with pytest.raises(MimeMismatchError) as exc_info:
        validator.validate_for_mediated_upload("fake.png", 1024, "image/jpeg")

    assert exc_info.value.filename == "fake.png"
    assert exc_info.value.mime_type == "image/jpeg"


def test_accepts_when_extension_cannot_be_guessed(validator: UploadValidator) -> None:
    validator.validate_for_mediated_upload("noextension", 1024, "image/jpeg")


@pytest.mark.parametrize(
    ("filename", "mime_type"),
    [("photo.jpg", "image/jpeg"), ("photo.jpeg", "image/jpeg"), ("logo.png", "image/png")],
)
def test_accepts_matching_extension_and_mime(
    validator: UploadValidator, filename: str, mime_type: str
) -> None:
    validator.validate_for_mediated_upload(filename, 1024, mime_type)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("profile.jpg", "profile.jpg"),
        ("../../etc/passwd.jpg", "passwd.jpg"),
        # `\` isn't a path separator on POSIX, so it's stripped as a disallowed
        # character rather than treated as a directory boundary — still no `/`
        # or `..` survives, so no traversal is possible, just a mangled name.
        ("..\\..\\windows\\config.jpg", "windowsconfig.jpg"),
        ("/etc/passwd.jpg", "passwd.jpg"),
        ("my photo (1).jpg", "my photo (1).jpg".replace("(", "").replace(")", "")),
        ("café.jpg", "cafe.jpg"),
    ],
)
def test_sanitize_filename_strips_traversal_and_unsafe_characters(
    filename: str, expected: str
) -> None:
    assert sanitize_filename(filename) == expected


@pytest.mark.parametrize("filename", ["", ".", "..", "../..", "***", "/"])
def test_sanitize_filename_falls_back_when_result_is_empty(filename: str) -> None:
    assert sanitize_filename(filename) == "upload"


def test_sanitize_filename_truncates_long_names() -> None:
    long_name = ("a" * 300) + ".jpg"

    result = sanitize_filename(long_name)

    assert len(result) == 200
