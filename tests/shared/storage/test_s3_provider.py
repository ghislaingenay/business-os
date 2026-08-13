from collections.abc import AsyncIterator, Iterator
from unittest.mock import patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from shared.storage.exceptions import (
    StorageError,
    StorageObjectNotFoundError,
    StoragePermissionError,
)
from shared.storage.s3_provider import S3StorageProvider


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, "operation")


_BUCKET = "test-bucket"
_REGION = "us-east-1"
_KEY = "originals/test.txt"


@pytest.fixture()
def s3_provider() -> Iterator[S3StorageProvider]:
    with mock_aws():
        boto3.client("s3", region_name=_REGION).create_bucket(Bucket=_BUCKET)
        yield S3StorageProvider(bucket=_BUCKET, region=_REGION)


async def _read_all(stream: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in stream])


async def test_upload_and_download_roundtrip(s3_provider: S3StorageProvider) -> None:
    await s3_provider.upload(_KEY, b"hello world", metadata={"mime_type": "text/plain"})

    body = await _read_all(s3_provider.download(_KEY))

    assert body == b"hello world"


async def test_upload_accepts_async_iterator(s3_provider: S3StorageProvider) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"chunk-1-"
        yield b"chunk-2"

    await s3_provider.upload(_KEY, chunks())

    body = await _read_all(s3_provider.download(_KEY))

    assert body == b"chunk-1-chunk-2"


async def test_head_returns_metadata(s3_provider: S3StorageProvider) -> None:
    await s3_provider.upload(_KEY, b"12345")

    metadata = await s3_provider.head(_KEY)

    assert metadata.size == 5
    assert metadata.etag
    assert metadata.last_modified


async def test_head_missing_key_raises_not_found(s3_provider: S3StorageProvider) -> None:
    with pytest.raises(StorageObjectNotFoundError):
        await s3_provider.head("missing")


async def test_download_missing_key_raises_not_found(s3_provider: S3StorageProvider) -> None:
    with pytest.raises(StorageObjectNotFoundError):
        await _read_all(s3_provider.download("missing"))


async def test_delete_removes_object(s3_provider: S3StorageProvider) -> None:
    await s3_provider.upload(_KEY, b"bye")

    await s3_provider.delete(_KEY)

    with pytest.raises(StorageObjectNotFoundError):
        await s3_provider.head(_KEY)


async def test_delete_is_idempotent_for_missing_key(s3_provider: S3StorageProvider) -> None:
    await s3_provider.delete("does-not-exist")


async def test_generate_presigned_url_get(s3_provider: S3StorageProvider) -> None:
    url = await s3_provider.generate_presigned_url(_KEY, "GET", ttl=60)

    assert url.startswith("http")
    assert _BUCKET in url


async def test_generate_presigned_url_put(s3_provider: S3StorageProvider) -> None:
    url = await s3_provider.generate_presigned_url(_KEY, "PUT", ttl=60)

    assert url.startswith("http")
    assert _BUCKET in url


async def test_upload_wraps_permission_denied(s3_provider: S3StorageProvider) -> None:
    with (
        patch.object(
            s3_provider._client, "upload_fileobj", side_effect=_client_error("AccessDenied")
        ),
        pytest.raises(StoragePermissionError) as exc_info,
    ):
        await s3_provider.upload(_KEY, b"data")

    assert exc_info.value.key == _KEY


async def test_upload_wraps_unrecognized_error_as_generic_storage_error(
    s3_provider: S3StorageProvider,
) -> None:
    with (
        patch.object(
            s3_provider._client, "upload_fileobj", side_effect=_client_error("InternalError")
        ),
        pytest.raises(StorageError) as exc_info,
    ):
        await s3_provider.upload(_KEY, b"data")

    assert not isinstance(exc_info.value, StorageObjectNotFoundError)
    assert not isinstance(exc_info.value, StoragePermissionError)


async def test_delete_wraps_permission_denied(s3_provider: S3StorageProvider) -> None:
    with (
        patch.object(
            s3_provider._client, "delete_object", side_effect=_client_error("AccessDenied")
        ),
        pytest.raises(StoragePermissionError) as exc_info,
    ):
        await s3_provider.delete(_KEY)

    assert exc_info.value.key == _KEY


async def test_generate_presigned_url_wraps_client_error(
    s3_provider: S3StorageProvider,
) -> None:
    with (
        patch.object(
            s3_provider._client,
            "generate_presigned_url",
            side_effect=_client_error("InternalError"),
        ),
        pytest.raises(StorageError) as exc_info,
    ):
        await s3_provider.generate_presigned_url(_KEY, "GET", ttl=60)

    assert not isinstance(exc_info.value, StoragePermissionError)


def test_accepts_custom_endpoint_url() -> None:
    """Wiring check only — no live MinIO/R2 server is available in this environment."""
    endpoint = "http://localhost:9000"

    provider = S3StorageProvider(bucket=_BUCKET, region=_REGION, endpoint_url=endpoint)

    assert provider._client.meta.endpoint_url == endpoint
