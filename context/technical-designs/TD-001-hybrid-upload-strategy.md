# TD-001: Hybrid Upload Strategy

Status: Not Started
Owner: TBD
Created: 2026-08-11
Last Updated: 2026-08-11

Feature Spec: [FEAT-001 - Hybrid Upload Strategy](../features/FEAT-001-hybrid-upload-strategy.md)

---

# 1. Overview

## Summary

Implement two upload paths with automatic routing: small files (≤2MB) flow through FastAPI backend to storage provider, large files (>2MB) use presigned URLs for direct client-to-storage upload. Unified response format and validation layer ensure consistent API experience.

## Goals

- Single entry point for upload initiation with automatic routing
- Minimize backend bandwidth for large files
- Maintain type safety with Pydantic models
- Support pluggable storage backends via adapter pattern
- Provide comprehensive validation before storage operations

## Non-Goals

- Streaming/chunking for small files (use presigned path instead)
- Client-side retry logic (client responsibility)
- Progress callbacks during upload (handled by client)

---

# 2. Architecture

## High-Level Design

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │
       │ File ≤2MB?
       ├─────────────┬──────────────────┐
       │ YES         │ NO               │
       ▼             ▼                  │
POST /upload   POST /initiate          │
       │             │                  │
       ▼             ▼                  │
┌─────────────────────────────┐        │
│   FastAPI Upload Service    │        │
│  - Validate (size, type)    │        │
│  - Inject dependencies      │        │
└──────┬──────────────┬───────┘        │
       │              │                │
       │              │ Generate       │
       │              │ presigned URL  │
       │              ▼                │
       │      ┌──────────────┐         │
       │      │Storage       │◄────────┘
       │      │Provider      │   Client uploads
       │      │(S3/GCS/R2)   │   directly via
       │      └──────────────┘   presigned URL
       │              │
       │              │
       ▼              ▼
POST /finalize (verify + commit)
       │
       ▼
┌──────────────┐
│  PostgreSQL  │
│ (metadata)   │
└──────────────┘
```

## Technology Choices

- **FastAPI**: Async endpoints for non-blocking I/O during storage operations
- **Pydantic**: Type-safe request/response models with built-in validation
- **boto3/google-cloud-storage**: Storage provider SDKs wrapped by adapter pattern
- **SQLAlchemy**: ORM for file metadata persistence
- **dependency-injector**: Service container for storage provider injection

---

# 3. Components

## New Components

### `src/upload/router.py`

**Purpose**: FastAPI router defining `/upload`, `/upload/initiate`, `/upload/finalize` endpoints

### `src/upload/service.py`

**Purpose**: Business logic for upload orchestration (validation, storage coordination, metadata persistence)

### `src/upload/models.py`

**Purpose**: Pydantic request/response models and SQLAlchemy ORM models

### `src/upload/validator.py`

**Purpose**: File validation utilities (size, type, mime type verification)

### `src/storage/provider.py`

**Purpose**: Storage provider abstract interface (already defined in FEAT-003, used here)

## Modified Components

None (new feature)

---

# 4. Data Model

## New Tables

### `files`

```sql
CREATE TABLE files (
    file_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    storage_key VARCHAR(512) NOT NULL,        -- S3 key or GCS object name
    filename VARCHAR(255) NOT NULL,            -- Original client filename
    size BIGINT NOT NULL,                      -- File size in bytes
    mime_type VARCHAR(127) NOT NULL,           -- Content type (image/jpeg, etc.)
    sha256_hash CHAR(64) NULL,                 -- Content hash (populated by FEAT-002)
    upload_strategy VARCHAR(20) NOT NULL,      -- 'mediated' or 'presigned'
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_size_positive CHECK (size > 0),
    CONSTRAINT chk_strategy CHECK (upload_strategy IN ('mediated', 'presigned'))
);

CREATE INDEX idx_files_storage_key ON files(storage_key);
CREATE INDEX idx_files_sha256_hash ON files(sha256_hash) WHERE sha256_hash IS NOT NULL;
CREATE INDEX idx_files_created_at ON files(created_at DESC);
```

### `upload_sessions` (for presigned URL tracking)

```sql
CREATE TABLE upload_sessions (
    upload_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename VARCHAR(255) NOT NULL,
    size BIGINT NOT NULL,
    mime_type VARCHAR(127) NOT NULL,
    presigned_url TEXT NOT NULL,                -- Generated presigned URL
    storage_key VARCHAR(512) NOT NULL,          -- Target storage key
    expires_at TIMESTAMP NOT NULL,              -- Presigned URL expiry
    finalized BOOLEAN NOT NULL DEFAULT FALSE,   -- True after /finalize called
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_session_size_positive CHECK (size > 0)
);

CREATE INDEX idx_upload_sessions_expires_at ON upload_sessions(expires_at)
    WHERE NOT finalized; -- For cleanup job

CREATE INDEX idx_upload_sessions_finalized ON upload_sessions(finalized, created_at);
```

## Schema Changes

None (new tables)

---

# 5. API Design

## New Endpoints

### `POST /upload`

**Description**: Upload small files (≤2MB) via backend-mediated transfer

**Request**:

```http
POST /upload HTTP/1.1
Content-Type: multipart/form-data; boundary=----WebKitFormBoundary
Authorization: Bearer <jwt_token>

------WebKitFormBoundary
Content-Disposition: form-data; name="file"; filename="profile.jpg"
Content-Type: image/jpeg

<binary data>
------WebKitFormBoundary--
```

**Response (200 OK)**:

```json
{
  "file_id": "550e8400-e29b-41d4-a716-446655440000",
  "storage_key": "originals/2026/08/11/550e8400-e29b-41d4-a716-446655440000.jpg",
  "filename": "profile.jpg",
  "size": 1048576,
  "mime_type": "image/jpeg",
  "upload_url": "https://cdn.example.com/originals/2026/08/11/550e8400-e29b-41d4-a716-446655440000.jpg",
  "created_at": "2026-08-11T10:30:00Z"
}
```

**Error Responses**:

```json
// 413 Payload Too Large
{
  "error": "file_too_large",
  "message": "File size (3145728 bytes) exceeds 2MB limit. Use /upload/initiate for large files.",
  "max_size": 2097152,
  "suggested_endpoint": "/upload/initiate"
}

// 400 Bad Request
{
  "error": "invalid_file_type",
  "message": "File type 'application/x-msdownload' is not allowed",
  "allowed_types": ["image/jpeg", "image/png", "image/gif", "video/mp4"]
}

// 400 Bad Request
{
  "error": "mime_mismatch",
  "message": "MIME type 'image/jpeg' does not match file extension '.png'",
  "detected_mime": "image/jpeg",
  "filename": "fake.png"
}
```

### `POST /upload/initiate`

**Description**: Initiate large file upload (>2MB), receive presigned URL

**Request**:

```json
{
  "filename": "vacation_video.mp4",
  "size": 157286400,
  "mime_type": "video/mp4"
}
```

**Response (200 OK)**:

```json
{
  "upload_id": "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d",
  "presigned_url": "https://s3.amazonaws.com/bucket/originals/...<signature>",
  "storage_key": "originals/2026/08/11/a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d.mp4",
  "expires_at": "2026-08-11T10:45:00Z",
  "instructions": "PUT file bytes to presigned_url, then call /upload/finalize with upload_id"
}
```

**Error Responses**:

```json
// 400 Bad Request (file too small)
{
  "error": "file_too_small",
  "message": "File size (1048576 bytes) is ≤2MB. Use /upload endpoint for small files.",
  "suggested_endpoint": "/upload"
}

// 400 Bad Request (invalid type)
{
  "error": "invalid_file_type",
  "message": "File type 'application/zip' is not allowed",
  "allowed_types": ["image/jpeg", "image/png", "video/mp4"]
}

// 429 Too Many Requests
{
  "error": "rate_limit_exceeded",
  "message": "Upload initiation rate limit exceeded. Retry after 60 seconds.",
  "retry_after": 60
}
```

### `POST /upload/finalize`

**Description**: Finalize large file upload after client uploads to presigned URL

**Request**:

```json
{
  "upload_id": "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d",
  "etag": "d41d8cd98f00b204e9800998ecf8427e"
}
```

**Response (200 OK)**:

```json
{
  "file_id": "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d",
  "storage_key": "originals/2026/08/11/a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d.mp4",
  "filename": "vacation_video.mp4",
  "size": 157286400,
  "mime_type": "video/mp4",
  "upload_url": "https://cdn.example.com/originals/2026/08/11/a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d.mp4",
  "created_at": "2026-08-11T10:35:00Z"
}
```

**Error Responses**:

```json
// 404 Not Found
{
  "error": "upload_not_found",
  "message": "Upload session not found or expired",
  "upload_id": "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d"
}

// 400 Bad Request
{
  "error": "upload_incomplete",
  "message": "File not found in storage. Upload may not have completed successfully.",
  "storage_key": "originals/2026/08/11/a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d.mp4"
}

// 410 Gone
{
  "error": "presigned_url_expired",
  "message": "Presigned URL expired. Initiate a new upload.",
  "expired_at": "2026-08-11T10:45:00Z"
}
```

---

# 6. Sequence Flow

## Small File Upload (Mediated)

```
Client                FastAPI Service        Storage Provider     Database
  │                         │                       │                │
  │ POST /upload (file)     │                       │                │
  ├────────────────────────►│                       │                │
  │                         │                       │                │
  │                         │ 1. Validate (size, type, mime)        │
  │                         │                       │                │
  │                         │ 2. Generate storage_key               │
  │                         │    (originals/YYYY/MM/DD/UUID.ext)    │
  │                         │                       │                │
  │                         │ 3. Upload bytes       │                │
  │                         ├──────────────────────►│                │
  │                         │                       │                │
  │                         │ ◄──────────────────── │                │
  │                         │   storage_key         │                │
  │                         │                       │                │
  │                         │ 4. Save metadata                       │
  │                         ├───────────────────────────────────────►│
  │                         │                       │                │
  │                         │ ◄──────────────────────────────────────│
  │                         │   file_id             │                │
  │                         │                       │                │
  │ ◄───────────────────────┤                       │                │
  │   200 OK (metadata)     │                       │                │
```

**Steps**:

1. Validate file size ≤2MB, type allowed, mime matches extension
2. Generate storage key: `originals/{YYYY}/{MM}/{DD}/{UUID}.{ext}`
3. Upload bytes to storage provider via `storage.upload(key, stream)`
4. Save metadata to `files` table with `upload_strategy='mediated'`
5. Return file metadata including `upload_url` for download

## Large File Upload (Presigned URLs)

```
Client                FastAPI Service        Storage Provider     Database
  │                         │                       │                │
  │ POST /initiate          │                       │                │
  ├────────────────────────►│                       │                │
  │  (filename, size, mime) │                       │                │
  │                         │                       │                │
  │                         │ 1. Validate (size >2MB, type allowed) │
  │                         │                       │                │
  │                         │ 2. Generate storage_key               │
  │                         │                       │                │
  │                         │ 3. Generate presigned URL (15min TTL) │
  │                         ├──────────────────────►│                │
  │                         │                       │                │
  │                         │ ◄──────────────────── │                │
  │                         │   presigned_url       │                │
  │                         │                       │                │
  │                         │ 4. Save upload session                 │
  │                         ├───────────────────────────────────────►│
  │                         │                       │                │
  │ ◄───────────────────────┤                       │                │
  │   200 OK                │                       │                │
  │   (upload_id,           │                       │                │
  │    presigned_url)       │                       │                │
  │                         │                       │                │
  │ PUT presigned_url (file bytes)                  │                │
  ├─────────────────────────────────────────────────►│                │
  │                         │                       │                │
  │ ◄───────────────────────────────────────────────┤                │
  │   200 OK (ETag)         │                       │                │
  │                         │                       │                │
  │ POST /finalize          │                       │                │
  ├────────────────────────►│                       │                │
  │  (upload_id, etag)      │                       │                │
  │                         │                       │                │
  │                         │ 5. Verify file exists (HEAD request)  │
  │                         ├──────────────────────►│                │
  │                         │                       │                │
  │                         │ ◄──────────────────── │                │
  │                         │   metadata (size, etag)               │
  │                         │                       │                │
  │                         │ 6. Save file metadata                  │
  │                         ├───────────────────────────────────────►│
  │                         │                       │                │
  │                         │ 7. Mark session finalized              │
  │                         ├───────────────────────────────────────►│
  │                         │                       │                │
  │ ◄───────────────────────┤                       │                │
  │   200 OK (metadata)     │                       │                │
```

**Steps**:

1. Validate size >2MB, type allowed, mime matches extension (check filename)
2. Generate storage key: `originals/{YYYY}/{MM}/{DD}/{UUID}.{ext}`
3. Generate presigned PUT URL with 15-minute TTL via `storage.generate_presigned_url(key, 'PUT', 900)`
4. Save `upload_sessions` record with upload_id, presigned_url, expires_at
5. Client uploads directly to storage using presigned URL, receives ETag
6. On `/finalize`, verify file exists via `storage.head_object(key)`
7. Save `files` table record with `upload_strategy='presigned'`
8. Mark `upload_sessions.finalized=true`
9. Return file metadata

---

# 7. Error Handling

| Scenario                   | Error Code | Response                                                                | Recovery                            |
| -------------------------- | ---------- | ----------------------------------------------------------------------- | ----------------------------------- |
| File >2MB on /upload       | 413        | `{"error": "file_too_large", "suggested_endpoint": "/upload/initiate"}` | Client retries with initiate flow   |
| File ≤2MB on /initiate     | 400        | `{"error": "file_too_small", "suggested_endpoint": "/upload"}`          | Client retries with mediated upload |
| Invalid file type          | 400        | `{"error": "invalid_file_type", "allowed_types": [...]}`                | Client validates type before upload |
| MIME mismatch              | 400        | `{"error": "mime_mismatch"}`                                            | Client corrects filename or type    |
| Storage provider down      | 503        | `{"error": "storage_unavailable", "retry_after": 30}`                   | Exponential backoff, retry          |
| Upload session expired     | 410        | `{"error": "presigned_url_expired"}`                                    | Client re-initiates upload          |
| File not found on finalize | 400        | `{"error": "upload_incomplete"}`                                        | Client re-uploads with new session  |
| Database unavailable       | 503        | `{"error": "service_unavailable"}`                                      | Return 503, no degradation          |

**Error Logging**: All storage and database errors logged with context (file_id, user_id, operation, error_type)

---

# 8. Testing Strategy

## Unit Tests

- [ ] `test_upload_validator_size_limits()` — verify 2MB threshold enforcement
- [ ] `test_upload_validator_file_types()` — allowlist enforcement
- [ ] `test_upload_validator_mime_mismatch()` — detect fake extensions
- [ ] `test_generate_storage_key_uniqueness()` — UUID collision probability
- [ ] `test_presigned_url_ttl()` — verify 15-minute expiry

## Integration Tests (with MinIO)

- [ ] `test_small_file_upload_success()` — end-to-end mediated upload
- [ ] `test_large_file_upload_success()` — initiate → client upload → finalize
- [ ] `test_small_file_rejected_if_too_large()` — /upload returns 413 for 3MB file
- [ ] `test_large_file_rejected_if_too_small()` — /initiate returns 400 for 1MB file
- [ ] `test_presigned_url_expires()` — finalize fails after 15 minutes
- [ ] `test_finalize_without_upload()` — finalize returns 400 if file not in storage
- [ ] `test_concurrent_uploads_same_file()` — verify no race conditions (with FEAT-002)
- [ ] `test_storage_provider_failure_handling()` — graceful error on S3 500

## Performance Tests

- [ ] 100 concurrent small file uploads (measure p95, p99 latency)
- [ ] Presigned URL generation under load (target: <200ms p95)
- [ ] Database connection pool saturation test (verify no deadlocks)

---

# 9. Implementation Phases (PR Mapping)

## Phase 1: PR1 - Upload Foundation

**Technical Scope**:

- Files:
  - `migrations/001_create_files_table.sql`
  - `migrations/002_create_upload_sessions_table.sql`
  - `src/upload/models.py` (Pydantic + SQLAlchemy models)
  - `src/upload/validator.py`
  - `src/config.py` (add upload config section)
  - `tests/unit/test_validator.py`
- Tests: Unit tests for validator, config loading
- Migration: Run locally against PostgreSQL in Docker

## Phase 2: PR2 - Small File Upload

**Technical Scope**:

- Files:
  - `src/upload/router.py` (POST /upload endpoint)
  - `src/upload/service.py` (upload_small_file method)
  - `tests/integration/test_small_upload.py`
  - `tests/integration/conftest.py` (MinIO fixtures)
- Tests: Integration tests with MinIO, error case coverage
- Depends on: Phase 1 merged, FEAT-003 storage interface available

## Phase 3: PR3 - Large File Upload

**Technical Scope**:

- Files:
  - `src/upload/router.py` (add /initiate and /finalize endpoints)
  - `src/upload/service.py` (add initiate_large_upload, finalize_large_upload methods)
  - `tests/integration/test_large_upload.py`
- Tests: Presigned URL workflow, expiry handling, verification logic
- Depends on: Phase 2 merged

---

# 10. Security Considerations

### Authentication & Authorization

- All endpoints require valid JWT token in `Authorization: Bearer <token>` header
- Rate limiting applied per user (via JWT `sub` claim) — see FEAT-006
- Upload sessions tied to user_id (prevent finalization by different user)

### Input Validation

- File size validated before accepting upload (prevent memory exhaustion)
- MIME type validated against allowlist (prevent executable uploads)
- MIME type vs extension mismatch detection (prevent disguised files)
- Filename sanitization (strip path traversal characters like `../`)

### Presigned URL Security

- 15-minute TTL limits exposure window
- URLs use storage provider's signed URL mechanism (AWS Signature V4, GCS signed URLs)
- Upload_id is UUID v4 (unguessable, prevents enumeration)
- Verify file exists before finalizing (prevent phantom metadata)

### Storage Key Generation

- Use UUIDs to prevent enumeration (`originals/{YYYY}/{MM}/{DD}/{UUID}.{ext}`)
- Date prefixing enables lifecycle policies (e.g., archive old files)
- Extension preserved for browser compatibility (correct Content-Type header)

---

# 11. Performance Considerations

### Backend Bandwidth Optimization

- Small files (≤2MB) routed through backend — acceptable bandwidth usage
- Large files (>2MB) bypass backend — saves bandwidth, reduces latency
- Target: <10% of total upload traffic through backend

### Database Connection Pooling

- SQLAlchemy pool size: 20 connections (FastAPI async workers + worker processes)
- Overflow: 10 (short-term burst capacity)
- Timeout: 30s (fail fast if pool exhausted)

### Storage Provider API Limits

- AWS S3: 3,500 PUT/s per prefix — use date-based prefixes for distribution
- Presigned URL generation: Local signing (no API call), ~1ms latency
- HEAD requests for verification: <100ms p95 (S3), cached per upload_id

### Redis Caching (Future)

- Cache upload session lookups (upload_id → session data) with 15-minute TTL
- Reduce database load for finalize calls
- Implemented in FEAT-002 (deduplication) infrastructure

---

# 12. Deployment Notes

### Configuration

**Environment Variables**:

```bash
# Upload limits
MAX_SMALL_FILE_SIZE=2097152           # 2MB in bytes
PRESIGNED_URL_TTL=900                 # 15 minutes in seconds
ALLOWED_FILE_TYPES=image/jpeg,image/png,image/gif,video/mp4

# Storage provider (injected by FEAT-003)
STORAGE_PROVIDER=s3
S3_BUCKET=prod-uploads
S3_REGION=us-east-1
```

### Database Migrations

1. Run `migrations/001_create_files_table.sql`
2. Run `migrations/002_create_upload_sessions_table.sql`
3. Verify indexes created: `SELECT * FROM pg_indexes WHERE tablename IN ('files', 'upload_sessions');`

### Rollback Plan

- Migrations are additive (no data modification)
- Rollback: Drop new tables if no uploads occurred
- If uploads occurred: Keep tables, disable endpoints in load balancer

### Monitoring

- Track upload_strategy distribution (expect 80%+ presigned for typical workload)
- Alert if mediated uploads >20% of total (indicates small file bias or misconfiguration)
- Monitor presigned URL expiry rate (high rate = client upload failures)

---

# 13. Open Questions

- [ ] Should we support custom presigned URL TTL via API parameter (e.g., `"ttl": 3600`)?
- [ ] Do we need to store ETag from finalize in files table for integrity verification?
- [ ] Should upload_sessions have a cleanup job (delete finalized sessions >24h old)?
- [ ] How do we handle client upload failures (incomplete uploads) — automatic retry or manual re-initiate?
