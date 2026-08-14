"""Configuration for deduplication cache TTL and lock retry policy (TD-003 §12)."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DedupSettings(BaseSettings):
    """Env-driven dedup config."""

    # `populate_by_name=True`: unlike `upload.config.UploadSettings`, whose
    # field names happen to equal their env var aliases modulo case (so
    # `case_sensitive=False` alone lets tests construct it by field name),
    # this settings class deliberately keeps shorter field names than their
    # `DEDUP_`-prefixed env vars (e.g. `enabled` vs `DEDUP_ENABLED`) — those
    # aren't the same string under any casing, so both must be accepted
    # explicitly for plain-field-name construction (as tests do) to work.
    model_config = SettingsConfigDict(case_sensitive=False, populate_by_name=True)

    enabled: bool = Field(default=True, validation_alias="DEDUP_ENABLED")
    cache_ttl_seconds: int = Field(default=86400, validation_alias="DEDUP_CACHE_TTL")
    lock_ttl_seconds: int = Field(default=10, validation_alias="DEDUP_LOCK_TTL")
    lock_retry_max: int = Field(default=3, validation_alias="DEDUP_LOCK_RETRY_MAX")
    lock_retry_delay_ms: int = Field(default=50, validation_alias="DEDUP_LOCK_RETRY_DELAY_MS")
    db_query_timeout_seconds: int = Field(default=5, validation_alias="DEDUP_DB_QUERY_TIMEOUT")
