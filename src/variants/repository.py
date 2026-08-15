"""Persistence access for updating a file's variant columns (TD-004 §4).

Follows the same cross-domain pattern as `dedup.repository.DedupRepository`:
this domain has no table of its own, so it operates directly on
`upload.models.File` rather than routing updates through `upload`'s
`FileRepository`.
"""

import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from upload.models import File


class VariantRepository:
    """Persists generated variant URLs onto a file's row."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def update_variants(
        self, file_id: uuid.UUID, web_optimized_url: str, thumbnail_url: str
    ) -> None:
        """`UPDATE files SET web_optimized_url=..., thumbnail_url=...,
        variants_processed_at=NOW() WHERE file_id=...` (FR-4).

        A single `UPDATE` statement makes the write atomic — both variant
        columns are set together or neither is, satisfying FR-4's "Atomic
        update (both variants or neither)" without needing a transaction
        spanning multiple statements.
        """
        await self.session.execute(
            update(File)
            .where(File.file_id == file_id)
            .values(
                web_optimized_url=web_optimized_url,
                thumbnail_url=thumbnail_url,
                variants_processed_at=func.now(),
            )
        )
        await self.session.commit()
