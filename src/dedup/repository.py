"""Persistence access for hash→storage_key lookups (FR-3)."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dedup.exceptions import DedupDatabaseUnavailableError
from upload.models import File


class DedupRepository:
    """Queries the `files` table for existing content by SHA-256 hash."""

    def __init__(self, session: AsyncSession, query_timeout_seconds: float) -> None:
        self.session = session
        self.query_timeout_seconds = query_timeout_seconds

    async def find_storage_key_by_hash(self, sha256_hash: str) -> str | None:
        """`SELECT storage_key FROM files WHERE sha256_hash = $1 LIMIT 1` (FR-3),
        bounded by `query_timeout_seconds` so a stalled database fails fast.
        """
        from sqlalchemy.exc import SQLAlchemyError

        try:
            result = await asyncio.wait_for(
                self.session.execute(
                    select(File.storage_key).where(File.sha256_hash == sha256_hash).limit(1)
                ),
                timeout=self.query_timeout_seconds,
            )
        except TimeoutError as exc:
            raise DedupDatabaseUnavailableError(
                f"Hash lookup timed out after {self.query_timeout_seconds}s"
            ) from exc
        except SQLAlchemyError as exc:
            raise DedupDatabaseUnavailableError(f"Hash lookup failed: {exc}") from exc
        return result.scalar_one_or_none()
                timeout=self.query_timeout_seconds,
            )
        except TimeoutError as exc:
            raise DedupDatabaseUnavailableError(
                f"Hash lookup timed out after {self.query_timeout_seconds}s"
            ) from exc
        return result.scalar_one_or_none()
