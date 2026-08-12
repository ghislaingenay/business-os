# TD-006: Rate Limiting

Status: Not Started
Owner: TBD
Created: 2026-08-11
Last Updated: 2026-08-11

Feature Spec: [FEAT-006 - Rate Limiting](../features/FEAT-006-rate-limiting.md)

---

# 1. Overview

## Summary

Token bucket rate limiting with Redis sorted sets for sliding window tracking, implemented as FastAPI middleware with per-user (JWT) and per-operation limits.

## Goals

- Enforce 100 uploads/hour, 10 uploads/minute per user
- Sub-10ms rate limit check latency
- Graceful degradation (fail-open if Redis down)

## Non-Goals

- IP-based rate limiting (JWT user identity only)
- Dynamic per-user tier limits

---

# 2. Architecture

```
Request → Rate Limit Middleware
             │
             ├─ Extract user_id (JWT)
             ├─ Check Redis (token bucket)
             │     └─ ZADD ratelimit:upload:minute:{user_id} {timestamp} {timestamp}
             │     └─ ZCOUNT ratelimit:upload:minute:{user_id} {now-60s} {now}
             │     └─ Compare count vs. limit (10)
             ├─ Allowed? → Continue to handler
             └─ Blocked? → Return 429 with Retry-After header
```

---

# 3. Implementation

**Token Bucket Check** (Redis Lua script for atomicity):

```lua
-- ratelimit_check.lua
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])  -- 60 seconds for minute window
local limit = tonumber(ARGV[3])   -- 10 for minute limit

-- Remove expired entries
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)

-- Count current entries
local count = redis.call('ZCOUNT', key, now - window, now)

if count < limit then
    -- Add new entry
    redis.call('ZADD', key, now, now)
    redis.call('EXPIRE', key, window)
    return {1, limit - count - 1}  -- [allowed, remaining]
else
    -- Get oldest entry timestamp to calculate retry-after
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = math.ceil(oldest[2] + window - now)
    return {0, 0, retry_after}  -- [blocked, remaining, retry_after]
end
```

**FastAPI Middleware**:

```python
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse


class RateLimitMiddleware:
    async def __call__(self, request: Request, call_next):
        user_id = extract_user_id(request)  # From JWT
        operation = get_operation(request)  # upload, initiate, finalize

        # Check minute window
        allowed_min, remaining_min, retry_min = await check_rate_limit(
            f"ratelimit:{operation}:minute:{user_id}", window=60, limit=10
        )

        # Check hour window
        allowed_hour, remaining_hour, retry_hour = await check_rate_limit(
            f"ratelimit:{operation}:hour:{user_id}", window=3600, limit=100
        )

        if not (allowed_min and allowed_hour):
            retry_after = min(retry_min or 60, retry_hour or 3600)
            return JSONResponse(
                status_code=429,
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": "10",
                    "X-RateLimit-Remaining": "0",
                },
                content={
                    "error": "rate_limit_exceeded",
                    "message": f"Rate limit exceeded. Retry after {retry_after} seconds.",
                    "retry_after": retry_after,
                },
            )

        # Add rate limit headers to response
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = "10"
        response.headers["X-RateLimit-Remaining"] = str(remaining_min)
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + 60)

        return response
```

---

# 4. Redis Keys

- `ratelimit:upload:minute:{user_id}` — Sorted set (timestamp → timestamp)
- `ratelimit:upload:hour:{user_id}` — Sorted set
- TTL: 60s (minute), 3600s (hour)

---

# 5. Testing Strategy

- [ ] Unit tests: Token bucket logic, limit enforcement
- [ ] Integration tests: Verify 10th request blocked, 11th allowed after 60s
- [ ] Graceful degradation tests: Redis down, requests allowed
- [ ] Performance tests: Measure Redis latency under load

---

# 6. Deployment Notes

**Configuration**:

```bash
RATE_LIMIT_UPLOAD_PER_MINUTE=10
RATE_LIMIT_UPLOAD_PER_HOUR=100
RATE_LIMIT_ENABLED=true
```

**Middleware Registration**:

```python
app.add_middleware(RateLimitMiddleware)
```
