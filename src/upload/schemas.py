"""API-boundary Pydantic schemas for the upload domain."""

import uuid
from datetime import datetime

from pydantic import BaseModel


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
    """Request body for `POST /upload/initiate` (TD-002 §5)."""

    filename: str
    size: int
    mime_type: str


class UploadSessionMetadata(BaseModel):
    """Response shape for `POST /upload/initiate` (TD-002 §5)."""

    upload_id: uuid.UUID
    presigned_url: str
    storage_key: str
    expires_at: datetime
    instructions: str


class FinalizeUploadRequest(BaseModel):
    """Request body for `POST /upload/finalize` (TD-002 §5).

    `etag` is verified against `storage.head()`'s reported ETag in
    `UploadService.finalize_large_upload` and persisted to `files.etag` —
    resolves TD-002 §13's open question on ETag integrity verification.
    """

    upload_id: uuid.UUID
    etag: str
