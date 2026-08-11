# TD-004: Async Variant Generation

Status: Not Started
Owner: TBD
Created: 2026-08-11
Last Updated: 2026-08-11

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
ADD COLUMN webp_url VARCHAR(512) NULL,
ADD COLUMN thumbnail_url VARCHAR(512) NULL,
ADD COLUMN variants_processed_at TIMESTAMP NULL;
```

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
        webp_key, thumb_key, file_id
    )
```

---

# 7. Testing Strategy

- [ ] Unit tests: Pillow processing (WebP, thumbnail)
- [ ] Integration tests: End-to-end with worker (upload → variants appear in storage)
- [ ] Retry tests: Simulate storage failure, verify 3 retries
- [ ] Performance tests: Measure p95 latency for 5MB images

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

**Docker Compose**:

```yaml
worker:
  build: .
  command: arq app.worker.WorkerSettings
  environment:
    - REDIS_URL=redis://redis:6379
    - STORAGE_PROVIDER=s3
```
