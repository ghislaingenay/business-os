"""Abstract interface all storage backends implement."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class StorageObjectMetadata:
    """Metadata returned by `head`, without downloading the object body."""

    size: int
    etag: str
    last_modified: str
    content_type: str | None = None


class StorageProvider(ABC):
    """Common operations every storage backend (S3, GCS, R2, MinIO) must support.

    Implementations must raise only the exceptions defined in
    `src/shared/storage/exceptions.py` — never leak provider-specific SDK
    exceptions across this boundary.
    """

    @abstractmethod
    async def upload(
        self,
        key: str,
        stream: AsyncIterator[bytes] | bytes,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Upload an object and return its storage key."""

    @abstractmethod
    def download(self, key: str) -> AsyncIterator[bytes]:
        """Download an object as a stream of bytes chunks.

        Implementations are async generators — call without `await`, consume
        with `async for chunk in provider.download(key)`.
        """

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete an object. Must not raise if the object does not exist."""

    @abstractmethod
    async def head(self, key: str) -> StorageObjectMetadata:
        """Get object metadata without downloading its body."""

    @abstractmethod
    async def generate_presigned_url(
        self, key: str, method: Literal["GET", "PUT"], ttl: int
    ) -> str:
        """Generate a time-limited presigned URL for direct client access."""
