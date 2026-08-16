"""API-boundary Pydantic schemas for the upload domain."""

import uuid
from datetime import datetime

from pydantic import BaseModel, model_validator


class FileMetadata(BaseModel):
    """Response shape returned by both upload paths (FR-5).

    Reused as-is for `/upload/finalize`'s response — FR-5 requires both paths
    to return an identical shape, so this isn't duplicated for the large-file
    path.

    `web_optimized_url`/`thumbnail_url` are `None` right after upload since
    generation happens asynchronously (TD-004); they're populated by
    `variants.repository.VariantRepository.update_variants` once the arq
    worker finishes (FR-4: "API response includes variant URLs if available").
    """

    file_id: uuid.UUID
    storage_key: str
    filename: str
    size: int
    mime_type: str
    sha256_hash: str | None
    upload_url: str
    web_optimized_url: str | None
    thumbnail_url: str | None
    created_at: datetime


class InitiateUploadRequest(BaseModel):
    """Request body for `POST /upload/initiate` (TD-002 §5; `multipart` added
    by TD-005 §4 for files large enough to warrant chunked upload).
    """

    filename: str
    size: int
    mime_type: str
    multipart: bool = False


class UploadSessionMetadata(BaseModel):
    """Response shape for `POST /upload/initiate` (TD-002 §5)."""

    upload_id: uuid.UUID
    presigned_url: str
    storage_key: str
    expires_at: datetime
    instructions: str


class MultipartUploadSessionMetadata(BaseModel):
    """Response shape for `POST /upload/initiate` when `multipart: true` (TD-005 §4)."""

    upload_id: uuid.UUID
    part_size: int
    total_parts: int
    storage_key: str
    part_upload_urls: list[str]
    expires_at: datetime


class MultipartUploadStatus(BaseModel):
    """Response shape for `GET /upload/{upload_id}/status` (TD-005 §4, FR-2)."""

    upload_id: uuid.UUID
    storage_key: str
    total_parts: int
    completed_parts: list[int]
    missing_parts: list[int]
    progress_percentage: float
    bytes_uploaded: int
    eta_seconds: int | None


class RetryPartRequest(BaseModel):
    """Request body for `POST /upload/{upload_id}/retry-part` (TD-005 §4, FR-3)."""

    part_number: int


class RetryPartResponse(BaseModel):
    """Response shape for `POST /upload/{upload_id}/retry-part` (TD-005 §4)."""

    part_number: int
    presigned_url: str
    expires_at: datetime


class PartETag(BaseModel):
    """A completed part's number and storage-reported ETag, as submitted by
    the client to `/upload/finalize` (TD-005 §4, FR-4).
    """

    part_number: int
    etag: str


class FinalizeUploadRequest(BaseModel):
    """Request body for `POST /upload/finalize`.

    `etag` (TD-002 §5) finalizes a single-PUT presigned upload; `parts`
    (TD-005 §4) finalizes a multipart upload. Exactly one of the two must be
    supplied — which one determines the finalize path taken (TD-005 §4).

    `etag` is verified against `storage.head()`'s reported ETag in
    `UploadService.finalize_large_upload` and persisted to `files.etag` —
    resolves TD-002 §13's open question on ETag integrity verification.
    """

    upload_id: uuid.UUID
    etag: str | None = None
    parts: list[PartETag] | None = None

    @model_validator(mode="after")
    def _validate_exactly_one_finalize_mode(self) -> "FinalizeUploadRequest":
        if (self.etag is None) == (self.parts is None):
            raise ValueError("Exactly one of 'etag' or 'parts' must be provided")
        return self
