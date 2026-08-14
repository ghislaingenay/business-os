import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import boto3
import pytest
from moto import mock_aws

from dedup.service import DedupCheckResult
from shared.storage.s3_provider import S3StorageProvider
from upload.config import UploadSettings
from upload.models import File, UploadSession

_BUCKET = "test-uploads"
_REGION = "us-east-1"


class AsyncBytesStream:
    """`ByteStream` (see `upload.service`) over an in-memory `bytes` payload."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    async def read(self, size: int = -1) -> bytes:
        end = len(self._data) if size < 0 else self._pos + size
        chunk = self._data[self._pos : end]
        self._pos += len(chunk)
        return chunk


class FakeFileRepository:
    """In-memory `FileRepository` (see `upload.service`) for tests without a real DB.

    Mimics the `file_id`/`created_at`/`updated_at` values Postgres would assign
    via `server_default` on commit, since there's no DB here to do it.
    """

    def __init__(self) -> None:
        self.saved: list[File] = []

    async def save(self, file: File) -> File:
        now = datetime.now(UTC)
        file.file_id = uuid.uuid4()
        file.created_at = now
        file.updated_at = now
        self.saved.append(file)
        return file


@pytest.fixture()
def fake_file_repository() -> FakeFileRepository:
    return FakeFileRepository()


class FakeUploadSessionRepository:
    """In-memory `UploadSessionRepositoryProtocol` (see `upload.service`) for tests.

    Mimics the `upload_id`/`created_at` values Postgres would assign via
    `server_default` on commit, since there's no DB here to do it.
    """

    def __init__(self) -> None:
        self.saved: list[UploadSession] = []

    async def save(self, upload_session: UploadSession) -> UploadSession:
        upload_session.upload_id = uuid.uuid4()
        upload_session.created_at = datetime.now(UTC)
        self.saved.append(upload_session)
        return upload_session

    async def find_active_by_id(self, upload_id: uuid.UUID) -> UploadSession | None:
        for session in self.saved:
            if session.upload_id == upload_id and not session.finalized:
                return session
        return None

    async def mark_finalized(self, upload_session: UploadSession) -> None:
        upload_session.finalized = True


@pytest.fixture()
def fake_upload_session_repository() -> FakeUploadSessionRepository:
    return FakeUploadSessionRepository()


@pytest.fixture()
def s3_storage_provider() -> Iterator[S3StorageProvider]:
    with mock_aws():
        boto3.client("s3", region_name=_REGION).create_bucket(Bucket=_BUCKET)
        yield S3StorageProvider(bucket=_BUCKET, region=_REGION)


@pytest.fixture()
def upload_settings() -> UploadSettings:
    return UploadSettings(
        max_small_file_size=2_097_152,
        presigned_url_ttl=900,
        allowed_file_types=("image/jpeg", "image/png", "video/mp4"),
    )


class FakeDedupService:
    """Controllable `DedupService` double (see `upload.service`) for tests
    that need to control dedup's hit/miss decision without exercising its
    own cache/lock/DB-fallback logic — that's covered by
    tests/dedup/test_service.py, so it isn't re-tested here.
    """

    def __init__(self, existing_storage_key: str | None = None) -> None:
        self.existing_storage_key = existing_storage_key
        self.check_calls: list[str] = []
        self.finish_calls: list[tuple[str, str]] = []
        self.abort_calls: list[str] = []

    async def check(self, sha256_hash: str) -> DedupCheckResult:
        self.check_calls.append(sha256_hash)
        return DedupCheckResult(
            existing_storage_key=self.existing_storage_key, lock_token="fake-lock-token"
        )

    async def finish(self, sha256_hash: str, storage_key: str, result: DedupCheckResult) -> None:
        self.finish_calls.append((sha256_hash, storage_key))

    async def abort(self, sha256_hash: str, result: DedupCheckResult) -> None:
        self.abort_calls.append(sha256_hash)


@pytest.fixture()
def fake_dedup_service() -> FakeDedupService:
    return FakeDedupService()
