import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from exceptions import register_exception_handlers
from shared.storage.exceptions import StorageError
from shared.storage.s3_provider import S3StorageProvider
from upload.config import UploadSettings
from upload.dependencies import get_upload_service
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
from upload.router import router
from upload.schemas import FileMetadata, UploadSessionMetadata
from upload.service import UploadService
from upload.validator import UploadValidator

from .conftest import FakeFileRepository, FakeUploadSessionRepository

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


@pytest.fixture()
def app() -> FastAPI:
    fastapi_app = FastAPI()
    register_exception_handlers(fastapi_app)
    fastapi_app.include_router(router)
    return fastapi_app


def test_upload_endpoint_returns_metadata_on_success(app: FastAPI) -> None:
    expected = FileMetadata(
        file_id=uuid.uuid4(),
        storage_key="originals/2026/08/13/abc.jpg",
        filename="profile.jpg",
        size=4,
        mime_type="image/jpeg",
        upload_url="https://storage.example.com/originals/2026/08/13/abc.jpg",
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
        upload_url="https://storage.example.com/originals/2026/08/14/abc.mp4",
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
