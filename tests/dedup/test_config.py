from dedup.config import DedupSettings


def test_defaults_when_no_env_vars_set(monkeypatch) -> None:
    for var in (
        "DEDUP_ENABLED",
        "DEDUP_CACHE_TTL",
        "DEDUP_LOCK_TTL",
        "DEDUP_LOCK_RETRY_MAX",
        "DEDUP_LOCK_RETRY_DELAY_MS",
        "DEDUP_DB_QUERY_TIMEOUT",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = DedupSettings()

    assert settings.enabled is True
    assert settings.cache_ttl_seconds == 86400
    assert settings.lock_ttl_seconds == 10
    assert settings.lock_retry_max == 3
    assert settings.lock_retry_delay_ms == 50
    assert settings.db_query_timeout_seconds == 5


def test_enabled_read_from_env(monkeypatch) -> None:
    monkeypatch.setenv("DEDUP_ENABLED", "false")

    assert DedupSettings().enabled is False


def test_cache_ttl_read_from_env(monkeypatch) -> None:
    monkeypatch.setenv("DEDUP_CACHE_TTL", "3600")

    assert DedupSettings().cache_ttl_seconds == 3600
