"""Business logic for async variant generation (TD-004 §2, §6).

Orchestrates the download → generate → upload → persist sequence; owns no
HTTP or arq concerns (`worker.tasks` is the arq boundary that calls into
this).
"""

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Protocol

from shared.image.exceptions import ImageDecodeError
from shared.image.processor import to_thumbnail, to_webp
from shared.storage.exceptions import StorageError
from shared.storage.provider import StorageProvider
from variants.config import VariantSettings
from variants.exceptions import VariantGenerationError

logger = logging.getLogger(__name__)


class VariantRepositoryProtocol(Protocol):
    """Persistence operations `VariantService` needs (see `variants.repository`)."""

    async def update_variants(
        self, file_id: uuid.UUID, web_optimized_url: str, thumbnail_url: str
    ) -> None:
        ...


class VariantService:
    """Generates and persists the web-optimized and thumbnail variants of an upload."""

    def __init__(
        self,
        *,
        storage: StorageProvider,
        repository: VariantRepositoryProtocol,
        settings: VariantSettings,
    ) -> None:
        self.storage = storage
        self.repository = repository
        self.settings = settings

    async def generate(self, file_id: uuid.UUID, storage_key: str, mime_type: str) -> None:
        """Generate both variants for `storage_key` and persist their URLs.

        No-ops for mime types outside FR-1's scope (JPEG/PNG/GIF) — e.g.
        `video/mp4` — since video thumbnail extraction and transcoding are
        explicit Non-Goals (FEAT-004 §"Non-Goals"; also resolves the FEAT's
        "Do we generate variants for uploaded videos" open question).
        """
        if mime_type not in self.settings.generated_mime_types:
            return

        try:
            original = await self._download(storage_key)
            # Pillow's encode/decode work is CPU-bound and synchronous; run it
            # in a thread so it doesn't block this worker's event loop (and
            # thus every other job it's concurrently running — `max_jobs=10`
            # in `worker.WorkerSettings`) for the duration of the conversion
            # (coding-standards.md §9: "run it in a threadpool rather than
            # blocking the event loop").
            web_optimized_bytes = await asyncio.to_thread(
                to_webp, original, quality=self.settings.web_optimized_quality
            )
            thumbnail_bytes = await asyncio.to_thread(
                to_thumbnail,
                original,
                size=(self.settings.thumbnail_size, self.settings.thumbnail_size),
                quality=self.settings.thumbnail_quality,
            )

            web_optimized_key = self._variant_key(storage_key, prefix="webp", suffix="", ext="webp")
            thumbnail_key = self._variant_key(
                storage_key, prefix="thumbnails", suffix="_thumb", ext="jpg"
            )

            await self.storage.upload(
                web_optimized_key, web_optimized_bytes, metadata={"mime_type": "image/webp"}
            )
            await self.storage.upload(
                thumbnail_key, thumbnail_bytes, metadata={"mime_type": "image/jpeg"}
            )

            await self.repository.update_variants(file_id, web_optimized_key, thumbnail_key)
        except (StorageError, ImageDecodeError) as exc:
            logger.warning(
                "variant_generation_failed",
                extra={"file_id": str(file_id), "storage_key": storage_key},
            )
            raise VariantGenerationError(
                f"Failed to generate variants for file {file_id}: {exc}"
            ) from exc

    async def _download(self, storage_key: str) -> bytes:
        chunks = [chunk async for chunk in self.storage.download(storage_key)]
        return b"".join(chunks)

    @staticmethod
    def _variant_key(storage_key: str, *, prefix: str, suffix: str, ext: str) -> str:
        """Build `{prefix}/{YYYY}/{MM}/{DD}/{UUID}{suffix}.{ext}` from an
        `originals/{YYYY}/{MM}/{DD}/{UUID}{orig_ext}` storage key (FR-1, FR-2),
        preserving the original's date/UUID path segment.
        """
        relative = Path(storage_key.removeprefix("originals/"))
        return f"{prefix}/{relative.parent}/{relative.stem}{suffix}.{ext}"
