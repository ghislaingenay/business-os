"""Persistence access for the `files`, `upload_sessions`, and
`multipart_sessions` tables (TD-002 §4, TD-005 §3).
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from upload.models import File, MultipartSession, UploadSession


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
        """Mark the session finalized in-memory — deliberately does NOT commit.

        `UploadService.finalize_large_upload` calls this immediately before
        `FileRepository.save()`, relying on that call's single `commit()` to
        flush both this mutation and the new `File` row together. Both
        repositories share one `AsyncSession` per request (FastAPI's
        dependency caching), but sharing a session alone doesn't make two
        separate `commit()` calls atomic — each `commit()` ends its own
        transaction. Committing here too would let a crash between the two
        commits leave `finalized=False` with the `File` row already persisted,
        so a client retry could create a duplicate `File` for the same upload.
        """
        upload_session.finalized = True


class MultipartSessionRepository:
    """`MultipartSessionRepository` (see `upload.multipart_service`) backed by
    SQLAlchemy's async session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, multipart_session: MultipartSession) -> MultipartSession:
        self.session.add(multipart_session)
        await self.session.commit()
        await self.session.refresh(multipart_session)
        return multipart_session

    async def find_active_by_id(self, upload_id: uuid.UUID) -> MultipartSession | None:
        """Look up a session by id, excluding already-finalized ones — mirrors
        `UploadSessionRepository.find_active_by_id`'s rationale.
        """
        result = await self.session.execute(
            select(MultipartSession).where(
                MultipartSession.upload_id == upload_id,
                MultipartSession.finalized.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def mark_finalized(self, multipart_session: MultipartSession) -> None:
        """Mark the session finalized in-memory — deliberately does NOT commit,
        matching `UploadSessionRepository.mark_finalized`'s same-transaction
        rationale with the `File` row it's persisted alongside.
        """
        multipart_session.finalized = True

    async def find_expired_unfinalized(self, now: datetime) -> list[MultipartSession]:
        """Sessions past their TTL that were never finalized (FR-5 cleanup job)."""
        result = await self.session.execute(
            select(MultipartSession).where(
                MultipartSession.expires_at < now,
                MultipartSession.finalized.is_(False),
            )
        )
        return list(result.scalars().all())

    async def delete(self, multipart_session: MultipartSession) -> None:
        await self.session.delete(multipart_session)
        await self.session.commit()
