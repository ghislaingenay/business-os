import uuid
from datetime import UTC, datetime, timedelta

import pytest
from redis.exceptions import RedisError

from shared.storage.s3_provider import S3StorageProvider
from upload.exceptions import (
    FileTooSmallForMultipartError,
    IncompletePartsError,
    InvalidFileTypeError,
    InvalidPartNumberError,
    MultipartSessionExpiredError,
    MultipartSessionNotFoundError,
)
from upload.models import MultipartSession
from upload.multipart_config import MultipartSettings
from upload.multipart_service import MultipartCleanupService, MultipartService
from upload.schemas import PartETag
from upload.validator import UploadValidator

from .conftest import (
    FakeDedupService,
    FakeFileRepository,
    FakeJobQueue,
    FakeMultipartSessionRepository,
)

_VIDEO_MIME_TYPE = "video/mp4"
_MULTIPART_SIZE = 125_000_000  # > 100MB threshold; ceil(125_000_000 / 10_485_760) == 12 parts
_UNDERSIZED_MULTIPART_SIZE = 1_048_576


def _build_service(
    *,
    upload_settings,
    multipart_settings: MultipartSettings,
    storage: S3StorageProvider,
    session_repository: FakeMultipartSessionRepository,
    repository: FakeFileRepository,
    dedup_service: FakeDedupService,
    job_queue: FakeJobQueue,
) -> MultipartService:
    return MultipartService(
        validator=UploadValidator(upload_settings),
        storage=storage,
        repository=repository,
        session_repository=session_repository,
        dedup_service=dedup_service,
        job_queue=job_queue,
        settings=multipart_settings,
        presigned_url_ttl=upload_settings.presigned_url_ttl,
    )


@pytest.fixture()
def service(
    *,
    upload_settings,
    multipart_settings: MultipartSettings,
    s3_storage_provider: S3StorageProvider,
    fake_multipart_session_repository: FakeMultipartSessionRepository,
    fake_file_repository: FakeFileRepository,
    fake_dedup_service: FakeDedupService,
    fake_job_queue: FakeJobQueue,
) -> MultipartService:
    return _build_service(
        upload_settings=upload_settings,
        multipart_settings=multipart_settings,
        storage=s3_storage_provider,
        session_repository=fake_multipart_session_repository,
        repository=fake_file_repository,
        dedup_service=fake_dedup_service,
        job_queue=fake_job_queue,
    )


async def test_initiate_creates_session_and_returns_part_urls(
    service: MultipartService, fake_multipart_session_repository: FakeMultipartSessionRepository
) -> None:
    result = await service.initiate(
        filename="video.mp4", size=_MULTIPART_SIZE, mime_type=_VIDEO_MIME_TYPE
    )

    assert result.total_parts == 12
    assert result.part_size == 10_485_760
    assert len(result.part_upload_urls) == 12
    assert len(fake_multipart_session_repository.saved) == 1
    assert fake_multipart_session_repository.saved[0].total_parts == 12


async def test_initiate_raises_when_at_or_under_multipart_threshold(
    service: MultipartService,
) -> None:
    with pytest.raises(FileTooSmallForMultipartError):
        await service.initiate(
            filename="video.mp4", size=_UNDERSIZED_MULTIPART_SIZE, mime_type=_VIDEO_MIME_TYPE
        )


async def test_initiate_raises_for_invalid_mime_type(service: MultipartService) -> None:
    with pytest.raises(InvalidFileTypeError):
        await service.initiate(
            filename="archive.zip", size=_MULTIPART_SIZE, mime_type="application/zip"
        )


async def test_get_status_raises_when_session_not_found(service: MultipartService) -> None:
    with pytest.raises(MultipartSessionNotFoundError):
        await service.get_status(uuid.uuid4())


async def test_get_status_reports_completed_and_missing_parts(
    service: MultipartService, s3_storage_provider: S3StorageProvider
) -> None:
    session_metadata = await service.initiate(
        filename="video.mp4", size=_MULTIPART_SIZE, mime_type=_VIDEO_MIME_TYPE
    )
    storage_key = session_metadata.storage_key
    storage_upload_id = _storage_upload_id(service, session_metadata.upload_id)
    s3_storage_provider._client.upload_part(
        Bucket=s3_storage_provider._bucket,
        Key=storage_key,
        UploadId=storage_upload_id,
        PartNumber=1,
        Body=b"x" * 1024,
    )

    status = await service.get_status(session_metadata.upload_id)

    assert status.completed_parts == [1]
    assert status.missing_parts == list(range(2, 13))
    assert status.bytes_uploaded == 1024
    assert status.progress_percentage == pytest.approx(8.33, abs=0.01)


async def test_get_status_eta_seconds_none_before_any_bytes_uploaded(
    service: MultipartService,
) -> None:
    session_metadata = await service.initiate(
        filename="video.mp4", size=_MULTIPART_SIZE, mime_type=_VIDEO_MIME_TYPE
    )

    status = await service.get_status(session_metadata.upload_id)

    assert status.eta_seconds is None


async def test_get_status_eta_seconds_estimated_from_elapsed_time(
    service: MultipartService,
    s3_storage_provider: S3StorageProvider,
    fake_multipart_session_repository: FakeMultipartSessionRepository,
) -> None:
    session_metadata = await service.initiate(
        filename="video.mp4", size=_MULTIPART_SIZE, mime_type=_VIDEO_MIME_TYPE
    )
    saved_session = fake_multipart_session_repository.saved[0]
    saved_session.created_at = datetime.now(UTC) - timedelta(seconds=10)
    s3_storage_provider._client.upload_part(
        Bucket=s3_storage_provider._bucket,
        Key=session_metadata.storage_key,
        UploadId=saved_session.storage_upload_id,
        PartNumber=1,
        Body=b"x" * 10_000_000,
    )

    status = await service.get_status(session_metadata.upload_id)

    assert status.eta_seconds is not None
    assert status.eta_seconds > 0


async def test_retry_part_returns_presigned_url(service: MultipartService) -> None:
    session_metadata = await service.initiate(
        filename="video.mp4", size=_MULTIPART_SIZE, mime_type=_VIDEO_MIME_TYPE
    )

    result = await service.retry_part(session_metadata.upload_id, 2)

    assert result.part_number == 2
    assert result.presigned_url.startswith("http")


async def test_retry_part_raises_for_out_of_range_part_number(service: MultipartService) -> None:
    session_metadata = await service.initiate(
        filename="video.mp4", size=_MULTIPART_SIZE, mime_type=_VIDEO_MIME_TYPE
    )

    with pytest.raises(InvalidPartNumberError):
        await service.retry_part(session_metadata.upload_id, 99)


async def test_retry_part_raises_when_session_not_found(service: MultipartService) -> None:
    with pytest.raises(MultipartSessionNotFoundError):
        await service.retry_part(uuid.uuid4(), 1)


async def test_finalize_completes_upload_and_persists_file(
    service: MultipartService,
    s3_storage_provider: S3StorageProvider,
    fake_file_repository: FakeFileRepository,
    fake_dedup_service: FakeDedupService,
    fake_job_queue: FakeJobQueue,
) -> None:
    session_metadata = await service.initiate(
        filename="video.mp4", size=_MULTIPART_SIZE, mime_type=_VIDEO_MIME_TYPE
    )
    storage_upload_id = _storage_upload_id(service, session_metadata.upload_id)
    # S3 requires every part except the last to be >= 5MB.
    part_sizes = [5 * 1024 * 1024] * (session_metadata.total_parts - 1) + [1024]
    parts = []
    for part_number, part_size in zip(
        range(1, session_metadata.total_parts + 1), part_sizes, strict=True
    ):
        response = s3_storage_provider._client.upload_part(
            Bucket=s3_storage_provider._bucket,
            Key=session_metadata.storage_key,
            UploadId=storage_upload_id,
            PartNumber=part_number,
            Body=b"x" * part_size,
        )
        parts.append(PartETag(part_number=part_number, etag=response["ETag"].strip('"')))

    file_metadata = await service.finalize(session_metadata.upload_id, parts)

    assert file_metadata.storage_key == session_metadata.storage_key
    assert file_metadata.size == sum(part_sizes)
    assert len(fake_file_repository.saved) == 1
    assert fake_file_repository.saved[0].upload_strategy == "multipart"
    assert len(fake_dedup_service.check_calls) == 1
    assert len(fake_job_queue.enqueued) == 1


async def test_finalize_enqueue_failure_does_not_fail_finalize(
    *,
    upload_settings,
    multipart_settings: MultipartSettings,
    s3_storage_provider: S3StorageProvider,
    fake_multipart_session_repository: FakeMultipartSessionRepository,
    fake_file_repository: FakeFileRepository,
    fake_dedup_service: FakeDedupService,
) -> None:
    """Redis being down for the job queue degrades to "no variants" rather
    than failing finalize — matches `UploadService`'s fail-open treatment
    (`test_upload_small_file_enqueue_failure_does_not_fail_upload`).
    """

    class _FailingJobQueue:
        async def enqueue_job(self, *_args: object) -> object | None:
            raise RedisError("simulated redis outage")

    finalize_service = _build_service(
        upload_settings=upload_settings,
        multipart_settings=multipart_settings,
        storage=s3_storage_provider,
        session_repository=fake_multipart_session_repository,
        repository=fake_file_repository,
        dedup_service=fake_dedup_service,
        job_queue=_FailingJobQueue(),  # type: ignore[arg-type]
    )
    session_metadata = await finalize_service.initiate(
        filename="video.mp4", size=_MULTIPART_SIZE, mime_type=_VIDEO_MIME_TYPE
    )
    storage_upload_id = _storage_upload_id(finalize_service, session_metadata.upload_id)
    part_sizes = [5 * 1024 * 1024] * (session_metadata.total_parts - 1) + [1024]
    parts = []
    for part_number, part_size in zip(
        range(1, session_metadata.total_parts + 1), part_sizes, strict=True
    ):
        response = s3_storage_provider._client.upload_part(
            Bucket=s3_storage_provider._bucket,
            Key=session_metadata.storage_key,
            UploadId=storage_upload_id,
            PartNumber=part_number,
            Body=b"x" * part_size,
        )
        parts.append(PartETag(part_number=part_number, etag=response["ETag"].strip('"')))

    file_metadata = await finalize_service.finalize(session_metadata.upload_id, parts)

    assert file_metadata.storage_key == session_metadata.storage_key
    assert len(fake_file_repository.saved) == 1


async def test_finalize_raises_for_missing_parts(
    service: MultipartService, s3_storage_provider: S3StorageProvider
) -> None:
    session_metadata = await service.initiate(
        filename="video.mp4", size=_MULTIPART_SIZE, mime_type=_VIDEO_MIME_TYPE
    )
    storage_upload_id = _storage_upload_id(service, session_metadata.upload_id)
    response = s3_storage_provider._client.upload_part(
        Bucket=s3_storage_provider._bucket,
        Key=session_metadata.storage_key,
        UploadId=storage_upload_id,
        PartNumber=1,
        Body=b"x" * 1024,
    )

    with pytest.raises(IncompletePartsError):
        await service.finalize(
            session_metadata.upload_id,
            [PartETag(part_number=1, etag=response["ETag"].strip('"'))],
        )


async def test_finalize_raises_when_session_expired(
    service: MultipartService, fake_multipart_session_repository: FakeMultipartSessionRepository
) -> None:
    session_metadata = await service.initiate(
        filename="video.mp4", size=_MULTIPART_SIZE, mime_type=_VIDEO_MIME_TYPE
    )
    saved_session = fake_multipart_session_repository.saved[0]
    saved_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    with pytest.raises(MultipartSessionExpiredError):
        await service.finalize(session_metadata.upload_id, [PartETag(part_number=1, etag="abc")])


async def test_finalize_raises_when_session_not_found(service: MultipartService) -> None:
    with pytest.raises(MultipartSessionNotFoundError):
        await service.finalize(uuid.uuid4(), [PartETag(part_number=1, etag="abc")])


async def test_cleanup_aborts_and_deletes_expired_sessions(
    s3_storage_provider: S3StorageProvider,
    fake_multipart_session_repository: FakeMultipartSessionRepository,
) -> None:
    storage_key = "originals/2026/08/16/expired.mp4"
    storage_upload_id = await s3_storage_provider.create_multipart_upload(storage_key)
    s3_storage_provider._client.upload_part(
        Bucket=s3_storage_provider._bucket,
        Key=storage_key,
        UploadId=storage_upload_id,
        PartNumber=1,
        Body=b"x" * 1024,
    )
    expired_session = MultipartSession(
        upload_id=uuid.uuid4(),
        storage_upload_id=storage_upload_id,
        filename="expired.mp4",
        size=_MULTIPART_SIZE,
        mime_type=_VIDEO_MIME_TYPE,
        part_size=10_485_760,
        total_parts=3,
        storage_key=storage_key,
        finalized=False,
        created_at=datetime.now(UTC) - timedelta(hours=25),
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    fake_multipart_session_repository.saved.append(expired_session)

    cleanup_service = MultipartCleanupService(
        storage=s3_storage_provider, session_repository=fake_multipart_session_repository
    )
    sessions_aborted, storage_parts_deleted = await cleanup_service.cleanup_abandoned_sessions()

    assert sessions_aborted == 1
    assert storage_parts_deleted == 1
    assert expired_session in fake_multipart_session_repository.deleted
    assert expired_session not in fake_multipart_session_repository.saved


async def test_cleanup_ignores_non_expired_sessions(
    service: MultipartService,
    s3_storage_provider: S3StorageProvider,
    fake_multipart_session_repository: FakeMultipartSessionRepository,
) -> None:
    await service.initiate(filename="video.mp4", size=_MULTIPART_SIZE, mime_type=_VIDEO_MIME_TYPE)
    cleanup_service = MultipartCleanupService(
        storage=s3_storage_provider,
        session_repository=fake_multipart_session_repository,
    )

    sessions_aborted, storage_parts_deleted = await cleanup_service.cleanup_abandoned_sessions()

    assert sessions_aborted == 0
    assert storage_parts_deleted == 0
    assert len(fake_multipart_session_repository.saved) == 1


def _storage_upload_id(service: MultipartService, upload_id: uuid.UUID) -> str:
    for session in service.session_repository.saved:  # type: ignore[attr-defined]
        if session.upload_id == upload_id:
            return session.storage_upload_id
    raise AssertionError("session not found")
