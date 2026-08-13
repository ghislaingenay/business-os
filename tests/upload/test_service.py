from datetime import UTC, datetime

import pytest

from shared.storage.s3_provider import S3StorageProvider
from upload.config import UploadSettings
from upload.exceptions import FileTooLargeError, InvalidFileTypeError, MimeMismatchError
from upload.schemas import FileMetadata
from upload.service import UploadService
from upload.validator import UploadValidator

from .conftest import AsyncBytesStream, FakeFileRepository


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
        filename="profile.jpg", mime_type="image/jpeg", stream=AsyncBytesStream(b"x" * 1024)
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
        filename="profile.jpg", mime_type="image/jpeg", stream=AsyncBytesStream(b"hello world")
    )

    stored = b"".join([chunk async for chunk in s3_storage_provider.download(metadata.storage_key)])
    assert stored == b"hello world"


async def test_upload_small_file_rejects_oversized_file(
    service: UploadService, fake_file_repository: FakeFileRepository
) -> None:
    with pytest.raises(FileTooLargeError):
        await service.upload_small_file(
            filename="video.mp4",
            mime_type="video/mp4",
            stream=AsyncBytesStream(b"x" * 2_097_153),
        )

    assert fake_file_repository.saved == []


async def test_upload_small_file_does_not_fully_materialize_oversized_stream(
    service: UploadService,
) -> None:
    huge = AsyncBytesStream(b"x" * 50_000_000)

    with pytest.raises(FileTooLargeError):
        await service.upload_small_file(filename="video.mp4", mime_type="video/mp4", stream=huge)

    # Bounded read should stop shortly after the threshold, not consume the
    # full 50MB stream (TD-002 §10 memory-exhaustion mitigation).
    assert huge._pos < 3_000_000


async def test_upload_small_file_rejects_disallowed_type(service: UploadService) -> None:
    with pytest.raises(InvalidFileTypeError):
        await service.upload_small_file(
            filename="virus.exe",
            mime_type="application/x-msdownload",
            stream=AsyncBytesStream(b"x" * 1024),
        )


async def test_upload_small_file_rejects_mime_mismatch(service: UploadService) -> None:
    with pytest.raises(MimeMismatchError):
        await service.upload_small_file(
            filename="fake.png", mime_type="image/jpeg", stream=AsyncBytesStream(b"x" * 1024)
        )


async def test_storage_key_uses_date_prefixed_uuid_format(service: UploadService) -> None:
    metadata = await service.upload_small_file(
        filename="profile.jpg", mime_type="image/jpeg", stream=AsyncBytesStream(b"data")
    )

    today = datetime.now(UTC)
    assert metadata.storage_key.startswith(f"originals/{today:%Y}/{today:%m}/{today:%d}/")


async def test_upload_small_file_sanitizes_path_traversal_in_filename(
    service: UploadService,
) -> None:
    metadata = await service.upload_small_file(
        filename="../../etc/passwd.jpg",
        mime_type="image/jpeg",
        stream=AsyncBytesStream(b"data"),
    )

    assert metadata.filename == "passwd.jpg"
    assert "/" not in metadata.filename
    assert ".." not in metadata.filename
