# File Storage Service - Project Overview

## Executive Summary

FastAPI-based file/image storage service with content-based deduplication, async variant generation, and hybrid upload strategy. Designed for production-grade distributed systems with proper concurrency handling, observability, and storage provider abstraction.

**Core Value Proposition**: Efficient, scalable file storage that reduces costs through deduplication, optimizes delivery through variant generation (WebP, thumbnails), and avoids vendor lock-in through storage abstraction.

---

## Problem Statement

Modern applications need robust file storage that can:

- **Handle uploads efficiently** without becoming a bandwidth bottleneck (hybrid strategy: mediated ≤2MB, presigned URLs for large files)
- **Prevent duplicate storage** of identical content to save costs (content-based deduplication)
- **Generate web-optimized variants** (WebP, thumbnails) for performance without blocking uploads
- **Scale under load** with proper concurrency handling (Redis coordination, async workers)
- **Support multiple storage backends** (S3, GCS, R2, MinIO) without lock-in

**Why it matters**: Poor implementations lead to wasted storage, slow page loads, race conditions under concurrent uploads, and vendor lock-in.

---

## Architecture Overview

### System Components

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │
       │ ≤2MB: POST /upload (mediated)
       │ >2MB: POST /upload/initiate → presigned URL
       │
┌──────▼──────────────────────────────┐
│         FastAPI Service             │
│  - Upload validation                │
│  - Deduplication check (Redis + DB) │
│  - Multipart session tracking       │
│  - Rate limiting (Redis)            │
└──────┬──────────────────────────────┘
       │
       ├─────────────┬────────────────┬────────────────┐
       │             │                │                │
┌──────▼──────┐ ┌───▼─────┐ ┌────────▼─────┐ ┌───────▼────────┐
│   Redis     │ │Database │ │Storage Provider│ │  Worker Queue  │
│             │ │         │ │ (S3/GCS/R2)    │ │  (arq/Celery)  │
│- Dedup cache│ │- File   │ │                │ │                │
│- Rate limits│ │  metadata│ │- Original      │ │- WebP gen      │
│- MP sessions│ │- Hash→Key│ │- Variants      │ │- Thumbnail gen │
│- Locks      │ │  mapping│ │                │ │                │
└─────────────┘ └─────────┘ └────────────────┘ └────────────────┘
```

### Key Design Patterns

1. **Storage Adapter Pattern**: Abstract interface (`StorageProvider`) with implementations per backend, swap providers without touching service layer
2. **Dependency Injection**: Configuration-driven provider selection, services receive dependencies (storage, Redis, DB) via constructor injection, enabling easy testing and swapping implementations
3. **Content-based Deduplication**: SHA-256 hash → check Redis/DB → reuse existing storage key or upload new
4. **Hybrid Upload Strategy**: Backend-mediated (≤2MB) for simplicity, presigned URLs (>2MB) for bandwidth efficiency
5. **Async Worker Pipeline**: Decouple upload latency from variant generation (WebP + thumbnails)
6. **Redis Coordination**: Locks for dedup race prevention, sliding window rate limiting, multipart session state

---

## Core Features

### Phase 1: MVP (Core Functionality)

- ✅ **Hybrid upload** (≤2MB mediated, >2MB presigned)
- ✅ **Content-based deduplication** (SHA-256, Redis lock to prevent races)
- ✅ **Storage provider abstraction** (S3, GCS, R2, MinIO)
- ✅ **Async variant generation** (WebP + thumbnail via worker)
- ✅ **Multipart upload support** (session tracking, part retry, ETags)
- ✅ **Rate limiting** (per-user token bucket, Redis-backed)
- ✅ **Observability** (structured logging, metrics, distributed tracing)

### Phase 2: Extensions (Future)

- 🔲 **CDN integration** (CloudFront/Cloudflare with signed URLs)
- 🔲 **Malware scanning** (ClamAV self-hosted or AWS GuardDuty)
- 🔲 **Content moderation** (Sightengine/AWS Rekognition for NSFW detection)
- 🔲 **Video transcoding** (HLS/DASH segmentation, adaptive bitrate)

---

## Technical Stack

### Backend

- **Framework**: FastAPI (async Python, auto-docs, type safety)
- **Worker**: arq (Redis-native, async) or Celery (multi-queue, priority routing)
- **Image Processing**: Pillow (WebP conversion, thumbnail generation)

### Infrastructure

- **Coordination**: Redis (locks, rate limiting, session state, dedup cache)
- **Database**: PostgreSQL (file metadata, hash→storage key mapping)
- **Storage**: Pluggable (AWS S3, GCS, Cloudflare R2, MinIO)

### Observability

- **Logging**: structlog (structured JSON logs with metrics embedded)
- **Metrics**: Log-based metrics (dedup hit rate, variant latency, error rates logged as structured events)
- **Tracing**: Basic request ID tracking across FastAPI → Redis → Worker → Storage

### Deployment

- **Dev**: Docker Compose (FastAPI + Redis + MinIO + Worker)
- **Prod**: Kubernetes (autoscaling workers, Redis HA, multi-region storage)

---

## Local Development Setup

### Docker Compose Configuration

The project includes a complete Docker Compose setup for local development and testing, eliminating the need for cloud services during development.

**Services Included**:

```yaml
services:
  # API Service
  fastapi:
    build: .
    ports:
      - "8000:8000"
    environment:
      - STORAGE_PROVIDER=s3
      - S3_ENDPOINT=http://minio:9000
      - S3_ACCESS_KEY=minioadmin
      - S3_SECRET_KEY=minioadmin
      - S3_BUCKET=uploads
      - REDIS_URL=redis://redis:6379
      - DATABASE_URL=postgresql://user:password@postgres:5432/filestore
    depends_on:
      - redis
      - postgres
      - minio
      - worker

  # Redis for coordination
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data

  # PostgreSQL for metadata
  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=filestore
    volumes:
      - postgres_data:/var/lib/postgresql/data

  # MinIO for S3-compatible storage
  minio:
    image: minio/minio:latest
    ports:
      - "9000:9000" # API
      - "9001:9001" # Console
    environment:
      - MINIO_ROOT_USER=minioadmin
      - MINIO_ROOT_PASSWORD=minioadmin
    command: server /data --console-address ":9001"
    volumes:
      - minio_data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 20s
      retries: 3

  # MinIO bucket initialization
  minio-init:
    image: minio/mc:latest
    depends_on:
      - minio
    entrypoint: >
      /bin/sh -c "
      until /usr/bin/mc alias set myminio http://minio:9000 minioadmin minioadmin; do
        echo 'Waiting for MinIO...';
        sleep 1;
      done;
      /usr/bin/mc mb myminio/uploads --ignore-existing;
      /usr/bin/mc anonymous set download myminio/uploads;
      echo 'MinIO initialized';
      "

  # Worker for async tasks
  worker:
    build: .
    command: arq app.worker.WorkerSettings
    environment:
      - STORAGE_PROVIDER=s3
      - S3_ENDPOINT=http://minio:9000
      - S3_ACCESS_KEY=minioadmin
      - S3_SECRET_KEY=minioadmin
      - S3_BUCKET=uploads
      - REDIS_URL=redis://redis:6379
      - DATABASE_URL=postgresql://user:password@postgres:5432/filestore
    depends_on:
      - redis
      - postgres
      - minio

volumes:
  redis_data:
  postgres_data:
  minio_data:
```

### MinIO Configuration Details

**Why MinIO for Testing?**

- **S3-Compatible**: Fully compatible with AWS S3 API (boto3 works without changes)
- **Self-Hosted**: No AWS credentials needed, runs entirely locally
- **Fast**: In-memory or local disk storage, ideal for integration tests
- **Console UI**: Web interface at http://localhost:9001 for manual inspection

**MinIO Features Used**:

1. **Standard S3 Operations**: PutObject, GetObject, DeleteObject, HeadObject
2. **Multipart Uploads**: CreateMultipartUpload, UploadPart, CompleteMultipartUpload, AbortMultipartUpload
3. **Presigned URLs**: Generate temporary upload/download URLs (same API as AWS)
4. **Bucket Policies**: Public download for variants, authenticated upload

**MinIO Console Access**:

- **URL**: http://localhost:9001
- **Username**: minioadmin
- **Password**: minioadmin
- **Features**: Browse buckets, view objects, manage policies, inspect multipart uploads

### Testing Workflow

**1. Start All Services**:

```bash
docker-compose up -d
```

**2. Verify Services Are Running**:

```bash
# Check all containers
docker-compose ps

# Check MinIO health
curl http://localhost:9000/minio/health/live

# Check FastAPI health
curl http://localhost:8000/health

# Check Redis
docker-compose exec redis redis-cli ping
```

**3. Run Integration Tests**:

```bash
# Run with pytest
docker-compose exec fastapi pytest tests/integration/

# Run specific test suites
docker-compose exec fastapi pytest tests/integration/test_deduplication.py
docker-compose exec fastapi pytest tests/integration/test_multipart_upload.py
docker-compose exec fastapi pytest tests/integration/test_variant_generation.py
```

**4. Manual Testing via MinIO Console**:

- Upload files via API: `POST http://localhost:8000/upload`
- View stored objects: http://localhost:9001 → Browse → uploads bucket
- Check variants: Should see `originals/`, `webp/`, `thumbnails/` prefixes
- Inspect multipart sessions: Check for orphaned uploads in console

**5. Test Deduplication**:

```bash
# Upload same file twice
curl -X POST http://localhost:8000/upload \
  -F "file=@test_image.jpg" \
  -H "Authorization: Bearer $TOKEN"

# Second upload should return immediately (dedup hit)
curl -X POST http://localhost:8000/upload \
  -F "file=@test_image.jpg" \
  -H "Authorization: Bearer $TOKEN"

# Verify only one object in MinIO (check console)
```

**6. Test Worker Processing**:

```bash
# Monitor worker logs
docker-compose logs -f worker

# Upload file and watch variant generation
curl -X POST http://localhost:8000/upload \
  -F "file=@test_image.jpg" \
  -H "Authorization: Bearer $TOKEN"

# Check MinIO for WebP and thumbnail variants (should appear within 5s)
```

**7. Test Graceful Degradation**:

```bash
# Stop Redis to test degradation mode
docker-compose stop redis

# Upload should still work (without dedup/rate limiting)
curl -X POST http://localhost:8000/upload \
  -F "file=@test_image.jpg" \
  -H "Authorization: Bearer $TOKEN"

# Check logs for degradation warnings
docker-compose logs fastapi | grep -i "degraded"

# Restart Redis
docker-compose start redis
```

**8. Cleanup**:

```bash
# Stop services but keep data
docker-compose down

# Stop and remove all data
docker-compose down -v
```

### Environment Switching

**Switch to AWS S3 for Production Testing**:

```yaml
# docker-compose.override.yml
services:
  fastapi:
    environment:
      - STORAGE_PROVIDER=s3
      - S3_ENDPOINT=https://s3.us-east-1.amazonaws.com
      - S3_ACCESS_KEY=${AWS_ACCESS_KEY_ID}
      - S3_SECRET_KEY=${AWS_SECRET_ACCESS_KEY}
      - S3_BUCKET=prod-uploads-bucket
      - S3_REGION=us-east-1
```

**Switch to GCS**:

```yaml
services:
  fastapi:
    environment:
      - STORAGE_PROVIDER=gcs
      - GCS_BUCKET=prod-uploads-bucket
      - GOOGLE_APPLICATION_CREDENTIALS=/app/gcs-key.json
    volumes:
      - ./gcs-key.json:/app/gcs-key.json:ro
```

**Switch to Cloudflare R2**:

```yaml
services:
  fastapi:
    environment:
      - STORAGE_PROVIDER=s3
      - S3_ENDPOINT=https://[account-id].r2.cloudflarestorage.com
      - S3_ACCESS_KEY=${R2_ACCESS_KEY}
      - S3_SECRET_KEY=${R2_SECRET_KEY}
      - S3_BUCKET=prod-uploads
```

### CI/CD Integration

**GitHub Actions Example**:

```yaml
name: Integration Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Start services
        run: docker-compose up -d

      - name: Wait for services
        run: |
          timeout 60 sh -c 'until curl -f http://localhost:8000/health; do sleep 1; done'
          timeout 60 sh -c 'until curl -f http://localhost:9000/minio/health/live; do sleep 1; done'

      - name: Run tests
        run: docker-compose exec -T fastapi pytest tests/integration/ -v

      - name: Check dedup metrics
        run: |
          docker-compose logs fastapi | grep -i "dedup_hit_rate"

      - name: Cleanup
        if: always()
        run: docker-compose down -v
```

### Performance Testing with MinIO

**Load Testing Configuration**:

```bash
# Install locust for load testing
pip install locust

# Run load test against local MinIO setup
locust -f tests/load/upload_test.py --host=http://localhost:8000
```

**Monitor MinIO Performance**:

```bash
# MinIO metrics endpoint (Prometheus format)
curl http://localhost:9000/minio/v2/metrics/cluster

# Key metrics to watch:
# - minio_s3_requests_total
# - minio_s3_requests_errors_total
# - minio_s3_time_ttfb_seconds_bucket
```

---

## Key Workflows

### Upload Flow (Small Files ≤2MB)

1. Client: `POST /upload` with file bytes
2. Server: Validate size, type, auth
3. Server: Hash content (SHA-256)
4. Server: Check Redis dedup cache → if hit, return existing metadata
5. Server: Acquire Redis lock (`SET NX`) on hash
6. Server: Check DB for hash → if exists, update cache, return metadata
7. Server: Upload to storage provider → get storage key
8. Server: Save metadata to DB, write hash→key to Redis cache
9. Server: Enqueue variant generation job (async)
10. Server: Return file metadata to client
11. Worker: Generate WebP + thumbnail, upload variants to storage
12. Worker: Update metadata with variant URLs

### Upload Flow (Large Files >2MB)

1. Client: `POST /upload/initiate` with metadata
2. Server: Validate, rate limit, auth
3. Server: Create multipart session in Redis (TTL=expiry time)
4. Server: Generate presigned URLs for each part
5. Client: Upload parts directly to storage provider
6. Client: `POST /upload/finalize` with part ETags
7. Server: Verify all parts uploaded, complete multipart upload
8. Server: Hash complete file, run dedup check (may be duplicate)
9. Server: Save metadata, enqueue variant generation
10. Worker: Same as small file flow

### Deduplication Race Prevention

```
Request A                          Request B
    |                                  |
    ├─ hash file                       ├─ hash file
    ├─ check Redis → MISS              ├─ check Redis → MISS
    ├─ SET lock:hash:abc NX → OK       ├─ SET lock:hash:abc NX → FAIL (locked)
    ├─ check DB → MISS                 ├─ wait 50ms, retry
    ├─ upload to storage               ├─ check Redis → HIT (A wrote it)
    ├─ write to DB                     ├─ return existing metadata
    ├─ write to Redis cache            |
    ├─ delete lock                     |
    ├─ return metadata                 |
```

---

## Critical Design Decisions

### 1. Deduplication Strategy: Dual-Write (Redis + DB)

**Decision**: Write hash→key mapping to both Redis (cache) and DB (source of truth) in parallel during upload.

**Rationale**: Prevents cache stampede — if Redis entry expires under load, fallback to DB doesn't cause duplicate uploads.

**Trade-off**: Slightly higher write latency (2 writes) vs. stronger consistency and cache miss protection.

### 2. Rate Limiting: Token Bucket with Sliding Window

**Algorithm**: Token bucket (burst capacity) + sliding window (accurate rate tracking)

**Implementation**: Redis sorted sets for sliding window, refill rate = avg requests/sec, bucket capacity = burst size

**Rationale**: Balances burst tolerance (legitimate spikes) with accurate rate enforcement (Cloudflare approach).

### 3. Worker Choice: arq over Celery

**Decision**: arq for MVP, Celery for complex scenarios

**Rationale**:

- **arq**: Redis-native, async/await compatible, simpler for single-queue workflows
- **Celery**: Multi-queue, priority routing, mature ecosystem — use if need advanced scheduling

**MVP uses arq** — variant generation is simple, no complex routing needed.

### 4. Graceful Degradation: Allow Uploads Without Redis

**Decision**: If Redis is down, continue accepting uploads without dedup/rate-limiting (log bypass, alert on threshold).

**Rationale**: Availability over consistency — losing dedup for 5 minutes is acceptable, losing all uploads is not.

**Monitoring**: Alert if degradation lasts >5 minutes, track bypass rate in metrics.

### 5. Presigned URL TTL: 15 Minutes

**Security**: Short TTL limits exposure if URL is leaked (client logs, debugging tools)

**Trade-off**: 15 min balances security (short exposure window) vs. usability (enough time for slow uploads).

**Mitigation**: Validate client identity before issuing presign request, use idempotency tokens for finalize.

### 6. Dependency Injection: Configuration-Driven Services

**Decision**: Use constructor-based dependency injection with factory pattern for all external dependencies (storage, Redis, DB, worker queue).

**Implementation**:

```python
# Factory creates providers based on config
def get_storage_provider(config: dict) -> StorageProvider:
    if config["provider"] == "s3":
        return S3Provider(config["bucket"], config["region"])
    elif config["provider"] == "gcs":
        return GCSProvider(config["bucket"])
    # ... other providers

# Service layer receives injected dependencies
class UploadService:
    def __init__(
        self,
        storage: StorageProvider,
        redis: Redis,
        db: Database,
        worker: WorkerQueue
    ):
        self.storage = storage
        self.redis = redis
        self.db = db
        self.worker = worker

# FastAPI dependency injection
def get_upload_service() -> UploadService:
    return UploadService(
        storage=get_storage_provider(config),
        redis=get_redis_client(config),
        db=get_database(config),
        worker=get_worker_queue(config)
    )
```

**Rationale**:

- **Testability**: Mock dependencies without modifying service code
- **Flexibility**: Swap implementations (dev uses MinIO, prod uses S3) via config only
- **Clarity**: Explicit dependencies visible in constructor, no hidden globals

**Trade-off**: Slightly more boilerplate vs. hardcoded imports, but vastly improves maintainability and testing.

---

## Security Considerations

### Threats Identified

1. **Presigned URL leakage**: Attacker intercepts URL, writes to storage key
   - _Mitigation_: 15-min TTL, validate client before issuing URL, monitor for anomalous writes
2. **Pillow CVE exploitation**: Malicious image triggers vulnerability during variant generation
   - _Mitigation_: Keep Pillow updated, run workers in isolated containers, resource limits
3. **JWT expiry during long uploads**: 10GB upload takes 15 min, JWT expires after 10 min
   - _Mitigation_: Presigned URLs use independent auth (not JWT), or implement refresh tokens
4. **Rate limit evasion**: Multiple accounts from same user
   - _Mitigation_: IP-based rate limiting as backstop (careful with NAT/proxies)
5. **Storage key collision**: Hash truncation or implementation bug causes different files → same key
   - _Mitigation_: Use full SHA-256 (not truncated), validate write with HEAD request

### Defense in Depth

- Input validation (file type, size, mime type)
- Authentication (JWT) + authorization (per-file ACLs or RBAC)
- Rate limiting (per-user + per-IP)
- Resource limits (worker memory, request timeout)
- Audit logging (who uploaded what, when)
- Optional: Malware scanning (Phase 2 extension)

---

## Operational Concerns

### Capacity Planning

| Component   | Bottleneck Risk             | Scaling Strategy                       |
| ----------- | --------------------------- | -------------------------------------- |
| FastAPI     | Low (stateless)             | Horizontal (add replicas)              |
| Redis       | Medium (single-threaded)    | Redis Cluster or read replicas         |
| Database    | Medium (metadata writes)    | Read replicas, connection pooling      |
| Worker      | High (CPU-bound image ops)  | Horizontal (autoscale on queue depth)  |
| Storage API | High (provider rate limits) | Per-prefix sharding, backoff, fallback |

### Disaster Recovery

- **Redis failure**: Graceful degradation (allow uploads without dedup), RDB+AOF persistence + replica for HA
- **DB failure**: Return 503, no degradation (metadata loss is unacceptable)
- **Storage provider failure**: Circuit breaker, return 503 or fallback to alternate provider (if multi-cloud)
- **Worker pod crash**: Job retry (max 3 attempts), dead-letter queue for persistent failures

### Monitoring & Alerting

**Key Metrics**:

- Dedup hit rate (target: >20%, lower = cost concern)
- Variant generation latency (p95, p99)
- Upload success rate
- Worker queue depth (alert if >1000 backlog)
- Degradation bypass events (Redis down)
- Storage provider API error rate

**Alerts**:

- Degraded mode active >5 minutes (Redis/rate limiter down)
- Worker queue depth >5000 (generation bottleneck)
- Dedup hit rate drops below 10% (cache eviction issue?)
- Storage provider error rate >5% (throttling, outage)

### Multipart Orphan Cleanup

**Problem**: Abandoned uploads leave parts in storage, no automatic cleanup

**Solution**: Scheduled job (daily) sweeps Redis for sessions >24h old, calls AbortMultipartUpload API

**Trade-off**: 24h TTL balances "legitimate slow uploads" vs. "storage waste from orphans"

---

## Cost Model

### Storage Costs (Example: AWS S3)

**Assumptions**: 100k uploads/month, 50% dedup hit rate, 5MB avg file size

| Item                    | Calculation                             | Monthly Cost |
| ----------------------- | --------------------------------------- | ------------ |
| Original files          | 50k × 5MB × $0.023/GB                   | $5.75        |
| Variants (WebP + thumb) | 50k × (2MB + 0.5MB) × $0.023/GB         | $2.88        |
| **Total storage**       |                                         | **$8.63**    |
| PUT requests            | 150k (originals + variants) × $0.005/1k | $0.75        |
| GET requests (1M/mo)    | 1M × $0.0004/1k                         | $0.40        |
| **Total S3**            |                                         | **$9.78/mo** |

**Without dedup**: 100k uploads × 5MB = $11.50/mo → **17% savings**

### Infrastructure Costs

- Redis (managed, 4GB): ~$30/mo
- RDS PostgreSQL (db.t3.medium): ~$60/mo
- Kubernetes nodes (worker pods): ~$100/mo
- Log aggregation (basic): ~$10/mo

**Total infrastructure**: ~$200/mo (scales with traffic)

---

## Success Metrics

### Technical KPIs

- **Upload latency**: p95 <500ms (small files), p95 <2s (presigned URL issuance)
- **Dedup hit rate**: >20% (project-dependent, higher = more savings)
- **Variant generation**: p95 <5s from upload complete → variants available
- **Availability**: 99.9% uptime (allows 43 min downtime/month)
- **Error rate**: <0.1% (failed uploads / total attempts)

### Learning Goals

- ✅ Master Redis coordination primitives (locks, rate limiting, TTL-based state)
- ✅ Understand storage provider APIs (presigned URLs, multipart mechanics)
- ✅ Design async worker patterns (arq vs. Celery trade-offs)
- ✅ Implement dependency injection patterns (testable, flexible service architecture)
- ✅ Implement production observability (structured logging, metrics, tracing)
- ✅ Handle distributed systems challenges (race conditions, graceful degradation, circuit breakers)

---

## Open Questions & Risks

### Questions Requiring Decisions

1. **Sync vs. async malware scanning**: Block upload until scan completes (safer) or scan async (faster, risk window)?
2. **Variant failure policy**: After 3 retries, serve original forever or retry on next access?
3. **Multi-region strategy**: Regional storage buckets (lower latency) or single multi-region bucket (simpler)?
4. **Worker autoscaling trigger**: Queue depth threshold (e.g., >100 jobs) or latency-based (p99 >10s)?

### Known Risks

| Risk                           | Likelihood | Impact | Mitigation                                                |
| ------------------------------ | ---------- | ------ | --------------------------------------------------------- |
| Redis single point of failure  | Medium     | High   | Redis Cluster + persistence, graceful degradation         |
| Worker retry explosion         | Medium     | Medium | Dead-letter queue, alerting, max 3 retries                |
| Storage provider throttling    | Low        | High   | Exponential backoff, circuit breaker, per-prefix sharding |
| JWT expiry during long uploads | Low        | Medium | Use independent auth for presigned URLs                   |
| Dedup cache stampede           | Low        | Medium | Dual-write Redis+DB, request coalescing                   |

---

## Implementation Roadmap

### Phase 1: Core Service (4-6 weeks)

**Week 1-2**: FastAPI scaffold with dependency injection setup, storage adapter interface, S3 implementation with factory pattern
**Week 3**: Redis coordination (locks, rate limiting), deduplication logic
**Week 4**: Multipart upload (session tracking, presigned URLs)
**Week 5**: Worker setup (arq), variant generation (Pillow)
**Week 6**: Observability (structlog with embedded metrics, request ID tracking)

### Phase 2: Production Hardening (2-3 weeks)

**Week 7**: Graceful degradation (Redis fallback), circuit breakers
**Week 8**: Integration tests (race conditions, failure modes)
**Week 9**: Load testing, capacity planning, performance tuning

### Phase 3: Extensions (Optional, Future)

- CDN integration (CloudFront with signed URLs)
- Malware scanning (ClamAV or AWS GuardDuty)
- Video transcoding (HLS/DASH segmentation)
- Content moderation (NSFW detection)

---

## Related Projects & References

### Internal Knowledge Base

- [Content Deduplication Patterns](../knowledge/02-Software%20Engineering/Architecture/content-deduplication-patterns.md)
- [Storage Adapter Pattern](../knowledge/02-Software%20Engineering/Architecture/storage-adapter-pattern.md)
- [Cache Stampede Prevention](../knowledge/02-Software%20Engineering/Performance/cache-stampede-prevention.md)
- [Graceful Degradation Patterns](../knowledge/02-Software%20Engineering/System%20Design/graceful-degradation-patterns.md)
- [Rate Limiting Patterns](../knowledge/02-Software%20Engineering/Architecture/rate-limiting-patterns.md)

### External References

- [FastAPI Official Documentation](https://fastapi.tiangolo.com/)
- [arq Documentation](https://arq-docs.helpmanual.io/)
- [AWS S3 Presigned URLs](https://docs.aws.amazon.com/AmazonS3/latest/userguide/PresignedUrlUploadObject.html)
- [Redis Rate Limiting](https://redis.io/glossary/rate-limiting/)
- [Pillow Documentation](https://pillow.readthedocs.io/)

### Comparable Systems

- **AWS S3 + Lambda**: Managed, event-driven, cold start latency
- **Cloudinary**: Full-featured SaaS, expensive at scale
- **MinIO**: Self-hosted S3-compatible, operational burden
- **Existing TS system**: Proven hybrid strategy, single backend implementation

---

## Conclusion

This project demonstrates production-grade distributed systems engineering: content-based deduplication with race prevention, async worker orchestration, storage abstraction for vendor independence, and operational patterns (graceful degradation, circuit breakers, observability). The hybrid upload strategy balances simplicity (mediated for small files) with efficiency (presigned URLs for large files), while variant generation optimizes delivery without blocking uploads.

**Key differentiator**: Not just a CRUD file uploader — solves real concurrency challenges, implements proper observability, and designs for failure scenarios. Portfolio-ready system design that showcases backend engineering maturity.
