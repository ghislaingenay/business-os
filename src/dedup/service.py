"""Business logic for content-based deduplication (TD-003 §2, §6).

`DedupService.check()` and `.finish()` bracket the caller's own upload work
rather than performing the upload itself, so `dedup` stays independent of
`upload`'s storage/persistence concerns (upload owns the `File` row and the
storage write; `dedup` only decides whether that write is necessary and
records the outcome).
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass

from dedup.config import DedupSettings
from dedup.exceptions import DedupDatabaseUnavailableError
from dedup.repository import DedupRepository
from shared.cache.exceptions import CacheUnavailableError
from shared.cache.provider import CacheProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DedupCheckResult:
    """Result of `DedupService.check()`.

    `lock_token` is `None` when dedup is disabled or the lock couldn't be
    acquired (fail-open per FR-4) — `finish()` uses its presence to decide
    whether there's a lock to release.
    """

    existing_storage_key: str | None
    lock_token: str | None


class DedupService:
    """Orchestrates hash-based dedup lookups, distributed locking, and cache
    population (FR-2 through FR-5).
    """

    def __init__(
        self,
        cache: CacheProvider,
        repository: DedupRepository,
        settings: DedupSettings,
    ) -> None:
        self.cache = cache
        self.repository = repository
        self.settings = settings

    async def check(self, sha256_hash: str) -> DedupCheckResult:
        """Look up existing content for `sha256_hash` (FR-2, FR-3, FR-4).

        Caller must call `finish()` afterwards — on both a hit and a miss —
        passing whichever `storage_key` ends up being used, so the cache gets
        populated/renewed and the lock gets released.
        """
        if not self.settings.enabled:
            return DedupCheckResult(existing_storage_key=None, lock_token=None)

        lock_token = await self._acquire_lock(sha256_hash)
        existing_storage_key = await self._find_existing(sha256_hash)
        return DedupCheckResult(existing_storage_key=existing_storage_key, lock_token=lock_token)

    async def finish(self, sha256_hash: str, storage_key: str, result: DedupCheckResult) -> None:
        """Populate/renew the cache with `storage_key` and release the lock
        acquired by `check()` (FR-5).
        """
        if not self.settings.enabled:
            return

        await self._populate_cache(sha256_hash, storage_key)
        if result.lock_token is not None:
            await self._release_lock(sha256_hash, result.lock_token)

    async def abort(self, sha256_hash: str, result: DedupCheckResult) -> None:
        """Release the lock acquired by `check()` without populating the cache
        (FR-4: "released after upload completes, or on failure"). Use this
        instead of `finish()` when the caller's own upload work failed before
        producing a `storage_key` worth caching.
        """
        if not self.settings.enabled:
            return

        if result.lock_token is not None:
            await self._release_lock(sha256_hash, result.lock_token)

    async def _find_existing(self, sha256_hash: str) -> str | None:
        cache_key = self._cache_key(sha256_hash)

        try:
            cached_storage_key = await self.cache.get(cache_key)
        except CacheUnavailableError:
            logger.warning("dedup_cache_unavailable", extra={"hash": sha256_hash})
            cached_storage_key = None

        if cached_storage_key is not None:
            try:
                await self.cache.expire(cache_key, self.settings.cache_ttl_seconds)
            except CacheUnavailableError:
                logger.warning("dedup_cache_unavailable", extra={"hash": sha256_hash})
            logger.info(
                "dedup_check", extra={"result": "hit", "hash": sha256_hash, "source": "cache"}
            )
            return cached_storage_key

        # Cache miss (or Redis unavailable) — fall back to the database
        # (FR-3). `DedupDatabaseUnavailableError` propagates uncaught: per
        # TD-003 §7 there's no further fallback tier below the database, so
        # the upload request fails (503) rather than silently skipping dedup.
        try:
            storage_key = await self.repository.find_storage_key_by_hash(sha256_hash)
        except DedupDatabaseUnavailableError:
            logger.error("database_unavailable", extra={"hash": sha256_hash})
            raise

        if storage_key is not None:
            await self._populate_cache(sha256_hash, storage_key)
            logger.info(
                "dedup_check", extra={"result": "hit", "hash": sha256_hash, "source": "database"}
            )
            return storage_key

        logger.info("dedup_check", extra={"result": "miss", "hash": sha256_hash})
        return None

    async def _populate_cache(self, sha256_hash: str, storage_key: str) -> None:
        try:
            await self.cache.set(
                self._cache_key(sha256_hash), storage_key, self.settings.cache_ttl_seconds
            )
        except CacheUnavailableError:
            logger.warning("cache_write_failed", extra={"hash": sha256_hash})

    async def _acquire_lock(self, sha256_hash: str) -> str | None:
        # Fixed-delay retry loop, deliberately not extracted into a generic
        # `shared/retry/` helper yet — see context/plans/shared-retry-module.md
        # for why (single caller, no backoff needed by FR-4 as written).
        lock_key = self._lock_key(sha256_hash)
        token = str(uuid.uuid4())
        started = time.monotonic()

        for attempt in range(self.settings.lock_retry_max + 1):
            try:
                acquired = await self.cache.set_if_not_exists(
                    lock_key, token, self.settings.lock_ttl_seconds
                )
            except CacheUnavailableError:
                # Redis itself is down, not just contended — no point retrying
                # a lock we can't reach. Fail-open immediately (FR-4).
                logger.warning("dedup_cache_unavailable", extra={"hash": sha256_hash})
                return None

            if acquired:
                wait_time_ms = (time.monotonic() - started) * 1000
                logger.info(
                    "dedup_lock_acquired",
                    extra={"hash": sha256_hash, "dedup_lock_wait_time_ms": wait_time_ms},
                )
                return token

            if attempt < self.settings.lock_retry_max:
                await asyncio.sleep(self.settings.lock_retry_delay_ms / 1000)

        logger.warning("dedup_lock_timeout", extra={"hash": sha256_hash})
        return None

    async def _release_lock(self, sha256_hash: str, lock_token: str) -> None:
        try:
            await self.cache.delete_if_matches(self._lock_key(sha256_hash), lock_token)
        except CacheUnavailableError:
            # Nothing to recover here — the lock's own TTL (`lock_ttl_seconds`)
            # auto-expires it, which is what makes fail-open safe.
            logger.warning("dedup_cache_unavailable", extra={"hash": sha256_hash})

    @staticmethod
    def _cache_key(sha256_hash: str) -> str:
        return f"dedup:hash:{sha256_hash}"

    @staticmethod
    def _lock_key(sha256_hash: str) -> str:
        return f"lock:hash:{sha256_hash}"
