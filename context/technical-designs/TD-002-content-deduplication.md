# TD-002: Content-Based Deduplication

Status: Not Started
Owner: TBD
Created: 2026-08-11
Last Updated: 2026-08-11

Feature Spec: [FEAT-002 - Content-Based Deduplication](../features/FEAT-002-content-deplication.md)

---

# 1. Overview

## Summary

SHA-256 content hashing with dual-tier lookup (Redis cache → PostgreSQL fallback) and distributed locking to prevent concurrent duplicate uploads. Integrates into existing upload flow with graceful degradation when Redis unavailable.

## Goals

- Sub-100ms dedup check latency (Redis cache hit)
- Zero duplicate storage writes under concurrent load
- Graceful degradation (continue uploads if Redis down)
- Observable hit rate for cost analysis

## Non-Goals

- Block-level or chunk-level deduplication (file-level only)
- Cross-bucket deduplication
- Automatic garbage collection of unused storage keys

---

# 2. Architecture

## High-Level Design

```
Upload Request
      │
      ▼
Calculate SHA-256 hash
      │
      ▼
┌─────────────────────────────────────┐
│ Acquire lock: lock:hash:{hash}      │  ← Redis SET NX EX 10
│ (prevents concurrent dedup checks)  │
└─────────────┬───────────────────────┘
              │
              ▼
Check Redis cache: dedup:hash:{hash}
      │
      ├─────► CACHE HIT ──┐
      │                   │
      └─────► CACHE MISS  │
              │           │
              ▼           │
        Query Database    │
              │           │
      ├───► FOUND ────────┤
      │                   │
      └───► NOT FOUND     │
              │           │
              ▼           │
      Upload to Storage   │
              │           │
              ▼           │
    Write hash→key to DB  │
    Write hash→key to Redis
              │           │
              └───────────┘
              │
              ▼
      Release lock
              │
              ▼
    Return storage_key
```

## Technology Choices

- **SHA-256**: Industry standard, cryptographically secure, negligible collision probability
- **Redis**: Sub-millisecond lookups, distributed lock primitive (SET NX), TTL-based expiry
- **PostgreSQL B-tree index**: Fast hash lookup (`WHERE sha256_hash = $1`), exact match queries
- **Dual-write pattern**: Write to both Redis + DB in parallel (prevents cache stampede)

---

# 3. Components

## New Components

### `src/dedup/service.py`

**Purpose**: Core deduplication logic (hash calculation, cache check, lock coordination)

### `src/dedup/cache.py`

**Purpose**: Redis cache adapter for hash→storage_key mappings

### `src/dedup/hasher.py`

**Purpose**: Streaming hash calculation (SHA-256) for files

## Modified Components

### `src/upload/service.py`

**Changes**: Integrate dedup check before storage upload (call `dedup_service.check_or_upload()`)

---

# 4. Data Model

## Schema Changes

### `files` table

```sql
ALTER TABLE files
ADD COLUMN sha256_hash CHAR(64) NULL;

CREATE INDEX idx_files_sha256_hash ON files(sha256_hash)
WHERE sha256_hash IS NOT NULL;

COMMENT ON COLUMN files.sha256_hash IS 'SHA-256 hash (hex-encoded) for content-based deduplication';
```

**Rationale**: NULL for legacy files uploaded before dedup feature, indexed for fast lookup

## Redis Keys

### `dedup:hash:{sha256_hash}`

**Type**: String
**Value**: `{storage_key}`
**TTL**: 24 hours (86400 seconds)
**Example**: `dedup:hash:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` → `originals/2026/08/11/550e8400.jpg`

### `lock:hash:{sha256_hash}`

**Type**: String
**Value**: `{request_id}` (UUID for identifying lock holder)
**TTL**: 10 seconds (auto-release on timeout)
**Example**: `lock:hash:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` → `req-123e4567-e89b-12d3`

---

# 5. API Design

## Modified Endpoints

No API changes — deduplication transparent to clients. Responses remain identical:

```json
{
  "file_id": "...",
  "storage_key": "originals/2026/08/11/...",
  "filename": "...",
  "size": 12345,
  "mime_type": "image/jpeg",
  "sha256_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "upload_url": "https://...",
  "created_at": "2026-08-11T10:30:00Z"
}
```

**New field**: `sha256_hash` (optional, for client-side verification)

---

# 6. Sequence Flow

## Deduplication Flow with Cache Hit

```
Upload Service    Dedup Service      Redis Cache       Database
      │                 │                 │                │
      │ check_or_upload │                 │                │
      ├────────────────►│                 │                │
      │                 │                 │                │
      │                 │ 1. Calculate SHA-256 hash       │
      │                 │                 │                │
      │                 │ 2. SET NX lock:hash:{hash} (10s)│
      │                 ├────────────────►│                │
      │                 │ ◄───────────────┤                │
      │                 │   OK (acquired) │                │
      │                 │                 │                │
      │                 │ 3. GET dedup:hash:{hash}        │
      │                 ├────────────────►│                │
      │                 │ ◄───────────────┤                │
      │                 │   storage_key   │                │
      │                 │                 │                │
      │                 │ 4. EXPIRE dedup:hash:{hash} 86400
      │                 ├────────────────►│  (renew TTL)  │
      │                 │                 │                │
      │                 │ 5. DEL lock:hash:{hash}         │
      │                 ├────────────────►│                │
      │                 │                 │                │
      │ ◄───────────────┤                 │                │
      │   storage_key   │                 │                │
      │ (no upload!)    │                 │                │
```

**Result**: No storage upload, instant return (~50ms)

## Deduplication Flow with Cache Miss (Database Hit)

```
Upload Service    Dedup Service      Redis Cache       Database       Storage
      │                 │                 │                │              │
      │ check_or_upload │                 │                │              │
      ├────────────────►│                 │                │              │
      │                 │                 │                │              │
      │                 │ 1. Calculate hash               │              │
      │                 │                 │                │              │
      │                 │ 2. Acquire lock │                │              │
      │                 ├────────────────►│                │              │
      │                 │                 │                │              │
      │                 │ 3. GET dedup:hash:{hash}        │              │
      │                 ├────────────────►│                │              │
      │                 │ ◄───────────────┤                │              │
      │                 │   NIL (miss)    │                │              │
      │                 │                 │                │              │
      │                 │ 4. SELECT storage_key           │              │
      │                 ├─────────────────────────────────►│              │
      │                 │ ◄──────────────────────────────┤              │
      │                 │   storage_key   │                │              │
      │                 │                 │                │              │
      │                 │ 5. SET dedup:hash:{hash} storage_key (24h TTL)│
      │                 ├────────────────►│                │              │
      │                 │                 │                │              │
      │                 │ 6. Release lock │                │              │
      │                 ├────────────────►│                │              │
      │                 │                 │                │              │
      │ ◄───────────────┤                 │                │              │
      │   storage_key   │                 │                │              │
      │ (no upload!)    │                 │                │              │
```

**Result**: Database query (~100-200ms), cache populated, no storage upload

## Deduplication Flow with Complete Miss (Upload Required)

```
Upload Service    Dedup Service      Redis Cache       Database       Storage
      │                 │                 │                │              │
      │ check_or_upload │                 │                │              │
      ├────────────────►│                 │                │              │
      │                 │                 │                │              │
      │                 │ 1. Calculate hash               │              │
      │                 │ 2. Acquire lock │                │              │
      │                 │ 3. Check Redis → NIL            │              │
      │                 │ 4. Check DB → NOT FOUND         │              │
      │                 │                 │                │              │
      │                 │ 5. Upload to storage            │              │
      │                 ├─────────────────────────────────────────────────►│
      │                 │ ◄───────────────────────────────────────────────┤
      │                 │   storage_key   │                │              │
      │                 │                 │                │              │
      │                 │ 6. INSERT INTO files (hash, storage_key, ...)  │
      │                 ├─────────────────────────────────►│              │
      │                 │                 │                │              │
      │                 │ 7. SET dedup:hash:{hash} storage_key (24h TTL) │
      │                 ├────────────────►│                │              │
      │                 │                 │                │              │
      │                 │ 8. Release lock │                │              │
      │                 ├────────────────►│                │              │
      │                 │                 │                │              │
      │ ◄───────────────┤                 │                │              │
      │   storage_key   │                 │                │              │
```

**Result**: Full upload flow, cache and DB populated

---

# 7. Error Handling

| Scenario                   | Behavior                         | Logging                          | Recovery                                   |
| -------------------------- | -------------------------------- | -------------------------------- | ------------------------------------------ |
| Redis down (cache check)   | Fallback to DB query immediately | WARN: `dedup_cache_unavailable`  | Continue upload with DB-only dedup         |
| Database down              | Return 503 (no degradation)      | ERROR: `database_unavailable`    | Fail request, client retries               |
| Lock acquisition timeout   | Proceed without lock (fail-open) | WARN: `dedup_lock_timeout`       | Upload may duplicate under extreme load    |
| Hash calculation error     | Return 500 (abort upload)        | ERROR: `hash_calculation_failed` | Client retries                             |
| Storage upload failure     | Return 503, no DB write          | ERROR: `storage_upload_failed`   | Transaction rollback, client retries       |
| Dual-write failure (Redis) | Continue (DB write succeeded)    | WARN: `cache_write_failed`       | Next request will repopulate cache from DB |

---

# 8. Testing Strategy

## Unit Tests

- [ ] `test_sha256_hash_calculation()` — verify hash correctness for known inputs
- [ ] `test_cache_hit_returns_storage_key()` — mock Redis GET returns key
- [ ] `test_cache_miss_falls_back_to_db()` — mock Redis NIL, DB query succeeds
- [ ] `test_lock_acquisition_retry_logic()` — simulate lock contention (3 retries)
- [ ] `test_graceful_degradation_redis_down()` — Redis raises exception, DB query proceeds
- [ ] `test_dual_write_redis_failure()` — Redis write fails, DB write succeeds, logs warning

## Integration Tests (with Redis + PostgreSQL + MinIO)

- [ ] `test_concurrent_duplicate_uploads()` — 10 concurrent uploads of same file, verify 1 storage upload
- [ ] `test_dedup_cache_hit_skips_upload()` — upload file twice, second upload has no storage API call
- [ ] `test_dedup_db_hit_populates_cache()` — clear cache, upload duplicate, verify cache populated
- [ ] `test_different_content_same_filename()` — two files "image.jpg" with different content, both stored
- [ ] `test_redis_down_graceful_degradation()` — stop Redis, upload succeeds via DB-only path
- [ ] `test_lock_expiry_auto_release()` — acquire lock, wait 11 seconds, verify lock released

## Performance Tests

- [ ] Measure cache hit latency (target: p95 <50ms)
- [ ] Measure DB fallback latency (target: p95 <200ms)
- [ ] Measure lock acquisition time under contention (target: p95 <10ms)
- [ ] Simulate high dedup rate workload (80% duplicates), verify cost savings

---

# 9. Implementation Phases (PR Mapping)

## Single PR: Complete Deduplication Implementation

**Technical Scope**:

- Files:
  - `migrations/003_add_sha256_hash_column.sql`
  - `src/dedup/__init__.py`
  - `src/dedup/service.py` (DedupService class)
  - `src/dedup/cache.py` (RedisCache adapter)
  - `src/dedup/hasher.py` (streaming SHA-256 hasher)
  - `src/upload/service.py` (modified to call dedup service)
  - `docs/redis-keys.md` (Redis key conventions)
  - `tests/unit/dedup/test_service.py`
  - `tests/unit/dedup/test_cache.py`
  - `tests/unit/dedup/test_hasher.py`
  - `tests/integration/test_deduplication.py`
- Tests: Unit tests (mocked Redis/DB), integration tests (real dependencies)
- Migration: Add `sha256_hash` column with index
- Documentation: Update OpenAPI schema with `sha256_hash` field

---

# 10. Security Considerations

### Hash Algorithm Choice

- **SHA-256**: Cryptographically secure, collision resistance ~2^128 operations (infeasible)
- **Not MD5/SHA-1**: Known vulnerabilities, collision attacks demonstrated

### Lock Hijacking Prevention

- Lock value is request_id (UUID), prevents different request from releasing lock
- TTL ensures locks auto-expire (no manual release needed for crash scenarios)

### Cache Poisoning

- Only internal service writes to `dedup:hash:{hash}` (no user input)
- Storage verification before finalization (FEAT-001) prevents phantom metadata

---

# 11. Performance Considerations

### Hash Calculation Performance

- Streaming hash calculation (1MB chunks) prevents memory exhaustion on large files
- For 100MB file: ~200ms hash calculation time (SSD I/O bound, not CPU)
- Parallelizable for multipart uploads (hash parts, combine — FEAT-005)

### Cache Hit Optimization

- 24-hour TTL balances cache size vs. hit rate (longer TTL = more hits)
- LRU eviction policy ensures hot files remain cached
- Estimated cache memory: 10M files × 128 bytes (key + value) = 1.28GB

### Database Query Optimization

- B-tree index on `sha256_hash` enables <5ms exact match queries
- Index only on non-NULL values (PARTIAL INDEX) reduces size
- Connection pooling (20 connections) prevents saturation

### Lock Contention Mitigation

- 10-second TTL is conservative (hash collision probability negligible)
- Retry with 50ms backoff allows lock holder to complete
- Fail-open after 3 retries (150ms total wait) prevents deadlock

---

# 12. Deployment Notes

### Configuration

**Environment Variables**:

```bash
# Deduplication settings
DEDUP_CACHE_TTL=86400                  # 24 hours
DEDUP_LOCK_TTL=10                      # 10 seconds
DEDUP_LOCK_RETRY_MAX=3
DEDUP_LOCK_RETRY_DELAY_MS=50

# Feature flag (for rollout)
DEDUP_ENABLED=true
```

### Database Migration

```bash
# Run migration
psql -d filestore -f migrations/003_add_sha256_hash_column.sql

# Verify index created
SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'files' AND indexname = 'idx_files_sha256_hash';
```

### Rollback Plan

- Disable feature via `DEDUP_ENABLED=false` (all uploads proceed without dedup check)
- Rollback migration: `ALTER TABLE files DROP COLUMN sha256_hash;`
- Redis keys expire after 24 hours (no manual cleanup needed)

### Monitoring

- Track dedup hit rate: `(cache_hits + db_hits) / total_checks`
- Alert if hit rate <10% (workload change or cache eviction issue)
- Alert if lock acquisition failures >1% (contention issue)
- Dashboard: Daily storage cost savings (duplicates avoided × avg file size × price)

---

# 13. Open Questions

- [ ] Should we backfill `sha256_hash` for existing files (migration script)?
- [ ] Do we need admin API to force cache invalidation for specific hash?
- [ ] Should we implement reference counting for garbage collection (track file_count per storage_key)?
- [ ] How do we handle SHA-256 collision (theoretical) — verify file content byte-by-byte?
