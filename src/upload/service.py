"""Business logic for the upload domain: mediated (TD-002 §3, §6) and presigned
(TD-002 §5, §6) flows.
"""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from shared.storage.exceptions import StorageObjectNotFoundError
from shared.storage.provider import StorageProvider
from upload.exceptions import (
    EtagMismatchError,
    PresignedUrlExpiredError,
    UploadIncompleteError,
    UploadNotFoundError,
)
from upload.models import File, UploadSession
from upload.schemas import FileMetadata, UploadSessionMetadata
from upload.validator import UploadValidator, sanitize_filename

_READ_CHUNK_SIZE = 64 * 1024
_FINALIZE_INSTRUCTIONS = (
    "PUT file bytes to presigned_url, then call /upload/finalize with upload_id"
)


class FileRepositoryProtocol(Protocol):
    """Persistence operations `UploadService` needs from the `files` table."""

    async def save(self, file: File) -> File:
        ...


class UploadSessionRepositoryProtocol(Protocol):
    """Persistence operations `UploadService` needs from the `upload_sessions` table."""

    async def save(self, upload_session: UploadSession) -> UploadSession:
        ...

    async def find_active_by_id(self, upload_id: uuid.UUID) -> UploadSession | None:
        ...

    async def mark_finalized(self, upload_session: UploadSession) -> None:
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
        session_repository: UploadSessionRepositoryProtocol,
        presigned_url_ttl: int,
    ) -> None:
        self.validator = validator
        self.storage = storage
        self.repository = repository
        self.session_repository = session_repository
        self.presigned_url_ttl = presigned_url_ttl

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
            saved.storage_key, "GET", self.presigned_url_ttl
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

    async def initiate_large_upload(
        self, filename: str, size: int, mime_type: str
    ) -> UploadSessionMetadata:
        """Validate and register a large file, returning a presigned PUT URL
        for the client to upload directly to storage (TD-002 §6 presigned flow).
        """
        safe_filename = sanitize_filename(filename)
        self.validator.validate_for_presigned_upload(safe_filename, size, mime_type)

        storage_key = self._generate_storage_key(safe_filename)
        presigned_url = await self.storage.generate_presigned_url(
            storage_key, "PUT", self.presigned_url_ttl
        )
        expires_at = datetime.now(UTC) + timedelta(seconds=self.presigned_url_ttl)

        saved = await self.session_repository.save(
            UploadSession(
                filename=safe_filename,
                size=size,
                mime_type=mime_type,
                presigned_url=presigned_url,
                storage_key=storage_key,
                expires_at=expires_at,
                finalized=False,
            )
        )

        return UploadSessionMetadata(
            upload_id=saved.upload_id,
            presigned_url=saved.presigned_url,
            storage_key=saved.storage_key,
            expires_at=saved.expires_at,
            instructions=_FINALIZE_INSTRUCTIONS,
        )

    async def finalize_large_upload(self, upload_id: uuid.UUID, etag: str) -> FileMetadata:
        """Verify a presigned-URL upload completed, then persist it as a `File`
        (TD-002 §6 presigned flow).

        Resolves TD-002 §13's ETag open question: the client-supplied `etag`
        (captured from its direct PUT response) is checked against what
        `storage.head()` actually reports before the upload is accepted, and
        the storage-verified value is what gets persisted to `files.etag` —
        not the client-supplied one, since storage is the ground truth.
        """
        session = await self.session_repository.find_active_by_id(upload_id)
        if session is None:
            raise UploadNotFoundError(upload_id)

        if session.expires_at < datetime.now(UTC):
            raise PresignedUrlExpiredError(upload_id, session.expires_at)

        try:
            storage_metadata = await self.storage.head(session.storage_key)
        except StorageObjectNotFoundError as exc:
            raise UploadIncompleteError(session.storage_key) from exc

        if storage_metadata.etag != etag:
            raise EtagMismatchError(expected=etag, actual=storage_metadata.etag)

        saved = await self.repository.save(
            File(
                storage_key=session.storage_key,
                filename=session.filename,
                size=storage_metadata.size,
                mime_type=session.mime_type,
                upload_strategy="presigned",
                etag=storage_metadata.etag,
            )
        )
        await self.session_repository.mark_finalized(session)

        download_url = await self.storage.generate_presigned_url(
            saved.storage_key, "GET", self.presigned_url_ttl
        )

        return FileMetadata(
            file_id=saved.file_id,
            storage_key=saved.storage_key,
            filename=saved.filename,
            size=saved.size,
            mime_type=saved.mime_type,
            upload_url=download_url,
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
