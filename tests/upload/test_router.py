import io
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from exceptions import register_exception_handlers
from shared.storage.exceptions import StorageError
from upload.config import UploadSettings
from upload.dependencies import get_upload_service
from upload.exceptions import FileTooLargeError, InvalidFileTypeError, MimeMismatchError
from upload.router import router
from upload.schemas import FileMetadata
from upload.service import UploadService
from upload.validator import UploadValidator

from .conftest import FakeFileRepository


class _RaisingService:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def upload_small_file(self, **_kwargs: object) -> FileMetadata:
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
        FileTooLargeError(3_000_000, 2_097_152)
    )
    client = TestClient(app)

    response = client.post(
        "/upload", files={"file": ("video.mp4", io.BytesIO(b"data"), "video/mp4")}
    )

    assert response.status_code == 413
    body = response.json()
    assert body["error"] == "file_too_large"
    assert body["max_size"] == 2_097_152
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
) -> None:
    service = UploadService(
        validator=UploadValidator(upload_settings),
        storage=s3_storage_provider,  # type: ignore[arg-type]
        repository=fake_file_repository,
        download_url_ttl=upload_settings.presigned_url_ttl,
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
