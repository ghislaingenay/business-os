import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import boto3
import pytest
from moto import mock_aws

from shared.storage.s3_provider import S3StorageProvider
from upload.config import UploadSettings
from upload.models import File

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
