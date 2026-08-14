# Current Feature

FEAT-003: Content-Based Deduplication

## File

[FEAT-003 - Content-Based Deduplication](features/FEAT-003-content-deduplication.md)

## Goals

- [x] FR-1: Content Hash Calculation — SHA-256 hash computed for all uploads (mediated in-memory, presigned on finalize), stored in `files.sha256_hash`
- [x] FR-2: Deduplication Check via Redis Cache — `dedup:hash:{sha256_hash}` lookup, 24h TTL, cache hit skips storage upload
- [x] FR-3: Database Fallback for Cache Misses — query `files.sha256_hash`, repopulate cache on hit, 5s query timeout
- [x] FR-4: Distributed Lock for Race Prevention — `lock:hash:{sha256_hash}` via SET NX EX 10, retry 3x/50ms, fail-open
- [x] FR-5: Cache Population on Upload — dual-write Redis + DB after successful upload, graceful degradation on Redis failure
- [ ] FR-6: Deduplication Metrics — structured `dedup_check` log events, hit-rate calculation
      Partial: `dedup_check`/`dedup_lock_acquired` events are logged, but hit-rate
      calculation, alerting, and dashboarding are monitoring infra outside this PR
      (not in TD-003 §9's deliverables); `file_size` and JSON formatting deferred to
      FEAT-007. See TD-003 §14 and FEAT-007 §4 FR-3.

## Notes

Single-PR feature (no phase decomposition in TD-003). Depends on FEAT-001 (storage abstraction) and FEAT-002 (hybrid upload flow), both Done. Redis cache adapter goes in `src/shared/cache/` (generic, mirrors `shared/storage/`); dedup business logic (hashing, key/TTL policy, lock coordination) goes in its own `src/dedup/` domain module wired into `upload/service.py`.
