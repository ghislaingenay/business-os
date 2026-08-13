"""Configuration for upload size limits and allowed file types (TD-002)."""

from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class UploadSettings(BaseSettings):
    """Env-driven upload config.

    `max_small_file_size` is the size threshold (in bytes) below which files
    go through the mediated `/upload` path; above it, files use the presigned
    URL path.
    """

    model_config = SettingsConfigDict(case_sensitive=False)

    max_small_file_size: int = Field(default=2_097_152, validation_alias="MAX_SMALL_FILE_SIZE")
    presigned_url_ttl: int = Field(default=900, validation_alias="PRESIGNED_URL_TTL")
    allowed_file_types: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("image/jpeg", "image/png", "image/gif", "video/mp4"),
        validation_alias="ALLOWED_FILE_TYPES",
    )

    @field_validator("allowed_file_types", mode="before")
    @classmethod
    def _split_csv(cls, value: str | tuple[str, ...]) -> tuple[str, ...]:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value
