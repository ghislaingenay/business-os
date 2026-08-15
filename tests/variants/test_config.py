from variants.config import VariantSettings

_ENV_VARS = (
    "VARIANT_WEBP_QUALITY",
    "VARIANT_THUMBNAIL_SIZE",
    "VARIANT_THUMBNAIL_QUALITY",
    "VARIANT_JOB_TIMEOUT",
    "VARIANT_RETRY_DELAYS_SECONDS",
    "VARIANT_GENERATED_MIME_TYPES",
)


def test_defaults_when_no_env_vars_set(monkeypatch) -> None:
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    settings = VariantSettings()

    assert settings.web_optimized_quality == 85
    assert settings.thumbnail_size == 256
    assert settings.thumbnail_quality == 80
    assert settings.job_timeout_seconds == 60
    assert settings.retry_delays_seconds == (1, 5, 25)
    assert settings.generated_mime_types == ("image/jpeg", "image/png", "image/gif")


def test_web_optimized_quality_read_from_env(monkeypatch) -> None:
    monkeypatch.setenv("VARIANT_WEBP_QUALITY", "90")

    assert VariantSettings().web_optimized_quality == 90


def test_retry_delays_seconds_parsed_from_csv_env(monkeypatch) -> None:
    monkeypatch.setenv("VARIANT_RETRY_DELAYS_SECONDS", "2, 10, 30")

    assert VariantSettings().retry_delays_seconds == (2, 10, 30)


def test_generated_mime_types_parsed_from_csv_env(monkeypatch) -> None:
    monkeypatch.setenv("VARIANT_GENERATED_MIME_TYPES", "image/jpeg, image/heic")

    assert VariantSettings().generated_mime_types == ("image/jpeg", "image/heic")
