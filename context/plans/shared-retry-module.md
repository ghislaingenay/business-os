# PLAN: Extract `shared/retry/` Module

Status: Proposed
Created: 2026-08-14

Relates to: [FEAT-003 - Content-Based Deduplication](../features/FEAT-003-content-deduplication.md) — `DedupService._acquire_lock` in `src/dedup/service.py` has a bespoke retry loop that's the first concrete case matching a pattern `context/coding-standards.md` §12 already anticipates.

---

## Summary

`context/coding-standards.md` §12 lists `retry/backoff` as a canonical example
of what belongs in `src/shared/` — reusable, business-agnostic technical
capability — but no `shared/retry/` module exists yet. FEAT-003's
`DedupService._acquire_lock` implements FR-4's lock-acquisition retry
(`SET NX`, wait 50ms, retry up to `lock_retry_max` times, then fail-open)
as an inline loop with a fixed delay and no jitter/backoff, directly in the
dedup domain.

## Why not built now

- FR-4's acceptance criteria specify a fixed 50ms delay, not exponential
  backoff — a generic retry helper isn't needed to satisfy this feature's
  spec as written.
- `DedupService._acquire_lock` is currently the only caller. Extracting an
  abstraction for one caller is premature per `context/coding-standards.md`
  §17 ("avoid unnecessary abstractions") — a shared module earns its place
  once a second caller needs the same shape (e.g. FEAT-006 Rate Limiting,
  which FEAT-003 §6 already notes "uses same Redis infrastructure," may be
  that second caller).
- Not part of TD-003 §9's Single PR deliverables file list.

## Sketch (for future implementation, not final)

A `shared/retry/` module generalizing the pattern already written in
`DedupService._acquire_lock`:

```python
# shared/retry/backoff.py
async def retry_with_delay(
    operation: Callable[[], Awaitable[T | None]],
    *,
    max_attempts: int,
    delay_seconds: float,
    is_success: Callable[[T | None], bool],
) -> T | None:
    """Retry `operation` up to `max_attempts` times with a fixed delay,
    returning the last result (success or not) once attempts are exhausted —
    callers decide what "exhausted" means (fail-open vs. raise).
    """
```

`DedupService._acquire_lock` would become a thin caller passing
`self.cache.set_if_not_exists` as `operation`. Whether to support
exponential backoff/jitter from the start, or add it only once a second
caller (e.g. rate limiting) actually needs it, is an open call — YAGNI
favors starting with exactly what FR-4 needs (fixed delay) and generalizing
when a second real use case exists, not before.

## Open Questions

- Should this land as part of FEAT-006 (Rate Limiting) instead, once that
  feature's TD is written and its own retry needs are known — giving the
  abstraction two real callers to design against instead of one?
- Fixed delay only, or does the abstraction need backoff/jitter support from
  day one? No current caller needs it, but retrofitting a signature change
  later is more disruptive than including an unused parameter now.
