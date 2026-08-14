"""Persistence access for the `files` and `upload_sessions` tables (TD-002 §4)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from upload.models import File, UploadSession


class FileRepository:
    """`FileRepository` (see `upload.service`) backed by SQLAlchemy's async session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, file: File) -> File:
        self.session.add(file)
        await self.session.commit()
        await self.session.refresh(file)
        return file


class UploadSessionRepository:
    """`UploadSessionRepository` (see `upload.service`) backed by SQLAlchemy's async session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, upload_session: UploadSession) -> UploadSession:
        self.session.add(upload_session)
        await self.session.commit()
        await self.session.refresh(upload_session)
        return upload_session

    async def find_active_by_id(self, upload_id: uuid.UUID) -> UploadSession | None:
        """Look up a session by id, excluding already-finalized ones.

        Excluding finalized sessions here (rather than in the service layer)
        means a repeat `/upload/finalize` call for an already-completed
        upload_id naturally comes back as "not found" — no separate
        already-finalized error case needed.
        """
        result = await self.session.execute(
            select(UploadSession).where(
                UploadSession.upload_id == upload_id,
                UploadSession.finalized.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def mark_finalized(self, upload_session: UploadSession) -> None:
        upload_session.finalized = True
        await self.session.commit()
