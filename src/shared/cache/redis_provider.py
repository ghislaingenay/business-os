"""Redis-backed cache provider."""

from typing import cast

from redis import asyncio as redis_asyncio
from redis.exceptions import RedisError

from shared.cache.exceptions import CacheUnavailableError
from shared.cache.provider import CacheProvider

# KEYS[1] = lock/value key, ARGV[1] = expected current value. Atomic
# read-compare-delete via Lua so a lock's TTL expiring mid-release can never
# make this delete a different holder's lock (TD-003 §10).
_DELETE_IF_MATCHES_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class RedisCacheProvider(CacheProvider):
    """`CacheProvider` backed by `redis.asyncio.Redis`."""

    def __init__(self, redis_url: str) -> None:
        self._client = redis_asyncio.from_url(redis_url, decode_responses=True)  # type: ignore

    async def get(self, key: str) -> str | None:
        try:
            return cast(str | None, await self._client.get(key))
        except RedisError as exc:
            raise CacheUnavailableError(f"Redis GET failed for key {key!r}: {exc}") from exc

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        try:
            await self._client.set(key, value, ex=ttl_seconds)
        except RedisError as exc:
            raise CacheUnavailableError(f"Redis SET failed for key {key!r}: {exc}") from exc

    async def set_if_not_exists(self, key: str, value: str, ttl_seconds: int) -> bool:
        try:
            result = await self._client.set(key, value, nx=True, ex=ttl_seconds)
        except RedisError as exc:
            raise CacheUnavailableError(f"Redis SET NX failed for key {key!r}: {exc}") from exc
        return bool(result)

    async def expire(self, key: str, ttl_seconds: int) -> None:
        try:
            await self._client.expire(key, ttl_seconds)
        except RedisError as exc:
            raise CacheUnavailableError(f"Redis EXPIRE failed for key {key!r}: {exc}") from exc

    async def delete_if_matches(self, key: str, expected_value: str) -> bool:
        try:
            # `eval` lacks type stub coverage in redis-py itself (unlike most
            # of its client, which is fully typed) — narrower than the
            # `ignore_missing_imports` override above, which only covers the
            # whole-module-not-found case, not this per-method gap.
            result = cast(
                int, await self._client.eval(_DELETE_IF_MATCHES_SCRIPT, 1, key, expected_value)
            )
        except RedisError as exc:
            raise CacheUnavailableError(f"Redis DEL failed for key {key!r}: {exc}") from exc
        return bool(result)
