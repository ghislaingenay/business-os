import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from upload.schemas import FileMetadata

_FILE_ID = uuid.uuid4()
_CREATED_AT = datetime(2026, 8, 11, 10, 30, 0, tzinfo=UTC)


_SHA256_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_file_metadata_round_trips_expected_fields() -> None:
    metadata = FileMetadata(
        file_id=_FILE_ID,
        storage_key="originals/2026/08/11/file.jpg",
        filename="profile.jpg",
        size=1_048_576,
        mime_type="image/jpeg",
        sha256_hash=_SHA256_HASH,
        upload_url="https://cdn.example.com/originals/2026/08/11/file.jpg",
        web_optimized_url=None,
        thumbnail_url=None,
        created_at=_CREATED_AT,
    )

    assert metadata.file_id == _FILE_ID
    assert metadata.size == 1_048_576
    assert metadata.sha256_hash == _SHA256_HASH
    assert metadata.created_at == _CREATED_AT


def test_file_metadata_allows_null_sha256_hash() -> None:
    """Legacy files uploaded before FEAT-003 have no hash on record (TD-003 §4)."""
    metadata = FileMetadata(
        file_id=_FILE_ID,
        storage_key="originals/2026/08/11/file.jpg",
        filename="profile.jpg",
        size=1_048_576,
        mime_type="image/jpeg",
        sha256_hash=None,
        upload_url="https://cdn.example.com/originals/2026/08/11/file.jpg",
        web_optimized_url=None,
        thumbnail_url=None,
        created_at=_CREATED_AT,
    )

    assert metadata.sha256_hash is None


def test_file_metadata_parses_iso8601_created_at_string() -> None:
    metadata = FileMetadata(
        file_id=_FILE_ID,
        storage_key="originals/2026/08/11/file.jpg",
        filename="profile.jpg",
        size=1_048_576,
        mime_type="image/jpeg",
        sha256_hash=_SHA256_HASH,
        upload_url="https://cdn.example.com/originals/2026/08/11/file.jpg",
        web_optimized_url=None,
        thumbnail_url=None,
        created_at="2026-08-11T10:30:00Z",
    )

    assert metadata.created_at == _CREATED_AT


def test_file_metadata_requires_all_fields() -> None:
    with pytest.raises(ValidationError):
        FileMetadata(file_id=_FILE_ID)
