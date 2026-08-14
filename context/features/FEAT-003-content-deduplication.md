# FEAT-003: Content-Based Deduplication

Status: Doing
Owner: TBD
Created: 2026-08-11
Last Updated: 2026-08-14

Technical Design: [TD-003 - Content-Based Deduplication](../technical-designs/TD-003-content-deduplication.md)

---

# 1. Overview

## Summary

Implement content-based deduplication using SHA-256 hashing to detect and eliminate duplicate file uploads, storing identical content only once while allowing multiple logical file records to reference the same physical storage object. Includes Redis-based cache and distributed lock coordination to prevent race conditions.

## Problem

Without deduplication:

- **Storage waste**: Users uploading the same profile picture across accounts stores N copies
- **Cost inefficiency**: Cloud storage costs scale linearly with redundant content
- **Bandwidth waste**: Re-uploading identical content to storage wastes transfer costs
- **Slower uploads**: Unnecessary storage API calls increase latency

## Goals

- Detect duplicate content by SHA-256 hash before uploading to storage
- Reuse existing storage keys for duplicate content
- Prevent race conditions when multiple users upload identical files concurrently
- Maintain separate file metadata records (different filenames, ownership, timestamps)
- Cache hash→storage_key mappings in Redis for fast lookups
- Fallback to database if Redis unavailable (graceful degradation)

## Non-Goals

- Partial deduplication (block-level or chunk-level)
- Cross-bucket deduplication (only dedupe within single storage bucket)
- Automatic cleanup of unused storage keys (garbage collection — future feature)
- Deduplication of variant files (each variant stored separately)

---

# 2. Users

## Primary Users

- **End users**: Benefit from faster uploads (dedup hits skip upload)
- **Application owners**: Reduce storage and bandwidth costs

## Stakeholders

- **Backend engineers**: Maintain dedup logic, monitor hit rates
- **DevOps**: Monitor Redis cache performance, alert on degradation
- **Finance**: Track storage cost savings from deduplication

---

# 3. User Stories

### Story 1: Upload Common Profile Picture

As a **social media platform user**
I want to **upload a default profile picture (that 1000 other users also chose)**
So that **my upload completes instantly without re-uploading existing content**

**Acceptance**: Upload returns in <100ms (dedup cache hit, no storage API call)

### Story 2: Upload Identical Document

As a **document management system user**
I want to **upload a company policy PDF (already uploaded by HR team)**
So that **the system stores one copy but both my account and HR account can access it**

**Acceptance**: Two file records with different owners, same storage_key

### Story 3: Concurrent Upload of Same File

As a **developer testing the system**
I want to **upload the same file from 10 concurrent requests**
So that **only one upload to storage occurs, all requests return success, no duplicate storage keys**

**Acceptance**: Redis lock prevents race, 1 storage upload, 10 database records

---

# 4. Product Requirements

## Functional Requirements

### FR-1: Content Hash Calculation

**Requirement**: Calculate SHA-256 hash of file content before deduplication check

#### Acceptance Criteria

- [ ] Hash calculated for all uploads (small and large files)
- [ ] Hash calculated on complete file content (not partial)
- [ ] For mediated uploads: Hash calculated in-memory during upload processing
- [ ] For presigned URL uploads: Hash calculated after upload completes (on finalize)
- [ ] Hash stored in `files.sha256_hash` column (CHAR(64) hex-encoded)

### FR-2: Deduplication Check via Redis Cache

**Requirement**: Check Redis for hash→storage_key mapping before uploading to storage

#### Acceptance Criteria

- [ ] Redis key format: `dedup:hash:{sha256_hash}` → `{storage_key}`
- [ ] Cache TTL: 24 hours (renewed on every hit)
- [ ] Cache hit: Return existing storage_key without storage API call
- [ ] Cache miss: Fallback to database query
- [ ] Metrics logged: `dedup_check_result` (hit/miss/error)

### FR-3: Database Fallback for Cache Misses

**Requirement**: Query database for hash→storage_key mapping if Redis unavailable or cache miss

#### Acceptance Criteria

- [ ] Query: `SELECT storage_key FROM files WHERE sha256_hash = $1 LIMIT 1`
- [ ] If found: Write to Redis cache (populate cache), return storage_key
- [ ] If not found: Proceed with upload to storage
- [ ] Database query timeout: 5 seconds (fail fast)

### FR-4: Distributed Lock for Race Prevention

**Requirement**: Acquire distributed lock during dedup check to prevent concurrent duplicate uploads

#### Acceptance Criteria

- [ ] Lock key format: `lock:hash:{sha256_hash}`
- [ ] Lock acquired via Redis `SET NX EX 10` (10-second TTL)
- [ ] Lock acquisition failure: Wait 50ms, retry up to 3 times, then proceed (fail-open)
- [ ] Lock released after upload completes (or on failure)
- [ ] Metrics logged: `dedup_lock_acquired`, `dedup_lock_wait_time_ms`

### FR-5: Cache Population on Upload

**Requirement**: Write hash→storage_key to Redis and database after successful upload

#### Acceptance Criteria

- [ ] Write to both Redis and database in parallel (dual-write pattern)
- [ ] Redis write failure: Log warning, continue (graceful degradation)
- [ ] Database write failure: Return 500, rollback storage upload if possible
- [ ] Redis write includes 24-hour TTL
- [ ] Database write includes full file metadata

### FR-6: Deduplication Metrics

**Requirement**: Track deduplication hit rate for monitoring and cost analysis

#### Acceptance Criteria

- [ ] Log structured event: `{"event": "dedup_check", "result": "hit|miss", "hash": "abc...", "file_size": 12345}`
- [ ] Calculate hit rate: `(cache_hits + db_hits) / total_checks`
- [ ] Alert if hit rate drops below 10% (indicates cache issues or workload change)
- [ ] Dashboard displays: Daily hit rate, cost savings estimate

---

# 5. Success Metrics

- **Deduplication hit rate**: >20% (depends on workload, higher is better)
- **Cache hit latency**: p95 <50ms (Redis lookup + metadata return)
- **Database fallback latency**: p95 <200ms (PostgreSQL query)
- **Lock acquisition success rate**: >99% (most requests acquire lock immediately)
- **Storage cost savings**: Measured as (duplicates avoided × avg file size × storage price)

---

# 6. Dependencies

- Depends on: **FEAT-002** (Hybrid Upload Strategy) — dedup integrated into upload flow
- Depends on: **FEAT-001** (Storage Provider Abstraction) — requires storage interface
- Blocks: None (other features can proceed independently)
- Related: **FEAT-006** (Rate Limiting) — uses same Redis infrastructure

---

# 7. Implementation Plan

## Single PR Implementation

**Scope**: Complete deduplication logic with Redis cache, database fallback, and distributed locking

**Rationale**: Deduplication is a cohesive feature with tightly coupled components (hash calculation, cache lookup, lock coordination). Splitting would create incomplete states and testing complexity.

**Estimated Size**: ~10 files, ~600 LOC

**Deliverables**:

- [ ] `src/dedup/service.py` (deduplication service with hash calculation, cache check, lock coordination)
- [ ] `src/dedup/cache.py` (Redis cache adapter for hash→storage_key mappings)
- [ ] Modify `src/upload/service.py` (integrate dedup check into upload flow)
- [ ] Add `sha256_hash` column to `files` table (migration)
- [ ] Redis key conventions documented in `docs/redis-keys.md`
- [ ] Unit tests for hash calculation, cache logic, lock coordination
- [ ] Integration tests for race conditions (concurrent uploads of same file)
- [ ] Integration tests for graceful degradation (Redis down, database fallback)
- [ ] Metrics logging for dedup hit rate
- [ ] OpenAPI schema updates (expose `sha256_hash` in file metadata response)

**Merge Requirements**: All tests pass, integration tests verify race prevention, graceful degradation tested

---

# 8. Open Questions

- [x] Should we expose SHA-256 hash in file metadata response for client-side verification?
      **Resolved — already answered in TD-003 §5**: yes, `sha256_hash` is included in the
      API response as an optional field.
- [x] How do we handle hash collisions (theoretically possible with SHA-256, probability ~10^-60)?
      **Resolved 2026-08-14** (see TD-003 §13): trust the hash match, no byte-by-byte
      verification — matches SHA-256's collision-resistance rationale and preserves the
      dedup-hit latency targets.
- [ ] Should we implement garbage collection for unreferenced storage keys (ref counting)?
      Out of scope: listed under FEAT-003 §1 Non-Goals as a future feature.
- [ ] Do we need admin API to manually invalidate cache for specific hash (force re-dedup)?
      Out of scope: not part of the Single PR Implementation deliverables (§7).
- [x] Should we support client-provided hashes to skip server-side calculation (trust model)?
      **Resolved — already answered by FR-1**: hash is always calculated server-side
      (in-memory for mediated uploads, on finalize for presigned); accepting a
      client-supplied hash would let a client claim dedup against content it never
      uploaded.
