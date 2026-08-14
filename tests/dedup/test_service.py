"""Unit tests for `DedupService` against fake `CacheProvider`/`DedupRepository`
doubles — no real Redis or Postgres needed, mirroring this project's
mocked-infrastructure convention (see tests/upload/test_repository.py).
"""

import asyncio

import pytest

from dedup.config import DedupSettings
from dedup.exceptions import DedupDatabaseUnavailableError
from dedup.service import DedupCheckResult, DedupService
from shared.cache.exceptions import CacheUnavailableError
from shared.cache.provider import CacheProvider

_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_STORAGE_KEY = "originals/2026/08/14/abc.jpg"
_NEW_STORAGE_KEY = "originals/2026/08/14/def.jpg"


class FakeCacheProvider(CacheProvider):
    """In-memory `CacheProvider` double. `unavailable=True` makes every
    method raise `CacheUnavailableError`, simulating Redis being down.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.unavailable = False

    async def get(self, key: str) -> str | None:
        if self.unavailable:
            raise CacheUnavailableError("simulated Redis outage")
        return self.store.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        if self.unavailable:
            raise CacheUnavailableError("simulated Redis outage")
        self.store[key] = value
        self.ttls[key] = ttl_seconds

    async def set_if_not_exists(self, key: str, value: str, ttl_seconds: int) -> bool:
        if self.unavailable:
            raise CacheUnavailableError("simulated Redis outage")
        if key in self.store:
            return False
        self.store[key] = value
        self.ttls[key] = ttl_seconds
        return True

    async def expire(self, key: str, ttl_seconds: int) -> None:
        if self.unavailable:
            raise CacheUnavailableError("simulated Redis outage")
        self.ttls[key] = ttl_seconds

    async def delete_if_matches(self, key: str, expected_value: str) -> bool:
        if self.unavailable:
            raise CacheUnavailableError("simulated Redis outage")
        if self.store.get(key) == expected_value:
            del self.store[key]
            return True
        return False


class FakeDedupRepository:
    """In-memory `DedupRepository` double. `raise_unavailable=True` simulates
    a database outage/timeout.
    """

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.raise_unavailable = False

    async def find_storage_key_by_hash(self, sha256_hash: str) -> str | None:
        if self.raise_unavailable:
            raise DedupDatabaseUnavailableError("simulated database outage")
        return self.data.get(sha256_hash)


@pytest.fixture()
def cache() -> FakeCacheProvider:
    return FakeCacheProvider()


@pytest.fixture()
def repository() -> FakeDedupRepository:
    return FakeDedupRepository()


@pytest.fixture()
def settings() -> DedupSettings:
    return DedupSettings(
        enabled=True,
        cache_ttl_seconds=86400,
        lock_ttl_seconds=10,
        lock_retry_max=2,
        lock_retry_delay_ms=1,
        db_query_timeout_seconds=5,
    )


@pytest.fixture()
def service(
    cache: FakeCacheProvider, repository: FakeDedupRepository, settings: DedupSettings
) -> DedupService:
    return DedupService(cache=cache, repository=repository, settings=settings)


async def test_check_returns_none_when_disabled(
    cache: FakeCacheProvider, repository: FakeDedupRepository
) -> None:
    disabled_settings = DedupSettings(enabled=False)
    service = DedupService(cache=cache, repository=repository, settings=disabled_settings)

    result = await service.check(_HASH)

    assert result == DedupCheckResult(existing_storage_key=None, lock_token=None)
    assert cache.store == {}


async def test_finish_is_a_noop_when_disabled(
    cache: FakeCacheProvider, repository: FakeDedupRepository
) -> None:
    disabled_settings = DedupSettings(enabled=False)
    service = DedupService(cache=cache, repository=repository, settings=disabled_settings)
    result = DedupCheckResult(existing_storage_key=None, lock_token=None)

    await service.finish(_HASH, _NEW_STORAGE_KEY, result)

    assert cache.store == {}


async def test_check_returns_none_on_full_miss(service: DedupService) -> None:
    result = await service.check(_HASH)

    assert result.existing_storage_key is None


async def test_check_returns_cache_hit_and_renews_ttl(
    service: DedupService, cache: FakeCacheProvider
) -> None:
    cache.store[f"dedup:hash:{_HASH}"] = _STORAGE_KEY
    cache.ttls[f"dedup:hash:{_HASH}"] = 1  # about to expire

    result = await service.check(_HASH)

    assert result.existing_storage_key == _STORAGE_KEY
    assert cache.ttls[f"dedup:hash:{_HASH}"] == 86400  # renewed (FR-2)


async def test_check_returns_db_hit_and_populates_cache(
    service: DedupService, cache: FakeCacheProvider, repository: FakeDedupRepository
) -> None:
    repository.data[_HASH] = _STORAGE_KEY

    result = await service.check(_HASH)

    assert result.existing_storage_key == _STORAGE_KEY
    assert cache.store[f"dedup:hash:{_HASH}"] == _STORAGE_KEY  # FR-3: cache populated on DB hit


async def test_check_propagates_database_unavailable_error(
    service: DedupService, repository: FakeDedupRepository
) -> None:
    repository.raise_unavailable = True

    with pytest.raises(DedupDatabaseUnavailableError):
        await service.check(_HASH)


async def test_check_falls_back_to_db_when_cache_unavailable(
    service: DedupService, cache: FakeCacheProvider, repository: FakeDedupRepository
) -> None:
    repository.data[_HASH] = _STORAGE_KEY
    cache.unavailable = True

    result = await service.check(_HASH)

    # Cache writes fail silently too (graceful degradation), but the lookup
    # itself still succeeds via the database.
    assert result.existing_storage_key == _STORAGE_KEY
    assert result.lock_token is None  # fail-open: couldn't acquire a lock either


async def test_check_acquires_lock_on_first_try(
    service: DedupService, cache: FakeCacheProvider
) -> None:
    result = await service.check(_HASH)

    assert result.lock_token is not None
    assert cache.store[f"lock:hash:{_HASH}"] == result.lock_token


async def test_check_fails_open_when_lock_already_held(
    service: DedupService, cache: FakeCacheProvider
) -> None:
    cache.store[f"lock:hash:{_HASH}"] = "someone-elses-token"

    result = await service.check(_HASH)

    # FR-4: fails open after exhausting retries rather than blocking forever.
    assert result.lock_token is None


async def test_finish_populates_cache_and_releases_lock(
    service: DedupService, cache: FakeCacheProvider
) -> None:
    result = await service.check(_HASH)

    await service.finish(_HASH, _NEW_STORAGE_KEY, result)

    assert cache.store[f"dedup:hash:{_HASH}"] == _NEW_STORAGE_KEY
    assert f"lock:hash:{_HASH}" not in cache.store  # lock released


async def test_finish_does_not_release_lock_when_none_was_acquired(
    service: DedupService, cache: FakeCacheProvider
) -> None:
    result = DedupCheckResult(existing_storage_key=None, lock_token=None)

    await service.finish(_HASH, _NEW_STORAGE_KEY, result)

    assert cache.store[f"dedup:hash:{_HASH}"] == _NEW_STORAGE_KEY


async def test_abort_releases_lock_without_populating_cache(
    service: DedupService, cache: FakeCacheProvider
) -> None:
    """FR-4: lock released on failure too — `abort()` is what the caller uses
    when its own upload work failed before producing a storage_key worth
    caching (see upload/service.py's use of it on a storage.upload failure).
    """
    result = await service.check(_HASH)

    await service.abort(_HASH, result)

    assert f"lock:hash:{_HASH}" not in cache.store  # lock released
    assert f"dedup:hash:{_HASH}" not in cache.store  # cache NOT populated


async def test_abort_does_nothing_when_no_lock_was_acquired(
    service: DedupService, cache: FakeCacheProvider
) -> None:
    result = DedupCheckResult(existing_storage_key=None, lock_token=None)

    await service.abort(_HASH, result)  # must not raise

    assert cache.store == {}


async def test_abort_is_a_noop_when_disabled(
    cache: FakeCacheProvider, repository: FakeDedupRepository
) -> None:
    disabled_settings = DedupSettings(enabled=False)
    service = DedupService(cache=cache, repository=repository, settings=disabled_settings)
    result = DedupCheckResult(existing_storage_key=None, lock_token="some-token")

    await service.abort(_HASH, result)  # must not raise or touch the cache

    assert cache.store == {}


async def test_finish_handles_cache_unavailable_without_raising(
    service: DedupService, cache: FakeCacheProvider
) -> None:
    result = await service.check(_HASH)
    cache.unavailable = True

    await service.finish(_HASH, _NEW_STORAGE_KEY, result)  # must not raise


async def test_concurrent_checks_for_same_hash_only_one_acquires_lock(
    cache: FakeCacheProvider, repository: FakeDedupRepository
) -> None:
    """Simulates TD-003's "Concurrent Upload of Same File" story: two
    concurrent `check()` calls for identical content must not both acquire
    the lock, even with retries disabled so the race is deterministic.
    """
    no_retry_settings = DedupSettings(lock_retry_max=0, lock_retry_delay_ms=1)
    service = DedupService(cache=cache, repository=repository, settings=no_retry_settings)

    result_a, result_b = await asyncio.gather(service.check(_HASH), service.check(_HASH))

    tokens = {result_a.lock_token, result_b.lock_token}
    assert None in tokens  # exactly one of the two failed to acquire
    assert len(tokens) == 2  # the other one did acquire a real token
