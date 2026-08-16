# FEAT-007: Observability

Status: Done
Owner: TBD
Created: 2026-08-11
Last Updated: 2026-08-16

Technical Design: [TD-007 - Observability](../technical-designs/TD-007-observability.md)

---

# 1. Overview

## Summary

Implement production-grade observability with structured logging (structlog), log-based metrics extraction, distributed tracing via request IDs, and comprehensive error tracking to enable debugging, performance monitoring, and operational insights.

## Problem

- **Opaque failures**: Upload failures logged as generic errors, no context (user_id, file_size, operation)
- **No performance insights**: Cannot identify slow operations (dedup latency, variant generation bottlenecks)
- **Difficult debugging**: Logs lack correlation across services (upload → worker → storage)
- **Missing metrics**: No dedup hit rate, storage cost tracking, or error rate monitoring

## Goals

- Structured JSON logging with consistent schema (level, timestamp, message, context)
- Request ID tracking across all components (FastAPI → Redis → Worker → Storage)
- Log-based metrics (dedup_hit_rate, upload_latency_p95, variant_generation_duration)
- Error tracking with stack traces and context (user_id, file_id, operation)
- Queryable logs in production (JSON format for log aggregation tools)

## Non-Goals

- Full APM solution (Datadog/New Relic integration — future)
- Real-time alerting (log aggregation tool responsibility)
- Client-side telemetry (backend observability only)

---

# 2. Users

## Primary Users

- **Backend engineers**: Debug production issues, analyze performance bottlenecks
- **SRE/DevOps**: Monitor service health, alert on anomalies

## Stakeholders

- **Product managers**: Track feature adoption (upload types, dedup savings)
- **Finance**: Analyze storage costs via usage metrics

---

# 3. User Stories

### Story 1: Debug Failed Upload

As a **backend engineer**
I want to **search logs for specific upload failure (file_id, user_id)**
So that **I can identify root cause (storage timeout, validation error, Redis down)**

### Story 2: Performance Analysis

As an **SRE**
I want to **query p95/p99 latency for upload operations**
So that **I can detect performance degradation before users complain**

### Story 3: Cost Analysis

As a **finance analyst**
I want to **calculate storage cost savings from deduplication**
So that **I can justify infrastructure investments**

---

# 4. Product Requirements

## Functional Requirements

### FR-1: Structured Logging

**Requirement**: All logs in JSON format with consistent schema

#### Acceptance Criteria

- [ ] Schema: `{"timestamp": "ISO8601", "level": "INFO", "message": "...", "request_id": "...", "user_id": "...", "operation": "...", "context": {...}}` —
      **Partially met**: `timestamp`/`level`/`request_id` present; the
      human-readable field is named `event`, not `message` (structlog's
      positional message and a bound `event=` field can't coexist under
      distinct keys — see `shared/logging/config.py`'s docstring). `user_id`
      is never populated — there's no auth/user concept anywhere in this
      codebase yet. `operation`/`context` only appear on the specific error
      logs that add them explicitly, not universally.
- [x] Levels: DEBUG (local only), INFO (success operations), WARN (degradation), ERROR (failures)
- [x] All logs include request_id for correlation (within a request's or worker job's async context)

### FR-2: Request ID Propagation

**Requirement**: Generate request ID on ingress, propagate through all components

#### Acceptance Criteria

- [x] Generated: UUID v4 on FastAPI request entry
- [x] Header: `X-Request-ID` returned in all responses
- [x] Logged: Included in every log statement (via structlog contextvars)
- [x] Propagated: Passed to worker jobs, Redis operations, storage calls (contextvars propagate automatically within the request's async context; explicitly re-bound at worker job start from the job's `request_id` arg)

### FR-3: Metrics Logging

**Requirement**: Log structured events for key metrics extraction

#### Acceptance Criteria

- [x] Events: `dedup_check` (result, hash, latency), `upload_complete` (size, strategy, duration), `variant_generated` (type, duration)
- [x] Queryable: Log aggregation tool extracts metrics via JSON field matching
- [x] Example: `{"event": "dedup_check", "result": "hit", "latency_ms": 45, "hash": "abc..."}`

**Known gap carried over from FEAT-003** (flagged during that feature's
`review-technical-design` pass, 2026-08-14): `DedupService._find_existing`
(`src/dedup/service.py`) already logs a `dedup_check` event via stdlib
`logging` with `result`/`hash`/`source` fields, but (1) it has no `file_size`
field — `DedupService.check()`'s interface never receives a file size, so
FEAT-003 couldn't add it without a signature change, and (2) there's no JSON
log formatter configured anywhere in the app yet, so `extra={...}` currently
produces separate `LogRecord` attributes, not the literal JSON body FR-3's
own example shows.

**Resolved 2026-08-16**: `file_size` WILL be threaded through
`DedupService.check()`/`_find_existing()` so the `dedup_check` event carries
it — both `UploadService.upload_small_file()` and
`UploadService.finalize_large_upload()` already know the size (`len(content)`
and `storage_metadata.size` respectively) at their `dedup_service.check()`
call sites, so passing it through is a small signature change. The
`database_unavailable` event on the DB-unavailable path IS unified into
`dedup_check` with `result: "error"` — one event family (`dedup_check`) now
covers hit/miss/error, matching FR-1's schema intent and simplifying FR-3's
hit-rate metrics query (single event name to filter on).

### FR-4: Error Tracking

**Requirement**: Log all errors with full context and stack traces

#### Acceptance Criteria

- [ ] Context: user_id, file_id, operation, request_id — **partially met**:
      `file_id`/`operation`/`request_id` present on the error logs added by
      this feature (`storage_upload_failed`, `variant_generation_failed`);
      `user_id` is never populated (no auth/user concept in this codebase).
      Also not wired into `MultipartService.finalize()`'s storage calls,
      which have no try/except to attach error logging to.
- [x] Stack trace: Included for all exceptions (`exc_info=True` + `format_exc_info` processor, verified renders under an `exception` field)
- [x] Structured: Error type, message, context as JSON fields
- [ ] Example: `{"level": "ERROR", "error_type": "StorageProviderError", "message": "S3 timeout", "stack_trace": "...", "context": {...}}` —
      close but not literal: the exception's own message text isn't a
      separate field, only embedded in the `exception` traceback string.

### FR-5: Performance Logging

**Requirement**: Log operation latencies for p95/p99 analysis

#### Acceptance Criteria

- [x] Operations: `upload_duration_ms`, `dedup_check_duration_ms`, `variant_generation_duration_ms` (as `duration_ms`/`latency_ms` fields on the `upload_complete`/`dedup_check`/`variant_generated` events)
- [x] Logged on operation completion
- [ ] Includes operation type and outcome (success/failure) — **partially met**:
      `variant_generated` logs `outcome=success|failure`; `upload_complete`
      only ever logs `outcome="success"` — there's no corresponding
      failure-outcome emission for uploads (a failed upload never reaches
      the "complete" event at all currently).

---

# 5. Success Metrics

- **Log query response time**: <5 seconds for recent logs (last 24 hours)
- **Request ID correlation**: 100% of requests have request_id in all log statements
- **Metrics extraction accuracy**: Log-based metrics match manual counts (>99%)
- **Error context completeness**: 100% of errors include user_id, file_id, operation

---

# 6. Dependencies

- Depends on: None (foundational feature)
- Blocks: None (improves debugging for all features)
- Related: All features benefit from observability

---

# 7. Implementation Plan

## Single PR Implementation

**Scope**: structlog configuration, request ID middleware, metrics logging, error handling

**Deliverables**:

- [ ] `src/logging/config.py` (structlog setup)
- [ ] `src/logging/middleware.py` (request ID generation, propagation)
- [ ] `src/logging/metrics.py` (structured metric event helpers)
- [ ] Update all services to use structured logger
- [ ] Environment-based config (JSON in prod, console in dev)
- [ ] Unit tests for log format, request ID propagation
- [ ] Documentation: Log schema reference

**Estimated Size**: ~6 files, ~300 LOC

---

# 8. Open Questions

- [x] Should we integrate with OpenTelemetry for distributed tracing? —
      **Resolved 2026-08-16**: No, out of scope — already covered by this
      feature's own Non-Goals ("Full APM solution... future"). request_id
      correlation (FR-2) is this phase's tracing mechanism.
- [ ] Do we need log sampling (reduce volume for high-traffic operations)? —
      Out of scope for this implementation; revisit if log volume becomes an
      operational problem.
- [x] Should we log sensitive data (filenames, user emails) or sanitize? —
      **Resolved 2026-08-16**: Sanitize — the implementation logs `file_id`
      (UUID), `storage_key`, and `sha256_hash`, never raw filenames or user
      emails, matching the pattern already established in `dedup/service.py`
      and `upload/service.py` before this feature.
- [ ] How do we handle log retention (rotate after 30 days, archive to S3)? —
      Out of scope for this implementation; a log aggregation tool /
      infrastructure concern per this feature's Non-Goals, not application code.
