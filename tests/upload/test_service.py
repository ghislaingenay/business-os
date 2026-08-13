from datetime import UTC, datetime

import pytest

from shared.storage.s3_provider import S3StorageProvider
from upload.config import UploadSettings
from upload.exceptions import FileTooLargeError, InvalidFileTypeError, MimeMismatchError
from upload.schemas import FileMetadata
from upload.service import UploadService
from upload.validator import UploadValidator

from .conftest import FakeFileRepository


@pytest.fixture()
def service(
    upload_settings: UploadSettings,
    s3_storage_provider: S3StorageProvider,
    fake_file_repository: FakeFileRepository,
) -> UploadService:
    return UploadService(
        validator=UploadValidator(upload_settings),
        storage=s3_storage_provider,
        repository=fake_file_repository,
        download_url_ttl=upload_settings.presigned_url_ttl,
    )


async def test_upload_small_file_success(
    service: UploadService, fake_file_repository: FakeFileRepository
) -> None:
    metadata = await service.upload_small_file(
        filename="profile.jpg", size=1024, mime_type="image/jpeg", content=b"x" * 1024
    )

    assert isinstance(metadata, FileMetadata)
    assert metadata.filename == "profile.jpg"
    assert metadata.size == 1024
    assert metadata.mime_type == "image/jpeg"
    assert metadata.storage_key.startswith("originals/")
    assert metadata.storage_key.endswith(".jpg")
    assert metadata.upload_url
    assert len(fake_file_repository.saved) == 1
    assert fake_file_repository.saved[0].upload_strategy == "mediated"


async def test_upload_small_file_persists_bytes_to_storage(
    service: UploadService, s3_storage_provider: S3StorageProvider
) -> None:
    metadata = await service.upload_small_file(
        filename="profile.jpg", size=11, mime_type="image/jpeg", content=b"hello world"
    )

    stored = b"".join([chunk async for chunk in s3_storage_provider.download(metadata.storage_key)])
    assert stored == b"hello world"


async def test_upload_small_file_rejects_oversized_file(
    service: UploadService, fake_file_repository: FakeFileRepository
) -> None:
    with pytest.raises(FileTooLargeError):
        await service.upload_small_file(
            filename="video.mp4",
            size=2_097_153,
            mime_type="video/mp4",
            content=b"x" * 2_097_153,
        )

    assert fake_file_repository.saved == []


async def test_upload_small_file_rejects_disallowed_type(service: UploadService) -> None:
    with pytest.raises(InvalidFileTypeError):
        await service.upload_small_file(
            filename="virus.exe",
            size=1024,
            mime_type="application/x-msdownload",
            content=b"x" * 1024,
        )


async def test_upload_small_file_rejects_mime_mismatch(service: UploadService) -> None:
    with pytest.raises(MimeMismatchError):
        await service.upload_small_file(
            filename="fake.png", size=1024, mime_type="image/jpeg", content=b"x" * 1024
        )


async def test_storage_key_uses_date_prefixed_uuid_format(service: UploadService) -> None:
    metadata = await service.upload_small_file(
        filename="profile.jpg", size=4, mime_type="image/jpeg", content=b"data"
    )

    today = datetime.now(UTC)
    assert metadata.storage_key.startswith(f"originals/{today:%Y}/{today:%m}/{today:%d}/")
