# TD-004: Async Variant Generation

Status: Doing
Owner: TBD
Created: 2026-08-11
Last Updated: 2026-08-15

Feature Spec: [FEAT-004 - Async Variant Generation](../features/FEAT-004-async-variant-generation.md)

---

# 1. Overview

## Summary

Redis-backed arq worker processes image variants (WebP, thumbnails) asynchronously using Pillow, with exponential backoff retry and metadata updates.

## Goals

- Decouple upload latency from variant processing
- Generate WebP (~30% smaller) and thumbnail (256x256)
- Retry failed jobs up to 3 times

## Non-Goals

- Real-time variant generation
- Video transcoding

---

# 2. Architecture

```
Upload Complete → Enqueue Job → arq Worker
                                    │
                                    ├─ Download original
                                    ├─ Generate WebP
                                    ├─ Generate thumbnail
                                    ├─ Upload variants
                                    └─ Update metadata
```

---

# 3. Components

## New Components

- `src/worker/tasks.py` — Variant generation task
- `src/image/processor.py` — Pillow-based WebP/thumbnail generator
- `src/worker/__init__.py` — arq WorkerSettings

## Modified Components

- `src/upload/service.py` — Enqueue job after upload

---

# 4. Data Model

```sql
ALTER TABLE files
ADD COLUMN web_optimized_url VARCHAR(512) NULL,
ADD COLUMN thumbnail_url VARCHAR(512) NULL,
ADD COLUMN variants_processed_at TIMESTAMP NULL;
```

**2026-08-15**: `webp_url` renamed to `web_optimized_url` per explicit user
instruction — same WebP variant, column name decoupled from the specific
codec in case the "web-optimized" format choice changes later. All
references below (`webp_key`, service/repository/schema code) use this name.

---

# 5. Sequence Flow

```
1. Upload completes → Save file metadata
2. Enqueue job: redis.enqueue("generate_variants", file_id, storage_key)
3. Worker picks job → Download original from storage
4. Generate WebP (Pillow) → Upload to storage (webp/{path})
5. Generate thumbnail → Upload to storage (thumbnails/{path})
6. UPDATE files SET webp_url=..., thumbnail_url=..., variants_processed_at=NOW()
```

---

# 6. Implementation

**arq Task**:

```python
async def generate_variants(ctx, file_id: str, storage_key: str):
    # Download original
    original = await storage.download(storage_key)

    # Generate WebP
    webp_bytes = image_processor.to_webp(original, quality=85)
    webp_key = f"webp/{storage_key.replace('originals/', '')}"
    await storage.upload(webp_key, webp_bytes)

    # Generate thumbnail
    thumb_bytes = image_processor.thumbnail(original, size=(256, 256))
    thumb_key = f"thumbnails/{storage_key.replace('originals/', '_thumb')}"
    await storage.upload(thumb_key, thumb_bytes)

    # Update metadata
    await db.execute(
        "UPDATE files SET webp_url=?, thumbnail_url=?, variants_processed_at=NOW() WHERE file_id=?",
        webp_key,
        thumb_key,
        file_id,
    )
```

---

# 7. Testing Strategy

- [x] Unit tests: Pillow processing (WebP, thumbnail) — `tests/shared/image/test_processor.py`
- [x] Integration tests: End-to-end with worker (upload → variants appear in storage)
      — split across `tests/variants/test_service.py` (service → real S3 via
      moto) and `tests/worker/test_tasks.py` (arq task boundary); no test hits
      a live Redis/arq worker process, matching this repo's existing
      convention of not exercising live infra anywhere in the suite (see
      `tests/test_database.py`'s docstring)
- [x] Retry tests: Simulate storage failure, verify 3 retries — `tests/worker/test_tasks.py`
      (parametrized over the 1s/5s/25s backoff schedule, plus exhaustion)
- [ ] Performance tests: Measure p95 latency for 5MB images — not implemented;
      no other feature in this repo has an automated perf-test harness either,
      so this is left to manual/production observation, consistent with existing practice

---

# 8. Deployment Notes

**arq Worker Configuration**:

```python
class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(os.getenv("REDIS_URL"))
    functions = [generate_variants]
    max_jobs = 10  # Concurrent jobs per worker
    job_timeout = 60  # seconds
```

**Docker Compose**: implemented as the `worker` service in `docker-compose.yml`
(env vars point at the compose network's `postgres`/`minio`/`redis` hostnames
rather than `localhost`, and `command` is `arq worker.WorkerSettings` — this
repo's package is `worker`, not `app.worker`). Required adding a top-level
`Dockerfile`, since the app had none before this feature — it previously only
ran locally via `uvicorn`/`make run`. For local (non-Docker) dev, `make worker`
runs the same `arq worker.WorkerSettings` command directly against `.env`.
