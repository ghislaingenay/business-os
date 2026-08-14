# FEAT-007: Observability

Status: Not Started
Owner: TBD
Created: 2026-08-11
Last Updated: 2026-08-11

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

- [ ] Schema: `{"timestamp": "ISO8601", "level": "INFO", "message": "...", "request_id": "...", "user_id": "...", "operation": "...", "context": {...}}`
- [ ] Levels: DEBUG (local only), INFO (success operations), WARN (degradation), ERROR (failures)
- [ ] All logs include request_id for correlation

### FR-2: Request ID Propagation

**Requirement**: Generate request ID on ingress, propagate through all components

#### Acceptance Criteria

- [ ] Generated: UUID v4 on FastAPI request entry
- [ ] Header: `X-Request-ID` returned in all responses
- [ ] Logged: Included in every log statement
- [ ] Propagated: Passed to worker jobs, Redis operations, storage calls

### FR-3: Metrics Logging

**Requirement**: Log structured events for key metrics extraction

#### Acceptance Criteria

- [ ] Events: `dedup_check` (result, hash, latency), `upload_complete` (size, strategy, duration), `variant_generated` (type, duration)
- [ ] Queryable: Log aggregation tool extracts metrics via JSON field matching
- [ ] Example: `{"event": "dedup_check", "result": "hit", "latency_ms": 45, "hash": "abc..."}`

**Known gap carried over from FEAT-003** (flagged during that feature's
`review-technical-design` pass, 2026-08-14): `DedupService._find_existing`
(`src/dedup/service.py`) already logs a `dedup_check` event via stdlib
`logging` with `result`/`hash`/`source` fields, but (1) it has no `file_size`
field — `DedupService.check()`'s interface never receives a file size, so
FEAT-003 couldn't add it without a signature change, and (2) there's no JSON
log formatter configured anywhere in the app yet, so `extra={...}` currently
produces separate `LogRecord` attributes, not the literal JSON body FR-3's
own example shows. When FEAT-007's `structlog` config lands, either thread
`file_size` through `DedupService.check()`/`_find_existing()` so the event
carries it, or accept the gap and document why. The DB-unavailable path also
emits a separate `database_unavailable` event rather than a `dedup_check`
event with `result: "error"` — worth deciding whether FR-3's "result" field
should unify hit/miss/error into one event family per this feature's own
FR-1 schema, or keep error logging on its own event name.

### FR-4: Error Tracking

**Requirement**: Log all errors with full context and stack traces

#### Acceptance Criteria

- [ ] Context: user_id, file_id, operation, request_id
- [ ] Stack trace: Included for all exceptions
- [ ] Structured: Error type, message, context as JSON fields
- [ ] Example: `{"level": "ERROR", "error_type": "StorageProviderError", "message": "S3 timeout", "stack_trace": "...", "context": {...}}`

### FR-5: Performance Logging

**Requirement**: Log operation latencies for p95/p99 analysis

#### Acceptance Criteria

- [ ] Operations: `upload_duration_ms`, `dedup_check_duration_ms`, `variant_generation_duration_ms`
- [ ] Logged on operation completion
- [ ] Includes operation type and outcome (success/failure)

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

- [ ] Should we integrate with OpenTelemetry for distributed tracing?
- [ ] Do we need log sampling (reduce volume for high-traffic operations)?
- [ ] Should we log sensitive data (filenames, user emails) or sanitize?
- [ ] How do we handle log retention (rotate after 30 days, archive to S3)?
