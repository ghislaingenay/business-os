# TD-005: Multipart Upload Support

Status: Doing
Owner: TBD
Created: 2026-08-11
Last Updated: 2026-08-16

Feature Spec: [FEAT-005 - Multipart Upload Support](../features/FEAT-005-multipart-upload-support.md)

---

# 1. Overview

## Summary

Multipart upload orchestration for files >100MB using storage provider's native multipart APIs (S3 CreateMultipartUpload, UploadPart, CompleteMultipartUpload), with session tracking in PostgreSQL and automatic cleanup of abandoned uploads.

## Goals

- Enable resilient uploads for large files (>100MB)
- Part-level retry without full re-upload
- Progress tracking and pause/resume support
- Automatic cleanup (abort orphaned multipart sessions)

## Non-Goals

- Adaptive chunk sizing (fixed 10MB)
- Server-driven resume (client tracks progress)

---

# 2. Architecture

```
Client                    FastAPI Service          Storage Provider
  │                            │                          │
  │ POST /initiate (multipart) │                          │
  ├───────────────────────────►│                          │
  │                            │ CreateMultipartUpload    │
  │                            ├─────────────────────────►│
  │                            │ ◄─────────────────────────│
  │                            │   upload_id (S3)         │
  │                            │                          │
  │                            │ Generate presigned URLs  │
  │                            │ (one per part)           │
  │                            │                          │
  │ ◄──────────────────────────┤                          │
  │   {upload_id, part_urls[]} │                          │
  │                            │                          │
  │ PUT part_urls[0] (chunk 1) │                          │
  ├────────────────────────────────────────────────────────►│
  │                            │                          │
  │ PUT part_urls[1] (chunk 2) │                          │
  ├────────────────────────────────────────────────────────►│
  │   ...                      │                          │
  │                            │                          │
  │ POST /finalize             │                          │
  ├───────────────────────────►│                          │
  │   (upload_id, parts[])     │                          │
  │                            │ CompleteMultipartUpload  │
  │                            ├─────────────────────────►│
  │                            │ ◄─────────────────────────│
  │                            │   storage_key            │
  │ ◄──────────────────────────┤                          │
  │   file metadata            │                          │
```

---

# 3. Data Model

```sql
CREATE TABLE multipart_sessions (
    upload_id UUID PRIMARY KEY,
    storage_upload_id VARCHAR(255) NOT NULL,  -- Provider's multipart upload ID
    filename VARCHAR(255) NOT NULL,
    size BIGINT NOT NULL,
    mime_type VARCHAR(127) NOT NULL,
    part_size BIGINT NOT NULL,                -- 10MB (10485760 bytes)
    total_parts INT NOT NULL,
    storage_key VARCHAR(512) NOT NULL,
    finalized BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,            -- created_at + 24 hours
    CONSTRAINT chk_multipart_size CHECK (size > 0),
    CONSTRAINT chk_multipart_parts CHECK (total_parts > 0)
);

CREATE INDEX idx_multipart_sessions_expires
ON multipart_sessions(expires_at) WHERE NOT finalized;
```

---

# 4. API Design

### `POST /upload/initiate` (Multipart Mode)

**Request**:

```json
{
  "filename": "large_video.mp4",
  "size": 524288000,
  "mime_type": "video/mp4",
  "multipart": true
}
```

**Response**:

```json
{
  "upload_id": "a1b2c3d4...",
  "part_size": 10485760,
  "total_parts": 50,
  "storage_key": "originals/2026/08/11/a1b2c3d4.mp4",
  "part_upload_urls": [
    "https://s3.../part1?signature=...",
    "https://s3.../part2?signature=...",
    ...
  ],
  "expires_at": "2026-08-12T10:30:00Z"
}
```

### `GET /upload/{upload_id}/status`

**Response**:

```json
{
  "upload_id": "a1b2c3d4...",
  "storage_key": "originals/2026/08/11/a1b2c3d4.mp4",
  "total_parts": 50,
  "completed_parts": [1, 2, 3, 5, 7],
  "missing_parts": [4, 6, 8, 9, ...],
  "progress_percentage": 10.0,
  "bytes_uploaded": 52428800
}
```

### `POST /upload/{upload_id}/retry-part`

**Request**:

```json
{
  "part_number": 5
}
```

**Response**:

```json
{
  "part_number": 5,
  "presigned_url": "https://s3.../part5?signature=...",
  "expires_at": "2026-08-11T10:45:00Z"
}
```

### `POST /upload/finalize` (Multipart Mode)

**Request**:

```json
{
  "upload_id": "a1b2c3d4...",
  "parts": [
    {"part_number": 1, "etag": "abc123..."},
    {"part_number": 2, "etag": "def456..."},
    ...
  ]
}
```

**Response**: Same as single-part upload (file metadata)

---

# 5. Implementation

**Storage Provider Interface Extension**:

```python
class StorageProvider(ABC):
    @abstractmethod
    async def create_multipart_upload(self, key: str) -> str:
        """Returns provider's upload_id"""
        pass

    @abstractmethod
    async def generate_part_upload_url(
        self, key: str, upload_id: str, part_number: int, ttl: int
    ) -> str:
        pass

    @abstractmethod
    async def list_parts(self, key: str, upload_id: str) -> List[Dict]:
        """Returns [{part_number, etag, size}]"""
        pass

    @abstractmethod
    async def complete_multipart_upload(self, key: str, upload_id: str, parts: List[Dict]) -> str:
        """Returns final storage_key"""
        pass

    @abstractmethod
    async def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        pass
```

**Cleanup Job** (arq task):

```python
async def cleanup_abandoned_multipart_sessions(ctx):
    sessions = await db.query(
        "SELECT upload_id, storage_key, storage_upload_id "
        "FROM multipart_sessions "
        "WHERE expires_at < NOW() AND NOT finalized"
    )

    for session in sessions:
        await storage.abort_multipart_upload(session["storage_key"], session["storage_upload_id"])
        await db.execute("DELETE FROM multipart_sessions WHERE upload_id = ?", session["upload_id"])

    logger.info(f"Cleaned up {len(sessions)} abandoned multipart sessions")
```

---

# 6. Testing Strategy

- [ ] Unit tests: Part number validation, session expiry logic
- [ ] Integration tests: End-to-end multipart workflow (initiate → upload parts → finalize)
- [ ] Error tests: Incomplete parts, expired session, abort handling
- [ ] Cleanup tests: Verify abandoned sessions aborted after 24 hours

---

# 7. Deployment Notes

**Cleanup Job Schedule** (cron):

```python
class WorkerSettings:
    cron_jobs = [
        cron(cleanup_abandoned_multipart_sessions, hour=2)  # Run daily at 2 AM
    ]
```

**Configuration**:

```bash
MULTIPART_PART_SIZE=10485760          # 10MB
MULTIPART_SESSION_TTL=86400           # 24 hours
MULTIPART_PRESIGNED_URL_TTL=900       # 15 minutes per part
```
