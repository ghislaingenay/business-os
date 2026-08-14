"""SHA-256 hash calculation for upload content (TD-003 §3, FR-1).

Two entry points because the two upload paths hold content differently: the
mediated path already has the full body in memory (`hash_bytes`), while the
presigned path never sees the bytes server-side and must stream them back
from storage on finalize (`hash_stream`) rather than buffering the whole
object in memory.
"""

import hashlib
from collections.abc import AsyncIterator


def hash_bytes(content: bytes) -> str:
    """Hex-encoded SHA-256 hash of in-memory `content`."""
    return hashlib.sha256(content).hexdigest()


async def hash_stream(stream: AsyncIterator[bytes]) -> str:
    """Hex-encoded SHA-256 hash of an async byte stream, without buffering
    the whole payload in memory.

    `digest.update()` is synchronous C code, so each call briefly blocks the
    event loop rather than yielding to it. Not wrapped in `asyncio.to_thread`:
    SHA-256 runs at roughly 500MB/s-1GB/s, and `StorageProvider.download()`
    yields 8MB chunks, so each `update()` costs only ~10ms — small next to the
    `await` on each chunk's network I/O, which is what actually dominates a
    hash's wall-clock time (TD-003 §11: "~200ms for 100MB, SSD I/O bound, not
    CPU"). A thread-hop per chunk would cost more than it saves at this size.
    """
    digest = hashlib.sha256()
    async for chunk in stream:
        digest.update(chunk)
    return digest.hexdigest()
