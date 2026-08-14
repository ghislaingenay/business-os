# PLAN: Graceful Shutdown for Infrastructure Clients

Status: Proposed
Created: 2026-08-14

Relates to: [FEAT-003 - Content-Based Deduplication](../features/FEAT-003-content-deduplication.md) — surfaced while wiring `cache_provider` into `src/container.py`, but predates FEAT-003.

---

## Summary

`src/main.py`'s `lifespan` only runs eager singleton init before `yield`;
nothing runs after it. None of the three infra clients wired through
`src/container.py` are closed on shutdown:

- `db_engine` (`AsyncEngine`, connection pool) — never `.dispose()`d.
- `storage_provider`'s boto3 S3 client — never closed.
- `cache_provider`'s `redis.asyncio.Redis` client (added by FEAT-003) —
  never `.aclose()`d.

## Why

This is a pre-existing gap across all three clients, not something FEAT-003
introduced — `cache_provider` just makes it a third instance of the same
missing pattern instead of two. Fixing only the new Redis client would be
inconsistent (and wouldn't actually fix the underlying gap); fixing all
three touches `database.py` and `shared/storage/` — code unrelated to
FEAT-003's scope — so it's being tracked here as a follow-up instead of
folded into that PR.

## Sketch (for future implementation, not final)

```python
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    container.storage_provider()
    container.cache_provider()
    container.db_engine()
    yield
    await container.db_engine().dispose()
    await container.cache_provider().aclose()
    # storage_provider: boto3's S3 client has no async close; call
    # `container.storage_provider()._client.close()` via asyncio.to_thread,
    # or add a `close()` method to the `StorageProvider` interface so this
    # doesn't reach into a private attribute.
```

## Open Questions

- Should `StorageProvider` gain an abstract `close()` method so `main.py`
  doesn't need provider-specific knowledge, or is reaching into
  `S3StorageProvider._client.close()` acceptable for a single call site?
- Does `CacheProvider` need the same treatment (an abstract `close()`) for
  the same reason?
