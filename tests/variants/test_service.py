import uuid

import pytest

from shared.storage.s3_provider import S3StorageProvider
from variants.config import VariantSettings
from variants.exceptions import VariantGenerationError
from variants.service import VariantService

from .conftest import FakeVariantRepository, make_jpeg_bytes

_ORIGINAL_STORAGE_KEY = "originals/2026/08/15/abc-123.jpg"


@pytest.fixture()
def service(
    s3_storage_provider: S3StorageProvider,
    fake_variant_repository: FakeVariantRepository,
    variant_settings: VariantSettings,
) -> VariantService:
    return VariantService(
        storage=s3_storage_provider,
        repository=fake_variant_repository,
        settings=variant_settings,
    )


async def test_generate_uploads_both_variants_and_updates_repository(
    service: VariantService,
    s3_storage_provider: S3StorageProvider,
    fake_variant_repository: FakeVariantRepository,
) -> None:
    await s3_storage_provider.upload(_ORIGINAL_STORAGE_KEY, make_jpeg_bytes())
    file_id = uuid.uuid4()

    await service.generate(file_id, _ORIGINAL_STORAGE_KEY, "image/jpeg")

    assert len(fake_variant_repository.updates) == 1
    updated_file_id, web_optimized_url, thumbnail_url = fake_variant_repository.updates[0]
    assert updated_file_id == file_id
    assert web_optimized_url == "webp/2026/08/15/abc-123.webp"
    assert thumbnail_url == "thumbnails/2026/08/15/abc-123_thumb.jpg"

    # Both variants actually landed in storage at the keys that were persisted.
    webp_meta = await s3_storage_provider.head(web_optimized_url)
    thumb_meta = await s3_storage_provider.head(thumbnail_url)
    assert webp_meta.size > 0
    assert thumb_meta.size > 0


async def test_generate_skips_unsupported_mime_types(
    service: VariantService,
    s3_storage_provider: S3StorageProvider,
    fake_variant_repository: FakeVariantRepository,
) -> None:
    await s3_storage_provider.upload(_ORIGINAL_STORAGE_KEY, b"not-really-a-video")

    await service.generate(uuid.uuid4(), _ORIGINAL_STORAGE_KEY, "video/mp4")

    assert fake_variant_repository.updates == []


async def test_generate_raises_variant_generation_error_on_missing_original(
    service: VariantService,
) -> None:
    with pytest.raises(VariantGenerationError):
        await service.generate(uuid.uuid4(), "originals/2026/08/15/missing.jpg", "image/jpeg")


async def test_generate_raises_variant_generation_error_on_corrupt_image(
    service: VariantService,
    s3_storage_provider: S3StorageProvider,
) -> None:
    await s3_storage_provider.upload(_ORIGINAL_STORAGE_KEY, b"not an image")

    with pytest.raises(VariantGenerationError):
        await service.generate(uuid.uuid4(), _ORIGINAL_STORAGE_KEY, "image/jpeg")
