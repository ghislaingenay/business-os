"""Factory for instantiating a `StorageProvider` from configuration."""

from shared.storage.config import StorageSettings
from shared.storage.exceptions import StorageConfigurationError
from shared.storage.provider import StorageProvider
from shared.storage.s3_provider import S3StorageProvider

_S3_COMPATIBLE_PROVIDERS = {"s3", "minio", "r2"}


class StorageProviderFactory:
    """Builds the configured `StorageProvider`, failing fast on bad config."""

    @staticmethod
    def create(settings: StorageSettings) -> StorageProvider:
        if settings.provider in _S3_COMPATIBLE_PROVIDERS:
            if not settings.s3_bucket or not settings.s3_region:
                raise StorageConfigurationError(
                    f"STORAGE_PROVIDER={settings.provider} requires "
                    "S3_BUCKET and S3_REGION to be set"
                )
            return S3StorageProvider(
                bucket=settings.s3_bucket,
                region=settings.s3_region,
                endpoint_url=settings.s3_endpoint,
            )

        if settings.provider == "gcs":
            raise StorageConfigurationError(
                "STORAGE_PROVIDER=gcs is not yet supported (planned for a follow-up phase)"
            )

        raise StorageConfigurationError(f"Unknown STORAGE_PROVIDER: {settings.provider!r}")
