"""arq task definitions (TD-004 §3, §6; TD-005 §7).

Kept thin like `upload.router` — parses job args, builds per-job
dependencies from `ctx`, and delegates to `variants.service.VariantService`
or `upload.multipart_service.MultipartCleanupService`. No business logic
lives here.
"""

import uuid
from typing import Any

from arq import Retry
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.logging.middleware import bind_request_id
from shared.storage.provider import StorageProvider
from upload.multipart_service import MultipartCleanupService
from upload.repository import MultipartSessionRepository
from variants.config import VariantSettings
from variants.exceptions import VariantGenerationError
from variants.repository import VariantRepository
from variants.service import VariantService


async def generate_variants(
    ctx: dict[str, Any],
    file_id: str,
    storage_key: str,
    mime_type: str,
    request_id: str | None = None,
) -> None:
    """Generate WebP + thumbnail variants for a newly uploaded file (FR-1 through FR-4).

    Retries with the exponential backoff configured in `VariantSettings`
    (FR-3: "3 attempts with exponential backoff (1s, 5s, 25s)") by raising
    arq's `Retry` with an explicit `defer` — arq's own `max_tries` re-enqueues
    immediately otherwise, which wouldn't honor the FR's backoff schedule.
    Once the configured retries are exhausted, the exception propagates and
    arq marks the job failed, satisfying the success metric's "failed jobs
    logged for manual inspection" rather than retrying forever.

    `request_id` is the originating upload request's id (FEAT-007 FR-2's
    worker-job propagation AC), re-bound here so this job's logs correlate
    back to that request.
    """
    bind_request_id(request_id)

    settings: VariantSettings = ctx["variant_settings"]
    storage: StorageProvider = ctx["storage_provider"]
    session_factory: async_sessionmaker[AsyncSession] = ctx["db_session_factory"]

    async with session_factory() as session:
        service = VariantService(
            storage=storage,
            repository=VariantRepository(session),
            settings=settings,
        )
        try:
            await service.generate(uuid.UUID(file_id), storage_key, mime_type)
        except VariantGenerationError:
            job_try: int = ctx["job_try"]
            delays = settings.retry_delays_seconds
            if job_try > len(delays):
                raise
            raise Retry(defer=delays[job_try - 1]) from None


async def cleanup_abandoned_multipart_sessions(ctx: dict[str, Any]) -> None:
    """Daily cron job: abort and delete multipart sessions past their 24h TTL
    (FR-5, TD-005 §7 — scheduled at 2 AM via `worker.WorkerSettings.cron_jobs`).
    """
    storage: StorageProvider = ctx["storage_provider"]
    session_factory: async_sessionmaker[AsyncSession] = ctx["db_session_factory"]

    async with session_factory() as session:
        service = MultipartCleanupService(
            storage=storage,
            session_repository=MultipartSessionRepository(session),
        )
        await service.cleanup_abandoned_sessions()
