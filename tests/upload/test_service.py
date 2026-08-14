import uuid
from datetime import UTC, datetime, timedelta

import pytest

from shared.storage.s3_provider import S3StorageProvider
from upload.config import UploadSettings
from upload.exceptions import (
    EtagMismatchError,
    FileTooLargeError,
    FileTooSmallError,
    InvalidFileTypeError,
    MimeMismatchError,
    PresignedUrlExpiredError,
    UploadIncompleteError,
    UploadNotFoundError,
)
from upload.schemas import FileMetadata, UploadSessionMetadata
from upload.service import UploadService
from upload.validator import UploadValidator

from .conftest import AsyncBytesStream, FakeFileRepository, FakeUploadSessionRepository

_LARGE_FILE_SIZE = 5_000_000
_VIDEO_MIME_TYPE = "video/mp4"


@pytest.fixture()
def service(
    upload_settings: UploadSettings,
    s3_storage_provider: S3StorageProvider,
    fake_file_repository: FakeFileRepository,
    fake_upload_session_repository: FakeUploadSessionRepository,
) -> UploadService:
    return UploadService(
        validator=UploadValidator(upload_settings),
        storage=s3_storage_provider,
        repository=fake_file_repository,
        session_repository=fake_upload_session_repository,
        presigned_url_ttl=upload_settings.presigned_url_ttl,
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
            mime_type=_VIDEO_MIME_TYPE,
            stream=AsyncBytesStream(b"x" * 2_097_153),
        )

    assert fake_file_repository.saved == []


async def test_upload_small_file_does_not_fully_materialize_oversized_stream(
    service: UploadService,
) -> None:
    # A lazy stream that generates bytes on-demand exercises the same bounded-read behavior without
    # the large allocation.
    class _LazyStream:
        def __init__(self, total: int) -> None:
            self._remaining = total
            self._pos = 0

        async def read(self, size: int = -1) -> bytes:
            if self._remaining <= 0:
                return b""
            chunk_size = self._remaining if size < 0 else min(size, self._remaining)
            self._remaining -= chunk_size
            self._pos += chunk_size
            return b"x" * chunk_size

    huge = _LazyStream(50_000_000)

    with pytest.raises(FileTooLargeError):
        await service.upload_small_file(
            filename="video.mp4", mime_type=_VIDEO_MIME_TYPE, stream=huge
        )

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


async def test_initiate_large_upload_success(
    service: UploadService, fake_upload_session_repository: FakeUploadSessionRepository
) -> None:
    metadata = await service.initiate_large_upload(
        filename="video.mp4", size=_LARGE_FILE_SIZE, mime_type=_VIDEO_MIME_TYPE
    )

    assert isinstance(metadata, UploadSessionMetadata)
    assert metadata.storage_key.startswith("originals/")
    assert metadata.storage_key.endswith(".mp4")
    assert metadata.presigned_url
    assert metadata.instructions == (
        "PUT file bytes to presigned_url, then call /upload/finalize with upload_id"
    )
    assert len(fake_upload_session_repository.saved) == 1
    saved = fake_upload_session_repository.saved[0]
    assert saved.finalized is False
    assert saved.size == _LARGE_FILE_SIZE


async def test_initiate_large_upload_rejects_file_at_or_under_threshold(
    service: UploadService,
) -> None:
    with pytest.raises(FileTooSmallError):
        await service.initiate_large_upload(
            filename="photo.jpg", size=2_097_152, mime_type="image/jpeg"
        )


async def test_initiate_large_upload_rejects_disallowed_type(service: UploadService) -> None:
    with pytest.raises(InvalidFileTypeError):
        await service.initiate_large_upload(
            filename="payload.exe", size=_LARGE_FILE_SIZE, mime_type="application/x-msdownload"
        )


async def test_initiate_large_upload_sanitizes_filename(
    service: UploadService, fake_upload_session_repository: FakeUploadSessionRepository
) -> None:
    await service.initiate_large_upload(
        filename="../../etc/video.mp4", size=_LARGE_FILE_SIZE, mime_type=_VIDEO_MIME_TYPE
    )

    assert fake_upload_session_repository.saved[0].filename == "video.mp4"


async def test_initiate_large_upload_sets_expiry_from_ttl(service: UploadService) -> None:
    before = datetime.now(UTC)

    metadata = await service.initiate_large_upload(
        filename="video.mp4", size=_LARGE_FILE_SIZE, mime_type=_VIDEO_MIME_TYPE
    )

    after = datetime.now(UTC)
    assert before + timedelta(seconds=900) <= metadata.expires_at <= after + timedelta(seconds=900)


async def test_finalize_large_upload_success(
    service: UploadService,
    s3_storage_provider: S3StorageProvider,
    fake_file_repository: FakeFileRepository,
    fake_upload_session_repository: FakeUploadSessionRepository,
) -> None:
    session_metadata = await service.initiate_large_upload(
        filename="video.mp4", size=_LARGE_FILE_SIZE, mime_type=_VIDEO_MIME_TYPE
    )
    # Simulate the client's direct PUT to storage via the presigned URL, then
    # capture the ETag storage reports back (what a real client would read
    # off the PUT response and send to /upload/finalize).
    await s3_storage_provider.upload(session_metadata.storage_key, b"x" * _LARGE_FILE_SIZE)
    real_etag = (await s3_storage_provider.head(session_metadata.storage_key)).etag

    metadata = await service.finalize_large_upload(
        upload_id=session_metadata.upload_id, etag=real_etag
    )

    assert isinstance(metadata, FileMetadata)
    assert metadata.filename == "video.mp4"
    assert metadata.size == _LARGE_FILE_SIZE
    assert metadata.storage_key == session_metadata.storage_key
    assert len(fake_file_repository.saved) == 1
    assert fake_file_repository.saved[0].upload_strategy == "presigned"
    assert fake_file_repository.saved[0].etag == real_etag
    assert fake_upload_session_repository.saved[0].finalized is True


async def test_finalize_large_upload_raises_not_found_for_unknown_upload_id(
    service: UploadService,
) -> None:
    with pytest.raises(UploadNotFoundError):
        await service.finalize_large_upload(upload_id=uuid.uuid4(), etag="x")


async def test_finalize_large_upload_raises_not_found_when_already_finalized(
    service: UploadService, s3_storage_provider: S3StorageProvider
) -> None:
    session_metadata = await service.initiate_large_upload(
        filename="video.mp4", size=_LARGE_FILE_SIZE, mime_type=_VIDEO_MIME_TYPE
    )
    await s3_storage_provider.upload(session_metadata.storage_key, b"x" * _LARGE_FILE_SIZE)
    real_etag = (await s3_storage_provider.head(session_metadata.storage_key)).etag
    await service.finalize_large_upload(upload_id=session_metadata.upload_id, etag=real_etag)

    with pytest.raises(UploadNotFoundError):
        await service.finalize_large_upload(upload_id=session_metadata.upload_id, etag=real_etag)


async def test_finalize_large_upload_raises_expired_when_ttl_passed(
    service: UploadService, fake_upload_session_repository: FakeUploadSessionRepository
) -> None:
    session_metadata = await service.initiate_large_upload(
        filename="video.mp4", size=_LARGE_FILE_SIZE, mime_type=_VIDEO_MIME_TYPE
    )
    fake_upload_session_repository.saved[0].expires_at = datetime.now(UTC) - timedelta(seconds=1)

    with pytest.raises(PresignedUrlExpiredError):
        await service.finalize_large_upload(upload_id=session_metadata.upload_id, etag="x")


async def test_finalize_large_upload_raises_incomplete_when_never_uploaded(
    service: UploadService,
) -> None:
    session_metadata = await service.initiate_large_upload(
        filename="video.mp4", size=_LARGE_FILE_SIZE, mime_type=_VIDEO_MIME_TYPE
    )
    # Client never actually PUT the bytes to storage.

    with pytest.raises(UploadIncompleteError):
        await service.finalize_large_upload(upload_id=session_metadata.upload_id, etag="x")


async def test_finalize_large_upload_raises_etag_mismatch(
    service: UploadService,
    s3_storage_provider: S3StorageProvider,
    fake_file_repository: FakeFileRepository,
    fake_upload_session_repository: FakeUploadSessionRepository,
) -> None:
    session_metadata = await service.initiate_large_upload(
        filename="video.mp4", size=_LARGE_FILE_SIZE, mime_type=_VIDEO_MIME_TYPE
    )
    await s3_storage_provider.upload(session_metadata.storage_key, b"x" * _LARGE_FILE_SIZE)

    with pytest.raises(EtagMismatchError) as exc_info:
        await service.finalize_large_upload(
            upload_id=session_metadata.upload_id, etag="not-the-real-etag"
        )

    assert exc_info.value.expected == "not-the-real-etag"
    real_etag = (await s3_storage_provider.head(session_metadata.storage_key)).etag
    assert exc_info.value.actual == real_etag
    # A mismatch must not persist a File row or finalize the session — the
    # upload stays retryable via the same still-active session.
    assert fake_file_repository.saved == []
    assert fake_upload_session_repository.saved[0].finalized is False
