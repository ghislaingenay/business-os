"""FastAPI dependency wiring for the upload domain, composed from `container.container`."""

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from container import container
from database import get_session
from shared.storage.provider import StorageProvider
from upload.config import UploadSettings
from upload.repository import SqlFileRepository
from upload.service import FileRepository, UploadService
from upload.validator import UploadValidator


def get_upload_settings() -> UploadSettings:
    return container.upload_settings()


def get_storage_provider() -> StorageProvider:
    return container.storage_provider()


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
    return SqlFileRepository(session)


def get_upload_service(
    validator: UploadValidator = Depends(get_upload_validator),
    storage: StorageProvider = Depends(get_storage_provider),
    repository: FileRepository = Depends(get_file_repository),
    settings: UploadSettings = Depends(get_upload_settings),
) -> UploadService:
    return UploadService(
        validator=validator,
        storage=storage,
        repository=repository,
        download_url_ttl=settings.presigned_url_ttl,
    )
