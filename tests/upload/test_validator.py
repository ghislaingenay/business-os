import pytest

from upload.config import UploadSettings
from upload.exceptions import (
    FileTooLargeError,
    FileTooSmallError,
    InvalidFileTypeError,
    MimeMismatchError,
)
from upload.validator import UploadValidator

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
