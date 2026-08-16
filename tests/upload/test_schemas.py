import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from upload.schemas import FileMetadata, FinalizeUploadRequest, InitiateUploadRequest, PartETag

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


def test_initiate_upload_request_multipart_defaults_to_false() -> None:
    request = InitiateUploadRequest(filename="video.mp4", size=5_000_000, mime_type="video/mp4")

    assert request.multipart is False


def test_initiate_upload_request_accepts_multipart_flag() -> None:
    request = InitiateUploadRequest(
        filename="video.mp4", size=500_000_000, mime_type="video/mp4", multipart=True
    )

    assert request.multipart is True


def test_finalize_upload_request_accepts_etag_only() -> None:
    request = FinalizeUploadRequest(upload_id=_FILE_ID, etag="abc123")

    assert request.etag == "abc123"
    assert request.parts is None


def test_finalize_upload_request_accepts_parts_only() -> None:
    request = FinalizeUploadRequest(
        upload_id=_FILE_ID, parts=[PartETag(part_number=1, etag="abc123")]
    )

    assert request.parts == [PartETag(part_number=1, etag="abc123")]
    assert request.etag is None


def test_finalize_upload_request_rejects_neither_etag_nor_parts() -> None:
    with pytest.raises(ValidationError):
        FinalizeUploadRequest(upload_id=_FILE_ID)


def test_finalize_upload_request_rejects_both_etag_and_parts() -> None:
    with pytest.raises(ValidationError):
        FinalizeUploadRequest(
            upload_id=_FILE_ID,
            etag="abc123",
            parts=[PartETag(part_number=1, etag="abc123")],
        )
