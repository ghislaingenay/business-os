"""Configuration for variant generation quality/size and retry policy (TD-004 §6, §8)."""

from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class VariantSettings(BaseSettings):
    """Env-driven variant-generation config.

    `retry_delays_seconds` are the exponential-backoff delays for the 1st,
    2nd, and 3rd retry attempts after an initial failure (FR-3: "3 attempts
    with exponential backoff (1s, 5s, 25s)").
    """

    model_config = SettingsConfigDict(case_sensitive=False, populate_by_name=True)

    web_optimized_quality: int = Field(default=85, validation_alias="VARIANT_WEBP_QUALITY")
    thumbnail_size: int = Field(default=256, validation_alias="VARIANT_THUMBNAIL_SIZE")
    thumbnail_quality: int = Field(default=80, validation_alias="VARIANT_THUMBNAIL_QUALITY")
    job_timeout_seconds: int = Field(default=60, validation_alias="VARIANT_JOB_TIMEOUT")
    retry_delays_seconds: Annotated[tuple[int, ...], NoDecode] = Field(
        default=(1, 5, 25), validation_alias="VARIANT_RETRY_DELAYS_SECONDS"
    )
    generated_mime_types: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("image/jpeg", "image/png", "image/gif"),
        validation_alias="VARIANT_GENERATED_MIME_TYPES",
    )

    @field_validator("retry_delays_seconds", mode="before")
    @classmethod
    def _split_delays(cls, value: str | tuple[int, ...]) -> tuple[int, ...]:
        if isinstance(value, str):
            return tuple(int(item.strip()) for item in value.split(",") if item.strip())
        return value

    @field_validator("generated_mime_types", mode="before")
    @classmethod
    def _split_mime_types(cls, value: str | tuple[str, ...]) -> tuple[str, ...]:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value
