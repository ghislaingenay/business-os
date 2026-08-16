import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dedup.exceptions import DedupDatabaseUnavailableError
from exceptions import register_exception_handlers
from shared.storage.exceptions import StorageError
from shared.storage.s3_provider import S3StorageProvider
from upload.config import UploadSettings
from upload.dependencies import get_multipart_service, get_upload_service
from upload.exceptions import (
    EtagMismatchError,
    FileTooLargeError,
    FileTooSmallError,
    FileTooSmallForMultipartError,
    IncompletePartsError,
    InvalidFileTypeError,
    InvalidPartNumberError,
    MimeMismatchError,
    MultipartSessionExpiredError,
    MultipartSessionNotFoundError,
    PresignedUrlExpiredError,
    UploadIncompleteError,
    UploadNotFoundError,
)
from upload.multipart_config import MultipartSettings
from upload.multipart_service import MultipartService
from upload.router import router
from upload.schemas import (
    FileMetadata,
    MultipartUploadSessionMetadata,
    MultipartUploadStatus,
    RetryPartResponse,
    UploadSessionMetadata,
)
from upload.service import UploadService
from upload.validator import UploadValidator

from .conftest import (
    FakeDedupService,
    FakeFileRepository,
    FakeJobQueue,
    FakeMultipartSessionRepository,
    FakeUploadSessionRepository,
)

_MAX_SMALL_FILE_SIZE = 2_097_152
_OVERSIZED_MEDIATED_FILE_SIZE = 3_000_000
_UNDERSIZED_PRESIGNED_FILE_SIZE = 1_048_576
_LARGE_FILE_SIZE = 5_000_000
_VIDEO_MIME_TYPE = "video/mp4"


class _RaisingService:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def upload_small_file(self, **_kwargs: object) -> FileMetadata:
        raise self._exc

    async def initiate_large_upload(self, **_kwargs: object) -> UploadSessionMetadata:
        raise self._exc

    async def finalize_large_upload(self, **_kwargs: object) -> FileMetadata:
        raise self._exc


class _UnusedUploadService:
    """Default `get_upload_service` override for tests that only exercise
    the multipart paths — see `_UnusedMultipartService` for why a default is
    needed at all.
    """

    async def upload_small_file(self, **_kwargs: object) -> FileMetadata:
        raise AssertionError("service.upload_small_file should not be called by this test")

    async def initiate_large_upload(self, **_kwargs: object) -> UploadSessionMetadata:
        raise AssertionError("service.initiate_large_upload should not be called by this test")

    async def finalize_large_upload(self, **_kwargs: object) -> FileMetadata:
        raise AssertionError("service.finalize_large_upload should not be called by this test")


class _UnusedMultipartService:
    """Default `get_multipart_service` override for tests that only exercise
    the non-multipart paths — FastAPI resolves both `/upload/initiate` and
    `/upload/finalize`'s dependencies on every request regardless of which
    branch the handler takes, so something must stand in even when a test
    never calls into it.
    """

    async def initiate(self, **_kwargs: object) -> MultipartUploadSessionMetadata:
        raise AssertionError("multipart_service.initiate should not be called by this test")

    async def get_status(self, *_args: object) -> MultipartUploadStatus:
        raise AssertionError("multipart_service.get_status should not be called by this test")

    async def retry_part(self, *_args: object) -> RetryPartResponse:
        raise AssertionError("multipart_service.retry_part should not be called by this test")

    async def finalize(self, **_kwargs: object) -> FileMetadata:
        raise AssertionError("multipart_service.finalize should not be called by this test")


class _RaisingMultipartService(_UnusedMultipartService):
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def initiate(self, **_kwargs: object) -> MultipartUploadSessionMetadata:
        raise self._exc

    async def get_status(self, *_args: object) -> MultipartUploadStatus:
        raise self._exc

    async def retry_part(self, *_args: object) -> RetryPartResponse:
        raise self._exc

    async def finalize(self, **_kwargs: object) -> FileMetadata:
        raise self._exc


@pytest.fixture()
def app() -> FastAPI:
    fastapi_app = FastAPI()
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(router)
    fastapi_app.dependency_overrides[get_upload_service] = _UnusedUploadService
    fastapi_app.dependency_overrides[get_multipart_service] = _UnusedMultipartService
    return fastapi_app


def test_upload_endpoint_returns_metadata_on_success(app: FastAPI) -> None:
    expected = FileMetadata(
        file_id=uuid.uuid4(),
        storage_key="originals/2026/08/13/abc.jpg",
        filename="profile.jpg",
        size=4,
        mime_type="image/jpeg",
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        upload_url="https://storage.example.com/originals/2026/08/13/abc.jpg",
        web_optimized_url=None,
        thumbnail_url=None,
        created_at=datetime.now(UTC),
    )

    class _StubService:
        async def upload_small_file(self, **_kwargs: object) -> FileMetadata:
            return expected

    app.dependency_overrides[get_upload_service] = _StubService
    client = TestClient(app)

    response = client.post(
        "/upload", files={"file": ("profile.jpg", io.BytesIO(b"data"), "image/jpeg")}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "profile.jpg"
    assert body["storage_key"] == expected.storage_key


def test_upload_endpoint_returns_413_when_file_too_large(app: FastAPI) -> None:
    app.dependency_overrides[get_upload_service] = lambda: _RaisingService(
        FileTooLargeError(_OVERSIZED_MEDIATED_FILE_SIZE, _MAX_SMALL_FILE_SIZE)
    )
    client = TestClient(app)

    response = client.post(
        "/upload", files={"file": ("video.mp4", io.BytesIO(b"data"), _VIDEO_MIME_TYPE)}
    )

    assert response.status_code == 413
    body = response.json()
    assert body["error"] == "file_too_large"
    assert body["max_size"] == _MAX_SMALL_FILE_SIZE
    assert body["suggested_endpoint"] == "/upload/initiate"


def test_upload_endpoint_returns_400_for_invalid_file_type(app: FastAPI) -> None:
    app.dependency_overrides[get_upload_service] = lambda: _RaisingService(
        InvalidFileTypeError("application/x-msdownload", ("image/jpeg", "image/png"))
    )
    client = TestClient(app)

    response = client.post(
        "/upload",
        files={"file": ("virus.exe", io.BytesIO(b"data"), "application/x-msdownload")},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "invalid_file_type"
    assert body["allowed_types"] == ["image/jpeg", "image/png"]


def test_upload_endpoint_returns_400_for_mime_mismatch(app: FastAPI) -> None:
    app.dependency_overrides[get_upload_service] = lambda: _RaisingService(
        MimeMismatchError("fake.png", "image/jpeg")
    )
    client = TestClient(app)

    response = client.post(
        "/upload", files={"file": ("fake.png", io.BytesIO(b"data"), "image/jpeg")}
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "mime_mismatch"
    assert body["filename"] == "fake.png"
    assert body["detected_mime"] == "image/jpeg"


def test_upload_endpoint_returns_503_when_storage_unavailable(app: FastAPI) -> None:
    app.dependency_overrides[get_upload_service] = lambda: _RaisingService(StorageError("boom"))
    client = TestClient(app)

    response = client.post(
        "/upload", files={"file": ("profile.jpg", io.BytesIO(b"data"), "image/jpeg")}
    )

    assert response.status_code == 503
    assert response.json()["error"] == "storage_unavailable"


def test_upload_endpoint_returns_503_when_dedup_database_unavailable(app: FastAPI) -> None:
    app.dependency_overrides[get_upload_service] = lambda: _RaisingService(
        DedupDatabaseUnavailableError("timed out")
    )
    client = TestClient(app)

    response = client.post(
        "/upload", files={"file": ("profile.jpg", io.BytesIO(b"data"), "image/jpeg")}
    )

    assert response.status_code == 503
    assert response.json()["error"] == "dedup_database_unavailable"


def test_upload_endpoint_end_to_end_with_real_storage(
    app: FastAPI,
    upload_settings: UploadSettings,
    s3_storage_provider: object,
    fake_file_repository: FakeFileRepository,
    fake_upload_session_repository: FakeUploadSessionRepository,
) -> None:
    service = UploadService(
        validator=UploadValidator(upload_settings),
        storage=s3_storage_provider,  # type: ignore[arg-type]
        repository=fake_file_repository,
        session_repository=fake_upload_session_repository,
        dedup_service=FakeDedupService(),
        job_queue=FakeJobQueue(),
        presigned_url_ttl=upload_settings.presigned_url_ttl,
    )
    app.dependency_overrides[get_upload_service] = lambda: service
    client = TestClient(app)

    response = client.post(
        "/upload",
        files={"file": ("profile.jpg", io.BytesIO(b"hello world"), "image/jpeg")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["size"] == 11
    assert body["storage_key"].startswith("originals/")
    assert len(fake_file_repository.saved) == 1


def test_initiate_endpoint_returns_metadata_on_success(app: FastAPI) -> None:
    expected = UploadSessionMetadata(
        upload_id=uuid.uuid4(),
        presigned_url="https://s3.example.com/bucket/key?signature=abc",
        storage_key="originals/2026/08/14/abc.mp4",
        expires_at=datetime.now(UTC),
        instructions="PUT file bytes to presigned_url, then call /upload/finalize with upload_id",
    )

    class _StubService:
        async def initiate_large_upload(self, **_kwargs: object) -> UploadSessionMetadata:
            return expected

    app.dependency_overrides[get_upload_service] = _StubService
    client = TestClient(app)

    response = client.post(
        "/upload/initiate",
        json={"filename": "video.mp4", "size": _LARGE_FILE_SIZE, "mime_type": _VIDEO_MIME_TYPE},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["storage_key"] == expected.storage_key
    assert body["instructions"] == expected.instructions


def test_initiate_endpoint_returns_400_for_file_too_small(app: FastAPI) -> None:
    app.dependency_overrides[get_upload_service] = lambda: _RaisingService(
        FileTooSmallError(_UNDERSIZED_PRESIGNED_FILE_SIZE, _MAX_SMALL_FILE_SIZE)
    )
    client = TestClient(app)

    response = client.post(
        "/upload/initiate",
        json={
            "filename": "photo.jpg",
            "size": _UNDERSIZED_PRESIGNED_FILE_SIZE,
            "mime_type": "image/jpeg",
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "file_too_small"
    assert body["suggested_endpoint"] == "/upload"


def test_initiate_endpoint_returns_400_for_invalid_file_type(app: FastAPI) -> None:
    app.dependency_overrides[get_upload_service] = lambda: _RaisingService(
        InvalidFileTypeError("application/zip", ("image/jpeg", _VIDEO_MIME_TYPE))
    )
    client = TestClient(app)

    response = client.post(
        "/upload/initiate",
        json={"filename": "archive.zip", "size": _LARGE_FILE_SIZE, "mime_type": "application/zip"},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_file_type"


def test_finalize_endpoint_returns_metadata_on_success(app: FastAPI) -> None:
    expected = FileMetadata(
        file_id=uuid.uuid4(),
        storage_key="originals/2026/08/14/abc.mp4",
        filename="video.mp4",
        size=_LARGE_FILE_SIZE,
        mime_type=_VIDEO_MIME_TYPE,
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        upload_url="https://storage.example.com/originals/2026/08/14/abc.mp4",
        web_optimized_url=None,
        thumbnail_url=None,
        created_at=datetime.now(UTC),
    )

    class _StubService:
        async def finalize_large_upload(self, **_kwargs: object) -> FileMetadata:
            return expected

    app.dependency_overrides[get_upload_service] = _StubService
    client = TestClient(app)

    response = client.post(
        "/upload/finalize",
        json={"upload_id": str(uuid.uuid4()), "etag": "abc123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "video.mp4"
    assert body["storage_key"] == expected.storage_key


def test_finalize_endpoint_returns_404_for_unknown_upload_id(app: FastAPI) -> None:
    upload_id = uuid.uuid4()
    app.dependency_overrides[get_upload_service] = lambda: _RaisingService(
        UploadNotFoundError(upload_id)
    )
    client = TestClient(app)

    response = client.post(
        "/upload/finalize",
        json={"upload_id": str(upload_id), "etag": "abc123"},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "upload_not_found"
    assert body["upload_id"] == str(upload_id)


def test_finalize_endpoint_returns_400_for_incomplete_upload(app: FastAPI) -> None:
    app.dependency_overrides[get_upload_service] = lambda: _RaisingService(
        UploadIncompleteError("originals/2026/08/14/abc.mp4")
    )
    client = TestClient(app)

    response = client.post(
        "/upload/finalize",
        json={"upload_id": str(uuid.uuid4()), "etag": "abc123"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "upload_incomplete"
    assert body["storage_key"] == "originals/2026/08/14/abc.mp4"


def test_finalize_endpoint_returns_410_for_expired_presigned_url(app: FastAPI) -> None:
    upload_id = uuid.uuid4()
    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    app.dependency_overrides[get_upload_service] = lambda: _RaisingService(
        PresignedUrlExpiredError(upload_id, expired_at)
    )
    client = TestClient(app)

    response = client.post(
        "/upload/finalize",
        json={"upload_id": str(upload_id), "etag": "abc123"},
    )

    assert response.status_code == 410
    assert response.json()["error"] == "presigned_url_expired"


def test_finalize_endpoint_returns_400_for_etag_mismatch(app: FastAPI) -> None:
    app.dependency_overrides[get_upload_service] = lambda: _RaisingService(
        EtagMismatchError(expected="client-etag", actual="storage-etag")
    )
    client = TestClient(app)

    response = client.post(
        "/upload/finalize",
        json={"upload_id": str(uuid.uuid4()), "etag": "client-etag"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "etag_mismatch"
    assert body["expected_etag"] == "client-etag"
    assert body["actual_etag"] == "storage-etag"


async def test_large_upload_initiate_then_finalize_end_to_end(
    app: FastAPI,
    upload_settings: UploadSettings,
    s3_storage_provider: S3StorageProvider,
    fake_file_repository: FakeFileRepository,
    fake_upload_session_repository: FakeUploadSessionRepository,
) -> None:
    service = UploadService(
        validator=UploadValidator(upload_settings),
        storage=s3_storage_provider,
        repository=fake_file_repository,
        session_repository=fake_upload_session_repository,
        dedup_service=FakeDedupService(),
        job_queue=FakeJobQueue(),
        presigned_url_ttl=upload_settings.presigned_url_ttl,
    )
    app.dependency_overrides[get_upload_service] = lambda: service
    client = TestClient(app)

    initiate_response = client.post(
        "/upload/initiate",
        json={"filename": "video.mp4", "size": _LARGE_FILE_SIZE, "mime_type": _VIDEO_MIME_TYPE},
    )
    assert initiate_response.status_code == 200
    initiate_body = initiate_response.json()

    # Simulate the client's direct PUT to storage via the presigned URL, then
    # capture the ETag storage reports (what a real client reads off the PUT
    # response and sends to /upload/finalize).
    await s3_storage_provider.upload(initiate_body["storage_key"], b"x" * _LARGE_FILE_SIZE)
    real_etag = (await s3_storage_provider.head(initiate_body["storage_key"])).etag

    finalize_response = client.post(
        "/upload/finalize",
        json={"upload_id": initiate_body["upload_id"], "etag": real_etag},
    )

    assert finalize_response.status_code == 200
    finalize_body = finalize_response.json()
    assert finalize_body["storage_key"] == initiate_body["storage_key"]
    assert finalize_body["size"] == _LARGE_FILE_SIZE
    assert len(fake_file_repository.saved) == 1


_MULTIPART_SIZE = 125_000_000


def test_initiate_endpoint_multipart_returns_session_metadata(app: FastAPI) -> None:
    expected = MultipartUploadSessionMetadata(
        upload_id=uuid.uuid4(),
        part_size=10_485_760,
        total_parts=12,
        storage_key="originals/2026/08/16/abc.mp4",
        part_upload_urls=["https://s3.example.com/part1", "https://s3.example.com/part2"],
        expires_at=datetime.now(UTC),
    )

    class _StubMultipartService(_UnusedMultipartService):
        async def initiate(self, **_kwargs: object) -> MultipartUploadSessionMetadata:
            return expected

    app.dependency_overrides[get_multipart_service] = _StubMultipartService
    client = TestClient(app)

    response = client.post(
        "/upload/initiate",
        json={
            "filename": "video.mp4",
            "size": _MULTIPART_SIZE,
            "mime_type": _VIDEO_MIME_TYPE,
            "multipart": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_parts"] == 12
    assert body["part_upload_urls"] == expected.part_upload_urls


def test_initiate_endpoint_multipart_returns_400_for_file_too_small(app: FastAPI) -> None:
    app.dependency_overrides[get_multipart_service] = lambda: _RaisingMultipartService(
        FileTooSmallForMultipartError(1024, 104_857_600)
    )
    client = TestClient(app)

    response = client.post(
        "/upload/initiate",
        json={
            "filename": "video.mp4",
            "size": 1024,
            "mime_type": _VIDEO_MIME_TYPE,
            "multipart": True,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "file_too_small_for_multipart"


def test_status_endpoint_returns_progress(app: FastAPI) -> None:
    upload_id = uuid.uuid4()
    expected = MultipartUploadStatus(
        upload_id=upload_id,
        storage_key="originals/2026/08/16/abc.mp4",
        total_parts=10,
        completed_parts=[1, 2, 3],
        missing_parts=[4, 5, 6, 7, 8, 9, 10],
        progress_percentage=30.0,
        bytes_uploaded=31_457_280,
        eta_seconds=120,
    )

    class _StubMultipartService(_UnusedMultipartService):
        async def get_status(self, *_args: object) -> MultipartUploadStatus:
            return expected

    app.dependency_overrides[get_multipart_service] = _StubMultipartService
    client = TestClient(app)

    response = client.get(f"/upload/{upload_id}/status")

    assert response.status_code == 200
    body = response.json()
    assert body["completed_parts"] == [1, 2, 3]
    assert body["progress_percentage"] == 30.0
    assert body["eta_seconds"] == 120


def test_status_endpoint_returns_404_for_unknown_upload_id(app: FastAPI) -> None:
    upload_id = uuid.uuid4()
    app.dependency_overrides[get_multipart_service] = lambda: _RaisingMultipartService(
        MultipartSessionNotFoundError(upload_id)
    )
    client = TestClient(app)

    response = client.get(f"/upload/{upload_id}/status")

    assert response.status_code == 404
    assert response.json()["error"] == "multipart_session_not_found"


def test_retry_part_endpoint_returns_presigned_url(app: FastAPI) -> None:
    upload_id = uuid.uuid4()
    expected = RetryPartResponse(
        part_number=5,
        presigned_url="https://s3.example.com/part5?signature=abc",
        expires_at=datetime.now(UTC),
    )

    class _StubMultipartService(_UnusedMultipartService):
        async def retry_part(self, *_args: object) -> RetryPartResponse:
            return expected

    app.dependency_overrides[get_multipart_service] = _StubMultipartService
    client = TestClient(app)

    response = client.post(f"/upload/{upload_id}/retry-part", json={"part_number": 5})

    assert response.status_code == 200
    assert response.json()["part_number"] == 5


def test_retry_part_endpoint_returns_400_for_invalid_part_number(app: FastAPI) -> None:
    upload_id = uuid.uuid4()
    app.dependency_overrides[get_multipart_service] = lambda: _RaisingMultipartService(
        InvalidPartNumberError(part_number=99, total_parts=10)
    )
    client = TestClient(app)

    response = client.post(f"/upload/{upload_id}/retry-part", json={"part_number": 99})

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "invalid_part_number"
    assert body["total_parts"] == 10


def test_finalize_endpoint_multipart_returns_metadata_on_success(app: FastAPI) -> None:
    expected = FileMetadata(
        file_id=uuid.uuid4(),
        storage_key="originals/2026/08/16/abc.mp4",
        filename="video.mp4",
        size=_MULTIPART_SIZE,
        mime_type=_VIDEO_MIME_TYPE,
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        upload_url="https://storage.example.com/originals/2026/08/16/abc.mp4",
        web_optimized_url=None,
        thumbnail_url=None,
        created_at=datetime.now(UTC),
    )

    class _StubMultipartService(_UnusedMultipartService):
        async def finalize(self, **_kwargs: object) -> FileMetadata:
            return expected

    app.dependency_overrides[get_multipart_service] = _StubMultipartService
    client = TestClient(app)

    response = client.post(
        "/upload/finalize",
        json={
            "upload_id": str(uuid.uuid4()),
            "parts": [{"part_number": 1, "etag": "abc123"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["storage_key"] == expected.storage_key


def test_finalize_endpoint_multipart_returns_400_for_incomplete_parts(app: FastAPI) -> None:
    upload_id = uuid.uuid4()
    app.dependency_overrides[get_multipart_service] = lambda: _RaisingMultipartService(
        IncompletePartsError(upload_id, missing_parts=[3, 4])
    )
    client = TestClient(app)

    response = client.post(
        "/upload/finalize",
        json={"upload_id": str(upload_id), "parts": [{"part_number": 1, "etag": "abc123"}]},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "incomplete_parts"
    assert body["missing_parts"] == [3, 4]


def test_finalize_endpoint_multipart_returns_410_for_expired_session(app: FastAPI) -> None:
    upload_id = uuid.uuid4()
    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    app.dependency_overrides[get_multipart_service] = lambda: _RaisingMultipartService(
        MultipartSessionExpiredError(upload_id, expired_at)
    )
    client = TestClient(app)

    response = client.post(
        "/upload/finalize",
        json={"upload_id": str(upload_id), "parts": [{"part_number": 1, "etag": "abc123"}]},
    )

    assert response.status_code == 410
    assert response.json()["error"] == "multipart_session_expired"


def test_finalize_endpoint_rejects_body_with_neither_etag_nor_parts(app: FastAPI) -> None:
    client = TestClient(app)

    response = client.post("/upload/finalize", json={"upload_id": str(uuid.uuid4())})

    assert response.status_code == 422


async def test_multipart_upload_end_to_end(
    *,
    app: FastAPI,
    upload_settings: UploadSettings,
    multipart_settings: MultipartSettings,
    s3_storage_provider: S3StorageProvider,
    fake_file_repository: FakeFileRepository,
    fake_multipart_session_repository: FakeMultipartSessionRepository,
) -> None:
    service = MultipartService(
        validator=UploadValidator(upload_settings),
        storage=s3_storage_provider,
        repository=fake_file_repository,
        session_repository=fake_multipart_session_repository,
        dedup_service=FakeDedupService(),
        job_queue=FakeJobQueue(),
        settings=multipart_settings,
        presigned_url_ttl=upload_settings.presigned_url_ttl,
    )
    app.dependency_overrides[get_multipart_service] = lambda: service
    client = TestClient(app)

    initiate_response = client.post(
        "/upload/initiate",
        json={
            "filename": "video.mp4",
            "size": _MULTIPART_SIZE,
            "mime_type": _VIDEO_MIME_TYPE,
            "multipart": True,
        },
    )
    assert initiate_response.status_code == 200
    initiate_body = initiate_response.json()
    upload_id = initiate_body["upload_id"]

    status_response = client.get(f"/upload/{upload_id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["completed_parts"] == []

    retry_response = client.post(f"/upload/{upload_id}/retry-part", json={"part_number": 1})
    assert retry_response.status_code == 200

    storage_upload_id = fake_multipart_session_repository.saved[0].storage_upload_id
    total_parts = initiate_body["total_parts"]
    part_sizes = [5 * 1024 * 1024] * (total_parts - 1) + [1024]
    parts_payload = []
    for part_number, part_size in zip(range(1, total_parts + 1), part_sizes, strict=True):
        part_response = s3_storage_provider._client.upload_part(
            Bucket=s3_storage_provider._bucket,
            Key=initiate_body["storage_key"],
            UploadId=storage_upload_id,
            PartNumber=part_number,
            Body=b"x" * part_size,
        )
        parts_payload.append({"part_number": part_number, "etag": part_response["ETag"].strip('"')})

    finalize_response = client.post(
        "/upload/finalize",
        json={"upload_id": upload_id, "parts": parts_payload},
    )

    assert finalize_response.status_code == 200
    finalize_body = finalize_response.json()
    assert finalize_body["storage_key"] == initiate_body["storage_key"]
    assert finalize_body["size"] == sum(part_sizes)
    assert len(fake_file_repository.saved) == 1
    assert fake_file_repository.saved[0].upload_strategy == "multipart"
