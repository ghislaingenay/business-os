# TD-007: Observability

Status: Not Started
Owner: TBD
Created: 2026-08-11
Last Updated: 2026-08-11

Feature Spec: [FEAT-007 - Observability](../features/FEAT-007-observability.md)

---

# 1. Overview

## Summary

Structured logging with structlog, request ID correlation, log-based metrics extraction, and comprehensive error tracking for production debugging and performance monitoring.

## Goals

- JSON-formatted logs for machine parsing
- Request ID propagation across all layers
- Log-based metrics (dedup hit rate, latencies)
- Complete error context (user, file, operation, stack trace)

## Non-Goals

- Full APM integration (Datadog/New Relic)
- Real-time alerting (handled by log aggregation tool)

---

# 2. Architecture

```
Request → Generate request_id → Bind to logger context
             │
             ├─ All log statements include request_id
             ├─ Propagate to worker jobs
             ├─ Include in storage provider calls
             └─ Return in X-Request-ID header
```

---

# 3. Implementation

**structlog Configuration**:

```python
import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()
```

**Request ID Middleware**:

```python
from fastapi import Request
import uuid
import structlog


class RequestIDMiddleware:
    async def __call__(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        return response
```

**Metrics Logging**:

```python
def log_dedup_check(result: str, hash: str, latency_ms: int):
    logger.info(
        "dedup_check",
        event="dedup_check",
        result=result,  # "hit" | "miss"
        hash=hash[:16],  # Truncated for logs
        latency_ms=latency_ms,
    )


def log_upload_complete(file_id: str, size: int, strategy: str, duration_ms: int):
    logger.info(
        "upload_complete",
        event="upload_complete",
        file_id=file_id,
        size=size,
        strategy=strategy,  # "mediated" | "presigned"
        duration_ms=duration_ms,
    )
```

**Error Logging**:

```python
try:
    await storage.upload(key, stream)
except Exception as e:
    logger.error(
        "storage_upload_failed",
        error_type=type(e).__name__,
        error_message=str(e),
        file_id=file_id,
        user_id=user_id,
        operation="upload",
        exc_info=True,  # Includes stack trace
    )
    raise
```

---

# 4. Log Schema

**Standard Fields**:

- `timestamp`: ISO8601 (2026-08-11T10:30:00.123Z)
- `level`: DEBUG | INFO | WARNING | ERROR
- `message`: Human-readable description
- `request_id`: UUID v4 for correlation
- `event`: Event type (upload_complete, dedup_check, etc.)

**Context Fields** (operation-dependent):

- `user_id`, `file_id`, `operation`, `duration_ms`, `size`, `hash`, `result`

**Example Log**:

```json
{
  "timestamp": "2026-08-11T10:30:00.123Z",
  "level": "INFO",
  "event": "dedup_check",
  "message": "Deduplication check completed",
  "request_id": "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d",
  "user_id": "user_123",
  "file_id": "550e8400-e29b-41d4-a716-446655440000",
  "result": "hit",
  "latency_ms": 45,
  "hash": "e3b0c44298fc1c14"
}
```

---

# 5. Metrics Extraction

**Log Aggregation Query Examples** (pseudo-SQL):

```sql
-- Dedup hit rate
SELECT
  COUNT(*) FILTER (WHERE result = 'hit') * 100.0 / COUNT(*) AS hit_rate_pct
FROM logs
WHERE event = 'dedup_check' AND timestamp > NOW() - INTERVAL '1 hour';

-- p95 upload latency
SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_latency
FROM logs
WHERE event = 'upload_complete' AND timestamp > NOW() - INTERVAL '1 hour';

-- Error rate by operation
SELECT operation, COUNT(*) AS error_count
FROM logs
WHERE level = 'ERROR' AND timestamp > NOW() - INTERVAL '1 hour'
GROUP BY operation
ORDER BY error_count DESC;
```

---

# 6. Testing Strategy

- [ ] Unit tests: Verify JSON log format, request_id present
- [ ] Integration tests: Verify request_id propagated (FastAPI → worker → storage)
- [ ] Metrics tests: Query logs, verify metric calculations match expected

---

# 7. Deployment Notes

**Configuration**:

```bash
LOG_LEVEL=INFO              # DEBUG in dev, INFO in prod
LOG_FORMAT=json             # json | console (for dev readability)
LOG_REQUEST_BODIES=false    # Privacy: Don't log request bodies in prod
```

**Log Aggregation**:

- Use ELK (Elasticsearch, Logstash, Kibana) or Loki for centralized logging
- Retention: 30 days in hot storage, 90 days in cold storage (S3)
