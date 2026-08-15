import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from redis.exceptions import RedisError

from shared.storage.exceptions import StorageError, StorageObjectNotFoundError
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

from .conftest import (
    AsyncBytesStream,
    FakeDedupService,
    FakeFileRepository,
    FakeJobQueue,
    FakeUploadSessionRepository,
)

_LARGE_FILE_SIZE = 5_000_000
_VIDEO_MIME_TYPE = "video/mp4"


@pytest.fixture()
def service(
    *,
    upload_settings: UploadSettings,
    s3_storage_provider: S3StorageProvider,
    fake_file_repository: FakeFileRepository,
    fake_upload_session_repository: FakeUploadSessionRepository,
    fake_dedup_service: FakeDedupService,
    fake_job_queue: FakeJobQueue,
) -> UploadService:
    return UploadService(
        validator=UploadValidator(upload_settings),
        storage=s3_storage_provider,
        repository=fake_file_repository,
        session_repository=fake_upload_session_repository,
        dedup_service=fake_dedup_service,
        job_queue=fake_job_queue,
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


async def test_upload_small_file_persists_sha256_hash(
    service: UploadService, fake_file_repository: FakeFileRepository
) -> None:
    content = b"hello world"

    metadata = await service.upload_small_file(
        filename="profile.jpg", mime_type="image/jpeg", stream=AsyncBytesStream(content)
    )

    expected_hash = hashlib.sha256(content).hexdigest()
    assert metadata.sha256_hash == expected_hash
    assert fake_file_repository.saved[0].sha256_hash == expected_hash


async def test_upload_small_file_checks_dedup_with_content_hash(
    service: UploadService, fake_dedup_service: FakeDedupService
) -> None:
    content = b"hello world"

    await service.upload_small_file(
        filename="profile.jpg", mime_type="image/jpeg", stream=AsyncBytesStream(content)
    )

    assert fake_dedup_service.check_calls == [hashlib.sha256(content).hexdigest()]


async def test_upload_small_file_skips_storage_upload_on_dedup_hit(
    upload_settings: UploadSettings,
    s3_storage_provider: S3StorageProvider,
    fake_file_repository: FakeFileRepository,
    fake_upload_session_repository: FakeUploadSessionRepository,
) -> None:
    existing_key = "originals/2026/08/01/preexisting.jpg"
    dedup_service = FakeDedupService(existing_storage_key=existing_key)
    service = UploadService(
        validator=UploadValidator(upload_settings),
        storage=s3_storage_provider,
        repository=fake_file_repository,
        session_repository=fake_upload_session_repository,
        dedup_service=dedup_service,
        job_queue=FakeJobQueue(),
        presigned_url_ttl=upload_settings.presigned_url_ttl,
    )

    metadata = await service.upload_small_file(
        filename="profile.jpg", mime_type="image/jpeg", stream=AsyncBytesStream(b"hello world")
    )

    # FR-2: existing storage_key reused, no new object written to storage.
    assert metadata.storage_key == existing_key
    with pytest.raises(StorageObjectNotFoundError):
        await s3_storage_provider.head(existing_key)
    assert dedup_service.finish_calls == [
        (hashlib.sha256(b"hello world").hexdigest(), existing_key)
    ]


async def test_upload_small_file_aborts_dedup_lock_on_storage_failure(
    upload_settings: UploadSettings,
    fake_file_repository: FakeFileRepository,
    fake_upload_session_repository: FakeUploadSessionRepository,
) -> None:
    """FR-4 AC: the dedup lock is released on failure, not just success."""

    class _FailingStorage:
        async def upload(self, *_args: object, **_kwargs: object) -> str:
            raise StorageError("simulated storage outage")

    dedup_service = FakeDedupService()
    service = UploadService(
        validator=UploadValidator(upload_settings),
        storage=_FailingStorage(),  # type: ignore[arg-type]
        repository=fake_file_repository,
        session_repository=fake_upload_session_repository,
        dedup_service=dedup_service,
        job_queue=FakeJobQueue(),
        presigned_url_ttl=upload_settings.presigned_url_ttl,
    )
    content = b"hello world"

    with pytest.raises(StorageError):
        await service.upload_small_file(
            filename="profile.jpg", mime_type="image/jpeg", stream=AsyncBytesStream(content)
        )

    assert dedup_service.abort_calls == [hashlib.sha256(content).hexdigest()]
    assert dedup_service.finish_calls == []  # no storage_key was ever written
    assert fake_file_repository.saved == []


async def test_upload_small_file_enqueues_variant_generation_job(
    service: UploadService, fake_job_queue: FakeJobQueue, fake_file_repository: FakeFileRepository
) -> None:
    metadata = await service.upload_small_file(
        filename="profile.jpg", mime_type="image/jpeg", stream=AsyncBytesStream(b"hello world")
    )

    assert len(fake_job_queue.enqueued) == 1
    function, args = fake_job_queue.enqueued[0]
    assert function == "generate_variants"
    assert args == (str(metadata.file_id), metadata.storage_key, "image/jpeg")


async def test_upload_small_file_enqueue_failure_does_not_fail_upload(
    upload_settings: UploadSettings,
    s3_storage_provider: S3StorageProvider,
    fake_file_repository: FakeFileRepository,
    fake_upload_session_repository: FakeUploadSessionRepository,
    fake_dedup_service: FakeDedupService,
) -> None:
    """Redis being down for the job queue degrades to "no variants" rather
    than failing the upload — matches dedup's fail-open treatment of Redis
    outages elsewhere in this domain.
    """

    class _FailingJobQueue:
        async def enqueue_job(self, *_args: object) -> object | None:
            raise RedisError("simulated redis outage")

    service = UploadService(
        validator=UploadValidator(upload_settings),
        storage=s3_storage_provider,
        repository=fake_file_repository,
        session_repository=fake_upload_session_repository,
        dedup_service=fake_dedup_service,
        job_queue=_FailingJobQueue(),  # type: ignore[arg-type]
        presigned_url_ttl=upload_settings.presigned_url_ttl,
    )

    metadata = await service.upload_small_file(
        filename="profile.jpg", mime_type="image/jpeg", stream=AsyncBytesStream(b"hello world")
    )

    assert isinstance(metadata, FileMetadata)
    assert len(fake_file_repository.saved) == 1


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


async def test_finalize_large_upload_enqueues_variant_generation_job(
    service: UploadService,
    s3_storage_provider: S3StorageProvider,
    fake_job_queue: FakeJobQueue,
) -> None:
    session_metadata = await service.initiate_large_upload(
        filename="video.mp4", size=_LARGE_FILE_SIZE, mime_type=_VIDEO_MIME_TYPE
    )
    await s3_storage_provider.upload(session_metadata.storage_key, b"x" * _LARGE_FILE_SIZE)
    real_etag = (await s3_storage_provider.head(session_metadata.storage_key)).etag

    metadata = await service.finalize_large_upload(
        upload_id=session_metadata.upload_id, etag=real_etag
    )

    assert len(fake_job_queue.enqueued) == 1
    function, args = fake_job_queue.enqueued[0]
    assert function == "generate_variants"
    assert args == (str(metadata.file_id), metadata.storage_key, _VIDEO_MIME_TYPE)


async def test_finalize_large_upload_persists_sha256_hash_and_checks_dedup(
    service: UploadService,
    s3_storage_provider: S3StorageProvider,
    fake_file_repository: FakeFileRepository,
    fake_dedup_service: FakeDedupService,
) -> None:
    session_metadata = await service.initiate_large_upload(
        filename="video.mp4", size=_LARGE_FILE_SIZE, mime_type=_VIDEO_MIME_TYPE
    )
    content = b"x" * _LARGE_FILE_SIZE
    await s3_storage_provider.upload(session_metadata.storage_key, content)
    real_etag = (await s3_storage_provider.head(session_metadata.storage_key)).etag

    metadata = await service.finalize_large_upload(
        upload_id=session_metadata.upload_id, etag=real_etag
    )

    # FR-1: hash calculated on finalize (streamed from storage, not buffered
    # server-side, since the client PUT directly to storage).
    expected_hash = hashlib.sha256(content).hexdigest()
    assert metadata.sha256_hash == expected_hash
    assert fake_file_repository.saved[0].sha256_hash == expected_hash
    assert fake_dedup_service.check_calls == [expected_hash]
    # Resolved 2026-08-14 (TD-003 §3): a dedup hit on the presigned path only
    # records the hash — it does NOT repoint storage_key to an existing one.
    assert fake_dedup_service.finish_calls == [(expected_hash, session_metadata.storage_key)]


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
