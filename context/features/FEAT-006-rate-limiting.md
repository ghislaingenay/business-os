# FEAT-006: Rate Limiting

Status: Not Started
Owner: TBD
Created: 2026-08-11
Last Updated: 2026-08-11

Technical Design: [TD-006 - Rate Limiting](../technical-designs/TD-006-rate-limiting.md)

---

# 1. Overview

## Summary

Implement token bucket rate limiting with sliding window tracking using Redis to prevent abuse, ensure fair usage, and protect backend resources. Applied per-user (JWT sub claim) with configurable limits for different operations (upload, initiate, finalize).

## Problem

- **API abuse**: Malicious users flood upload endpoints, degrading service for legitimate users
- **Resource exhaustion**: Unlimited uploads overwhelm storage API rate limits, workers, database
- **Cost control**: Unbounded usage leads to unexpected cloud bills (storage, bandwidth, workers)
- **No QoS enforcement**: Power users impact regular users by consuming all available capacity

## Goals

- Enforce per-user upload rate limits (e.g., 100 uploads/hour, 10 uploads/minute)
- Support burst capacity (e.g., 20 uploads in 1 minute, then throttle)
- Sliding window accuracy (not bucket-based approximation)
- Rate limit different operations independently (upload, initiate, finalize)
- Return clear error messages with retry-after headers

## Non-Goals

- IP-based rate limiting (use JWT user identity only)
- Dynamic rate limits per user tier (single global limit for MVP)
- Distributed rate limiting across multiple Redis clusters

---

# 2. Users

## Primary Users

- **All API consumers**: Protected from service degradation caused by abuse
- **Platform administrators**: Monitor and adjust rate limits based on usage patterns

## Stakeholders

- **Backend engineers**: Maintain rate limiting logic, monitor Redis performance
- **Security team**: Prevent DoS attacks via API abuse

---

# 3. User Stories

### Story 1: Fair Usage Enforcement

As a **regular user**
I want to **experience consistent upload performance**
So that **power users don't consume all backend capacity**

### Story 2: Burst Tolerance

As a **photographer uploading a photo batch**
I want to **upload 15 photos quickly (burst)**
So that **I don't get rate limited during normal batch upload workflow**

### Story 3: Clear Error Messages

As a **API consumer hitting rate limit**
I want to **receive a 429 response with retry-after header**
So that **I know exactly when I can retry my request**

---

# 4. Product Requirements

## Functional Requirements

### FR-1: Per-User Rate Limits

**Requirement**: Apply rate limits per JWT user identity (sub claim)

#### Acceptance Criteria

- [ ] Rate limit key: `ratelimit:upload:{user_id}`
- [ ] Limits: 100 uploads/hour, 10 uploads/minute (whichever is reached first)
- [ ] Anonymous requests (no JWT): Rate limit by IP (fallback, stricter limits)

### FR-2: Token Bucket Algorithm

**Requirement**: Implement token bucket with sliding window tracking

#### Acceptance Criteria

- [ ] Bucket capacity: 20 tokens (burst size)
- [ ] Refill rate: 10 tokens/minute (average throughput)
- [ ] Tokens deducted on each request (1 token per upload)
- [ ] Requests blocked when bucket empty (return 429)

### FR-3: Multiple Rate Limit Windows

**Requirement**: Enforce both per-minute and per-hour limits simultaneously

#### Acceptance Criteria

- [ ] Check both windows: `ratelimit:upload:minute:{user_id}`, `ratelimit:upload:hour:{user_id}`
- [ ] Block request if either limit exceeded
- [ ] Return smallest retry-after value in error response

### FR-4: Rate Limit Headers

**Requirement**: Include rate limit metadata in all API responses

#### Acceptance Criteria

- [ ] Headers: `X-RateLimit-Limit: 10`, `X-RateLimit-Remaining: 7`, `X-RateLimit-Reset: 1628097600`
- [ ] On 429 error: `Retry-After: 45` (seconds until reset)
- [ ] Headers present on both success and rate-limited responses

### FR-5: Graceful Degradation

**Requirement**: Continue accepting requests if Redis unavailable (fail-open)

#### Acceptance Criteria

- [ ] Redis connection error: Log warning, allow request through
- [ ] Alert if degradation lasts >5 minutes
- [ ] Metrics track bypass rate: `rate_limit_bypassed / total_requests`

---

# 5. Success Metrics

- **Rate limit enforcement accuracy**: >99.5% (requests blocked when limit exceeded)
- **Redis latency**: p95 <10ms (rate limit check)
- **Bypass rate during degradation**: <0.1% (Redis highly available)
- **User experience**: Clear 429 error messages with actionable retry-after guidance

---

# 6. Dependencies

- Depends on: None (uses existing Redis infrastructure)
- Blocks: None (can be deployed independently)
- Related: **FEAT-003** (Deduplication) — uses same Redis connection pool

---

# 7. Implementation Plan

## Single PR Implementation

**Scope**: Complete rate limiting with token bucket, sliding window, graceful degradation

**Deliverables**:

- [ ] `src/ratelimit/limiter.py` (token bucket implementation)
- [ ] `src/ratelimit/middleware.py` (FastAPI middleware)
- [ ] Redis key conventions: `ratelimit:{operation}:{window}:{user_id}`
- [ ] Configuration: Limits per operation (upload, initiate, finalize)
- [ ] Unit tests (mock Redis)
- [ ] Integration tests (real Redis, verify limits enforced)
- [ ] Graceful degradation tests (Redis down)
- [ ] Metrics logging: `rate_limit_exceeded`, `rate_limit_check_latency_ms`

**Estimated Size**: ~6 files, ~350 LOC

---

# 8. Open Questions

- [ ] Should we support per-user tier limits (free vs. paid accounts)?
- [ ] Do we need admin API to temporarily increase user limits?
- [ ] Should we rate limit variant generation jobs (prevent worker queue flooding)?
- [ ] How do we handle IP-based rate limiting for anonymous requests?
