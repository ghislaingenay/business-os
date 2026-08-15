import io
import uuid
from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws
from PIL import Image

from shared.storage.s3_provider import S3StorageProvider
from variants.config import VariantSettings

_BUCKET = "test-uploads"
_REGION = "us-east-1"


@pytest.fixture()
def s3_storage_provider() -> Iterator[S3StorageProvider]:
    with mock_aws():
        boto3.client("s3", region_name=_REGION).create_bucket(Bucket=_BUCKET)
        yield S3StorageProvider(bucket=_BUCKET, region=_REGION)


@pytest.fixture()
def variant_settings() -> VariantSettings:
    return VariantSettings(
        web_optimized_quality=85,
        thumbnail_size=256,
        thumbnail_quality=80,
        job_timeout_seconds=60,
        retry_delays_seconds=(1, 5, 25),
        generated_mime_types=("image/jpeg", "image/png", "image/gif"),
    )


class FakeVariantRepository:
    """In-memory `VariantRepositoryProtocol` (see `variants.service`) for tests."""

    def __init__(self) -> None:
        self.updates: list[tuple[uuid.UUID, str, str]] = []

    async def update_variants(
        self, file_id: uuid.UUID, web_optimized_url: str, thumbnail_url: str
    ) -> None:
        self.updates.append((file_id, web_optimized_url, thumbnail_url))


@pytest.fixture()
def fake_variant_repository() -> FakeVariantRepository:
    return FakeVariantRepository()


def make_jpeg_bytes(size: tuple[int, int] = (100, 100)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(0, 128, 255)).save(buffer, format="JPEG")
    return buffer.getvalue()
