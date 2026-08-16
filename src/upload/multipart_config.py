"""Configuration for multipart upload chunking, session TTL, and part URL TTL
(TD-005 §7).
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MultipartSettings(BaseSettings):
    """Env-driven multipart-upload config.

    `min_multipart_size` is FEAT-005's own threshold (Goals: "Support chunked
    uploads for files >100MB") — distinct from `UploadSettings.max_small_file_size`,
    which is the existing mediated-vs-presigned boundary from FEAT-002. A file
    can be large enough for the presigned single-PUT path (>2MB) without being
    large enough to justify multipart (>100MB).
    """

    model_config = SettingsConfigDict(case_sensitive=False, populate_by_name=True)

    part_size: int = Field(default=10_485_760, validation_alias="MULTIPART_PART_SIZE")
    session_ttl_seconds: int = Field(default=86_400, validation_alias="MULTIPART_SESSION_TTL")
    presigned_url_ttl_seconds: int = Field(
        default=900, validation_alias="MULTIPART_PRESIGNED_URL_TTL"
    )
    min_multipart_size: int = Field(default=104_857_600, validation_alias="MULTIPART_MIN_SIZE")
