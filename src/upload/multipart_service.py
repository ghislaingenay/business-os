"""Business logic for chunked multipart uploads (TD-005 §2, §5).

Split out from `upload.service` rather than folded into `UploadService`
per `context/coding-standards.md` §4 ("split service.py into multiple
service modules when it becomes large") — multipart's session lifecycle
(initiate/status/retry-part/finalize) is substantial enough on its own to
warrant its own class, while still sharing `UploadValidator`,
`generate_storage_key`, and the `files`/dedup/job-queue collaborators that
`UploadService` already uses.
"""

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

from redis.exceptions import RedisError

from dedup.hasher import hash_stream
from dedup.service import DedupCheckResult
from shared.logging.config import setup_logger
from shared.logging.metrics import log_upload_complete
from shared.logging.middleware import get_request_id
from shared.storage.provider import CompletedPart, StorageProvider
from upload.exceptions import (
    IncompletePartsError,
    InvalidPartNumberError,
    MultipartSessionExpiredError,
    MultipartSessionNotFoundError,
)
from upload.models import File, MultipartSession
from upload.multipart_config import MultipartSettings
from upload.schemas import (
    FileMetadata,
    MultipartUploadSessionMetadata,
    MultipartUploadStatus,
    PartETag,
    RetryPartResponse,
)
from upload.validator import UploadValidator, generate_storage_key, sanitize_filename

logger = setup_logger(__name__)

_GENERATE_VARIANTS_JOB = "generate_variants"
_UPLOAD_STRATEGY = "multipart"


class MultipartSessionRepositoryProtocol(Protocol):
    """Persistence operations `MultipartService` needs from the
    `multipart_sessions` table.
    """

    async def save(self, multipart_session: MultipartSession) -> MultipartSession:
        ...

    async def find_active_by_id(self, upload_id: uuid.UUID) -> MultipartSession | None:
        ...

    async def mark_finalized(self, multipart_session: MultipartSession) -> None:
        ...

    async def find_expired_unfinalized(self, now: datetime) -> list[MultipartSession]:
        ...

    async def delete(self, multipart_session: MultipartSession) -> None:
        ...


class FileRepositoryProtocol(Protocol):
    """Persistence operations `MultipartService` needs from the `files` table."""

    async def save(self, file: File) -> File:
        ...


class DedupServiceProtocol(Protocol):
    """Deduplication operations `MultipartService` needs from `dedup.service.DedupService`."""

    async def check(self, sha256_hash: str, file_size: int) -> DedupCheckResult:
        ...

    async def finish(self, sha256_hash: str, storage_key: str, result: DedupCheckResult) -> None:
        ...


class JobQueueProtocol(Protocol):
    """Queueing operations `MultipartService` needs to enqueue variant generation."""

    async def enqueue_job(self, function: str, *args: object) -> object | None:
        ...


class MultipartService:
    """Orchestrates multipart session lifecycle: initiate, status, part
    retry, finalize, and abandoned-session cleanup (FR-1 through FR-5).
    """

    def __init__(
        self,
        *,
        validator: UploadValidator,
        storage: StorageProvider,
        repository: FileRepositoryProtocol,
        session_repository: MultipartSessionRepositoryProtocol,
        dedup_service: DedupServiceProtocol,
        job_queue: JobQueueProtocol,
        settings: MultipartSettings,
        presigned_url_ttl: int,
    ) -> None:
        self.validator = validator
        self.storage = storage
        self.repository = repository
        self.session_repository = session_repository
        self.dedup_service = dedup_service
        self.job_queue = job_queue
        self.settings = settings
        self.presigned_url_ttl = presigned_url_ttl

    async def initiate(
        self, filename: str, size: int, mime_type: str
    ) -> MultipartUploadSessionMetadata:
        """Create a multipart session and return one presigned PUT URL per
        part (FR-1).
        """
        safe_filename = sanitize_filename(filename)
        self.validator.validate_for_multipart_upload(
            safe_filename, size, mime_type, self.settings.min_multipart_size
        )

        storage_key = generate_storage_key(safe_filename)
        storage_upload_id = await self.storage.create_multipart_upload(storage_key)

        total_parts = -(-size // self.settings.part_size)  # ceil division
        part_upload_urls = list(
            await asyncio.gather(
                *[
                    self.storage.generate_part_upload_url(
                        storage_key,
                        storage_upload_id,
                        part_number,
                        self.settings.presigned_url_ttl_seconds,
                    )
                    for part_number in range(1, total_parts + 1)
                ]
            )
        )

        expires_at = datetime.now(UTC) + timedelta(seconds=self.settings.session_ttl_seconds)

        saved = await self.session_repository.save(
            MultipartSession(
                storage_upload_id=storage_upload_id,
                filename=safe_filename,
                size=size,
                mime_type=mime_type,
                part_size=self.settings.part_size,
                total_parts=total_parts,
                storage_key=storage_key,
                expires_at=expires_at,
                finalized=False,
            )
        )

        return MultipartUploadSessionMetadata(
            upload_id=saved.upload_id,
            part_size=saved.part_size,
            total_parts=saved.total_parts,
            storage_key=saved.storage_key,
            part_upload_urls=part_upload_urls,
            expires_at=saved.expires_at,
        )

    async def get_status(self, upload_id: uuid.UUID) -> MultipartUploadStatus:
        """Report per-part progress by asking storage which parts have
        actually landed (FR-2).
        """
        session = await self._find_active_session(upload_id)

        parts = await self.storage.list_parts(session.storage_key, session.storage_upload_id)
        completed_parts = sorted(part.part_number for part in parts)
        completed_set = set(completed_parts)
        missing_parts = [
            part_number
            for part_number in range(1, session.total_parts + 1)
            if part_number not in completed_set
        ]
        bytes_uploaded = sum(part.size for part in parts)
        progress_percentage = (
            round(len(completed_parts) / session.total_parts * 100, 2)
            if session.total_parts
            else 0.0
        )

        return MultipartUploadStatus(
            upload_id=session.upload_id,
            storage_key=session.storage_key,
            total_parts=session.total_parts,
            completed_parts=completed_parts,
            missing_parts=missing_parts,
            progress_percentage=progress_percentage,
            bytes_uploaded=bytes_uploaded,
            eta_seconds=self._estimate_eta_seconds(session, bytes_uploaded),
        )

    async def retry_part(self, upload_id: uuid.UUID, part_number: int) -> RetryPartResponse:
        """Issue a fresh presigned URL for a single part (FR-3)."""
        session = await self._find_active_session(upload_id)

        if not 1 <= part_number <= session.total_parts:
            raise InvalidPartNumberError(part_number, session.total_parts)

        presigned_url = await self.storage.generate_part_upload_url(
            session.storage_key,
            session.storage_upload_id,
            part_number,
            self.settings.presigned_url_ttl_seconds,
        )
        expires_at = datetime.now(UTC) + timedelta(seconds=self.settings.presigned_url_ttl_seconds)

        return RetryPartResponse(
            part_number=part_number, presigned_url=presigned_url, expires_at=expires_at
        )

    async def finalize(self, upload_id: uuid.UUID, parts: list[PartETag]) -> FileMetadata:
        """Complete a multipart upload once the client reports every part's
        ETag (FR-4).

        Hash is calculated after all parts are uploaded, not incrementally
        per part — resolves FEAT-005 §8's open question, per its own §6
        Dependencies note ("hash calculated after all parts uploaded").
        """
        started = time.monotonic()
        session = await self._find_active_session(upload_id)

        if session.expires_at < datetime.now(UTC):
            raise MultipartSessionExpiredError(upload_id, session.expires_at)

        for part in parts:
            if not 1 <= part.part_number <= session.total_parts:
                raise InvalidPartNumberError(part.part_number, session.total_parts)

        parts_by_number = {part.part_number: part.etag for part in parts}
        expected_numbers = list(range(1, session.total_parts + 1))
        missing = sorted(set(expected_numbers) - set(parts_by_number))

        if missing:
            raise IncompletePartsError(upload_id, missing)

        completed_parts = [
            CompletedPart(part_number=part.part_number, etag=parts_by_number[part.part_number])
            for part in parts
        ]
        await self.storage.complete_multipart_upload(
            session.storage_key, session.storage_upload_id, completed_parts
        )

        storage_metadata = await self.storage.head(session.storage_key)
        sha256_hash = await hash_stream(self.storage.download(session.storage_key))
        dedup_result = await self.dedup_service.check(sha256_hash, storage_metadata.size)

        async def _persist_finalized_file() -> File:
            # Same same-transaction rationale as
            # `UploadService.finalize_large_upload._persist_finalized_file`:
            # `mark_finalized` only mutates in-memory, `repository.save`'s
            # commit persists both together.
            await self.session_repository.mark_finalized(session)
            return await self.repository.save(
                File(
                    storage_key=session.storage_key,
                    filename=session.filename,
                    size=storage_metadata.size,
                    mime_type=session.mime_type,
                    sha256_hash=sha256_hash,
                    upload_strategy=_UPLOAD_STRATEGY,
                    etag=storage_metadata.etag,
                )
            )

        _, saved = await asyncio.gather(
            self.dedup_service.finish(sha256_hash, session.storage_key, dedup_result),
            _persist_finalized_file(),
        )

        await self._enqueue_variant_generation(saved)

        download_url = await self.storage.generate_presigned_url(
            saved.storage_key, "GET", self.presigned_url_ttl
        )

        log_upload_complete(
            file_id=str(saved.file_id),
            size=saved.size,
            strategy=_UPLOAD_STRATEGY,
            duration_ms=(time.monotonic() - started) * 1000,
        )

        return FileMetadata(
            file_id=saved.file_id,
            storage_key=saved.storage_key,
            filename=saved.filename,
            size=saved.size,
            mime_type=saved.mime_type,
            sha256_hash=saved.sha256_hash,
            upload_url=download_url,
            web_optimized_url=saved.web_optimized_url,
            thumbnail_url=saved.thumbnail_url,
            created_at=saved.created_at,
        )

    async def _find_active_session(self, upload_id: uuid.UUID) -> MultipartSession:
        session = await self.session_repository.find_active_by_id(upload_id)
        if session is None:
            raise MultipartSessionNotFoundError(upload_id)
        return session

    async def _enqueue_variant_generation(self, file: File) -> None:
        """Enqueue the async variant-generation job, matching
        `UploadService._enqueue_variant_generation`'s fail-open Redis
        handling so both finalize paths behave identically once a `File`
        row exists.
        """
        try:
            await self.job_queue.enqueue_job(
                _GENERATE_VARIANTS_JOB,
                str(file.file_id),
                file.storage_key,
                file.mime_type,
                get_request_id(),
            )
        except RedisError:
            logger.warning("variant_job_enqueue_failed", file_id=str(file.file_id))

    @staticmethod
    def _estimate_eta_seconds(session: MultipartSession, bytes_uploaded: int) -> int | None:
        """Heuristic ETA from the session's own age and bytes uploaded so far.

        TD-005 doesn't define a per-request telemetry table to track real
        upload throughput, so this uses elapsed wall-clock time since
        `initiate` as the only available rate signal. Returns `None` when a
        rate can't be estimated yet (no bytes landed) or the upload is
        already complete (no remaining bytes to estimate against).
        """
        if bytes_uploaded <= 0 or bytes_uploaded >= session.size:
            return None

        elapsed_seconds = (datetime.now(UTC) - session.created_at).total_seconds()
        if elapsed_seconds <= 0:
            return None

        bytes_per_second = bytes_uploaded / elapsed_seconds
        remaining_bytes = session.size - bytes_uploaded
        return round(remaining_bytes / bytes_per_second)


class MultipartCleanupService:
    """Aborts and deletes multipart sessions past their 24h TTL (FR-5).

    Kept separate from `MultipartService`: cleanup only needs storage and
    the session repository, while `MultipartService`'s other methods also
    need the `files` repository, dedup service, and job queue — the arq
    cron task that runs this shouldn't have to wire dependencies it never
    uses just to construct one service object.
    """

    def __init__(
        self,
        storage: StorageProvider,
        session_repository: MultipartSessionRepositoryProtocol,
    ) -> None:
        self.storage = storage
        self.session_repository = session_repository

    async def cleanup_abandoned_sessions(self) -> tuple[int, int]:
        """Returns `(sessions_aborted, storage_parts_deleted)` for the caller
        (the arq cron task) to log, per FR-5's "Logs cleanup metrics" AC.
        """
        expired_sessions = await self.session_repository.find_expired_unfinalized(datetime.now(UTC))

        storage_parts_deleted = 0
        for session in expired_sessions:
            parts = await self.storage.list_parts(session.storage_key, session.storage_upload_id)
            storage_parts_deleted += len(parts)
            await self.storage.abort_multipart_upload(
                session.storage_key, session.storage_upload_id
            )
            await self.session_repository.delete(session)

        logger.info(
            "multipart_cleanup",
            sessions_aborted=len(expired_sessions),
            storage_parts_deleted=storage_parts_deleted,
        )
        return len(expired_sessions), storage_parts_deleted
