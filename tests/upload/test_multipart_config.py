from upload.multipart_config import MultipartSettings


def test_defaults_when_no_env_vars_set(monkeypatch) -> None:
    monkeypatch.delenv("MULTIPART_PART_SIZE", raising=False)
    monkeypatch.delenv("MULTIPART_SESSION_TTL", raising=False)
    monkeypatch.delenv("MULTIPART_PRESIGNED_URL_TTL", raising=False)
    monkeypatch.delenv("MULTIPART_MIN_SIZE", raising=False)

    settings = MultipartSettings()

    assert settings.part_size == 10_485_760
    assert settings.session_ttl_seconds == 86_400
    assert settings.presigned_url_ttl_seconds == 900
    assert settings.min_multipart_size == 104_857_600


def test_part_size_read_from_env(monkeypatch) -> None:
    monkeypatch.setenv("MULTIPART_PART_SIZE", "5242880")

    settings = MultipartSettings()

    assert settings.part_size == 5_242_880


def test_session_ttl_read_from_env(monkeypatch) -> None:
    monkeypatch.setenv("MULTIPART_SESSION_TTL", "3600")

    settings = MultipartSettings()

    assert settings.session_ttl_seconds == 3600


def test_min_multipart_size_read_from_env(monkeypatch) -> None:
    monkeypatch.setenv("MULTIPART_MIN_SIZE", "52428800")

    settings = MultipartSettings()

    assert settings.min_multipart_size == 52_428_800
