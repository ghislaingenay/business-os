"""arq-backed Redis job queue client (TD-004 §3, §8).

No `StorageProvider`/`CacheProvider`-style ABC here: unlike storage or cache,
this project only ever targets one queue backend (arq on Redis, per FR-3's
"Redis-backed arq queue"), so an abstraction layer would have no second
implementation to decouple from.
"""

from arq.connections import ArqRedis
from redis import asyncio as redis_asyncio


def create_job_queue(redis_url: str) -> ArqRedis:
    """Build an `ArqRedis` client without connecting eagerly.

    Mirrors `RedisCacheProvider`'s lazy `from_url()` pattern (see
    `shared/cache/redis_provider.py`) rather than arq's own `create_pool()`,
    which pings Redis immediately and would make this a blocking call —
    `container.py`'s `providers.Singleton` factories are expected to be sync
    and cheap.
    """
    pool = redis_asyncio.from_url(redis_url)
    return ArqRedis(connection_pool=pool.connection_pool)
