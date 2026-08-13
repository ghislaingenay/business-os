from upload.config import UploadSettings


def test_defaults_when_no_env_vars_set(monkeypatch) -> None:
    monkeypatch.delenv("MAX_SMALL_FILE_SIZE", raising=False)
    monkeypatch.delenv("ALLOWED_FILE_TYPES", raising=False)

    settings = UploadSettings()

    assert settings.max_small_file_size == 2_097_152
    assert settings.allowed_file_types == (
        "image/jpeg",
        "image/png",
        "image/gif",
        "video/mp4",
    )


def test_max_small_file_size_read_from_env(monkeypatch) -> None:
    monkeypatch.setenv("MAX_SMALL_FILE_SIZE", "1048576")

    settings = UploadSettings()

    assert settings.max_small_file_size == 1_048_576


def test_allowed_file_types_parsed_from_csv_env(monkeypatch) -> None:
    monkeypatch.setenv("ALLOWED_FILE_TYPES", "image/jpeg, application/pdf")

    settings = UploadSettings()

    assert settings.allowed_file_types == ("image/jpeg", "application/pdf")
