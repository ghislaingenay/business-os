"""Business logic for the mediated (small-file) upload path (TD-002 §3, §6)."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from shared.storage.provider import StorageProvider
from upload.models import File
from upload.schemas import FileMetadata
from upload.validator import UploadValidator, sanitize_filename

_READ_CHUNK_SIZE = 64 * 1024


class FileRepositoryProtocol(Protocol):
    """Persistence operations `UploadService` needs from the `files` table."""

    async def save(self, file: File) -> File:
        ...


class ByteStream(Protocol):
    """Minimal async-readable shape `UploadService` needs from an upload body.

    `fastapi.UploadFile` satisfies this structurally; declared here (rather than
    importing `UploadFile`) so the domain stays framework-independent.
    """

    async def read(self, size: int = -1) -> bytes:
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
        mime_type: str,
        stream: ByteStream,
    ) -> FileMetadata:
        """Validate, store, and persist a small file (TD-002 §6 mediated flow)."""
        safe_filename = sanitize_filename(filename)
        content = await self._read_bounded(stream)
        self.validator.validate_for_mediated_upload(safe_filename, len(content), mime_type)

        storage_key = self._generate_storage_key(safe_filename)
        await self.storage.upload(storage_key, content, metadata={"mime_type": mime_type})

        saved = await self.repository.save(
            File(
                storage_key=storage_key,
                filename=safe_filename,
                size=len(content),
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

    async def _read_bounded(self, stream: ByteStream) -> bytes:
        """Read at most one `_READ_CHUNK_SIZE` chunk past `max_small_file_size`.

        Stops requesting further chunks once the running total exceeds the
        mediated-upload threshold, so an oversized upload is rejected by
        `validate_for_mediated_upload` after reading only ~`max_small_file_size +
        _READ_CHUNK_SIZE` bytes, never the full body (TD-002 §10).
        """
        max_size = self.validator.settings.max_small_file_size
        chunks: list[bytes] = []
        total = 0
        while total <= max_size:
            chunk = await stream.read(_READ_CHUNK_SIZE)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        return b"".join(chunks)

    @staticmethod
    def _generate_storage_key(filename: str) -> str:
        """Build `originals/{YYYY}/{MM}/{DD}/{UUID}.{ext}` (TD-002 §10)."""
        today = datetime.now(UTC)
        extension = Path(filename).suffix
        return f"originals/{today:%Y}/{today:%m}/{today:%d}/{uuid.uuid4()}{extension}"
