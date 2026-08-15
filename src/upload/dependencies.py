"""FastAPI dependency wiring for the upload domain, composed from `container.container`."""

from collections.abc import AsyncIterator

from arq.connections import ArqRedis
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from container import container
from database import get_session
from dedup.config import DedupSettings
from dedup.repository import DedupRepository
from dedup.service import DedupService
from shared.cache.provider import CacheProvider
from shared.storage.provider import StorageProvider
from upload.config import UploadSettings
from upload.repository import FileRepository, UploadSessionRepository
from upload.service import UploadService
from upload.validator import UploadValidator


def get_upload_settings() -> UploadSettings:
    return container.upload_settings()


def get_dedup_settings() -> DedupSettings:
    return container.dedup_settings()


def get_storage_provider() -> StorageProvider:
    return container.storage_provider()


def get_cache_provider() -> CacheProvider:
    return container.cache_provider()


def get_job_queue() -> ArqRedis:
    return container.job_queue()


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session(container.db_session_factory()):
        yield session


def get_upload_validator(
    settings: UploadSettings = Depends(get_upload_settings),
) -> UploadValidator:
    return UploadValidator(settings)


def get_file_repository(
    session: AsyncSession = Depends(get_db_session),
) -> FileRepository:
    return FileRepository(session)


def get_upload_session_repository(
    session: AsyncSession = Depends(get_db_session),
) -> UploadSessionRepository:
    return UploadSessionRepository(session)


def get_dedup_repository(
    session: AsyncSession = Depends(get_db_session),
    settings: DedupSettings = Depends(get_dedup_settings),
) -> DedupRepository:
    return DedupRepository(session, query_timeout_seconds=settings.db_query_timeout_seconds)


def get_dedup_service(
    cache: CacheProvider = Depends(get_cache_provider),
    repository: DedupRepository = Depends(get_dedup_repository),
    settings: DedupSettings = Depends(get_dedup_settings),
) -> DedupService:
    return DedupService(cache=cache, repository=repository, settings=settings)


def get_upload_service(
    *,
    validator: UploadValidator = Depends(get_upload_validator),
    storage: StorageProvider = Depends(get_storage_provider),
    repository: FileRepository = Depends(get_file_repository),
    session_repository: UploadSessionRepository = Depends(get_upload_session_repository),
    dedup_service: DedupService = Depends(get_dedup_service),
    job_queue: ArqRedis = Depends(get_job_queue),
    settings: UploadSettings = Depends(get_upload_settings),
) -> UploadService:
    return UploadService(
        validator=validator,
        storage=storage,
        repository=repository,
        session_repository=session_repository,
        dedup_service=dedup_service,
        job_queue=job_queue,
        presigned_url_ttl=settings.presigned_url_ttl,
    )
