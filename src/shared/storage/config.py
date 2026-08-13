"""Configuration for storage provider selection (FR-5)."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

StorageProviderName = Literal["s3", "gcs", "r2", "minio"]


class StorageSettings(BaseSettings):
    """Env-driven storage config. `STORAGE_PROVIDER` picks the backend;
    `StorageProviderFactory` validates the fields required for that backend.
    """

    model_config = SettingsConfigDict(case_sensitive=False)

    provider: StorageProviderName = Field(validation_alias="STORAGE_PROVIDER")
    s3_bucket: str | None = Field(default=None, validation_alias="S3_BUCKET")
    s3_region: str | None = Field(default=None, validation_alias="S3_REGION")
    s3_endpoint: str | None = Field(default=None, validation_alias="S3_ENDPOINT")
