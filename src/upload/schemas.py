"""API-boundary Pydantic schemas for the upload domain."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class FileMetadata(BaseModel):
    """Response shape returned by both upload paths (FR-5)."""

    file_id: uuid.UUID
    storage_key: str
    filename: str
    size: int
    mime_type: str
    upload_url: str
    created_at: datetime
