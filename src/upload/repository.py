"""Persistence access for the `files` table (TD-002 §4)."""

from sqlalchemy.ext.asyncio import AsyncSession

from upload.models import File


class FileRepository:
    """`FileRepository` (see `upload.service`) backed by SQLAlchemy's async session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, file: File) -> File:
        self.session.add(file)
        await self.session.commit()
        await self.session.refresh(file)
        return file
