"""Business logic for the mediated (small-file) upload path (TD-002 §3, §6)."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from shared.storage.provider import StorageProvider
from upload.models import File
from upload.schemas import FileMetadata
from upload.validator import UploadValidator


class FileRepositoryProtocol(Protocol):
    """Persistence operations `UploadService` needs from the `files` table."""

    async def save(self, file: File) -> File:
        ...


class UploadService:
    """Orchestrates validation, storage, and metadata persistence for uploads."""

    def __init__(
        self,
        validator: UploadValidator,
        storage: StorageProvider,
        repository: FileRepositoryProtocol,
        download_url_ttl: int,
    ) -> None:
        self.validator = validator
        self.storage = storage
        self.repository = repository
        self.download_url_ttl = download_url_ttl

    async def upload_small_file(
        self,
        filename: str,
        size: int,
        mime_type: str,
        content: bytes,
    ) -> FileMetadata:
        """Validate, store, and persist a small file (TD-002 §6 mediated flow)."""
        self.validator.validate_for_mediated_upload(filename, size, mime_type)

        storage_key = self._generate_storage_key(filename)
        await self.storage.upload(storage_key, content, metadata={"mime_type": mime_type})

        saved = await self.repository.save(
            File(
                storage_key=storage_key,
                filename=filename,
                size=size,
                mime_type=mime_type,
                upload_strategy="mediated",
            )
        )

        upload_url = await self.storage.generate_presigned_url(
            saved.storage_key, "GET", self.download_url_ttl
        )

        return FileMetadata(
            file_id=saved.file_id,
            storage_key=saved.storage_key,
            filename=saved.filename,
            size=saved.size,
            mime_type=saved.mime_type,
            upload_url=upload_url,
            created_at=saved.created_at,
        )

    @staticmethod
    def _generate_storage_key(filename: str) -> str:
        """Build `originals/{YYYY}/{MM}/{DD}/{UUID}.{ext}` (TD-002 §10)."""
        today = datetime.now(UTC)
        extension = Path(filename).suffix
        return f"originals/{today:%Y}/{today:%m}/{today:%d}/{uuid.uuid4()}{extension}"
