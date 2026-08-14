# FEAT-002: Hybrid Upload Strategy

Status: Done
Owner: TBD
Created: 2026-08-11
Last Updated: 2026-08-14 (Phase 3 complete, all phases done)

Technical Design: [TD-002 - Hybrid Upload Strategy](../technical-designs/TD-002-hybrid-upload-strategy.md)

---

## PR Progress

- [x] Phase 1: Upload Foundation (branch: feature/hybrid-upload-a)
- [x] Phase 2: Small File Upload - Mediated (branch: feature/hybrid-upload-b)
- [x] Phase 3: Large File Upload - Presigned URLs (branch: feature/hybrid-upload-c)

---

# 1. Overview

## Summary

Implement a dual-mode file upload strategy that automatically selects the optimal upload path based on file size: backend-mediated uploads for small files (≤xMB) and presigned URL uploads for large files (>xMB) to balance simplicity, bandwidth efficiency, and scalability. The size threshold (xMB) is configurable and defaults to 2MB (env variable `MAX_SMALL_FILE_SIZE`, in bytes — see TD-002 §12 Configuration).

## Problem

A single upload strategy cannot efficiently handle both small and large files:

- **Backend-mediated only**: Backend becomes a bandwidth bottleneck for large files (video, high-res images), increasing latency and server costs
- **Presigned URLs only**: Unnecessary complexity for small files, poor UX (extra round-trip), and higher client implementation burden
- **No strategy**: Inefficient resource utilization and poor user experience

## Goals

- Accept files ≤xMB through direct `POST /upload` (backend-mediated)
- Support files >xMB through `POST /upload/initiate` → presigned URL → `POST /upload/finalize` flow
- Automatically route uploads based on file size without client pre-configuration
- Maintain consistent API response format regardless of upload path
- Validate file metadata (size, type, mime) before accepting uploads

## Non-Goals

- Resume capability for interrupted uploads (handled by FEAT-005 multipart)
- Streaming uploads (use presigned URL path instead)
- Client-side chunking for small files
- Automatic retry logic (client responsibility)

---

# 2. Users

## Primary Users

- **Frontend developers**: Implement upload forms in web/mobile apps
- **API consumers**: Third-party integrations uploading user content

## Stakeholders

- **Backend engineers**: Maintain upload logic, monitor bandwidth usage
- **DevOps**: Monitor server resource utilization, optimize costs
- **End users**: Experience fast, reliable file uploads

---

# 3. User Stories

### Story 1: Upload Profile Picture

As a **web application user**
I want to **upload a profile picture (typically <500KB)**
So that **I can personalize my account quickly**

**Acceptance**: Upload completes in <1s, single API call

### Story 2: Upload High-Resolution Photo

As a **mobile app user**
I want to **upload a 15MB DSLR photo**
So that **I can share full-quality images without waiting for backend processing**

**Acceptance**: Receive presigned URL within 200ms, upload directly to storage, finalize in <500ms

### Story 3: Upload Video File

As a **content creator**
I want to **upload a 500MB video file**
So that **I can publish video content without overwhelming the API server**

**Acceptance**: Backend not involved in actual upload transfer, only orchestration

---

# 4. Product Requirements

## Functional Requirements

### FR-1: Small File Upload Endpoint

**Requirement**: Provide `POST /upload` endpoint accepting multipart/form-data with file bytes for files ≤2MB

#### Acceptance Criteria

- [x] Accepts `Content-Type: multipart/form-data` with `file` field
- [x] Returns `413 Payload Too Large` if file >xMB
- [x] Returns file metadata (file_id, storage_key, size, mime_type, upload_url)
- [x] Validates file type against allowlist (configurable)
- [x] Validates MIME type matches file extension

### FR-2: Large File Upload Initiation

**Requirement**: Provide `POST /upload/initiate` endpoint accepting file metadata (size, name, mime_type) for files >2MB

#### Acceptance Criteria

- [x] Accepts JSON body: `{"filename": "...", "size": 15000000, "mime_type": "image/jpeg"}`
- [x] Returns `400 Bad Request` if size ≤xMB (should use mediated upload)
- [x] Returns presigned upload URL with 15-minute TTL
- [x] Returns upload_id for finalization tracking
- [x] Validates file type is supported
- [ ] Applies rate limiting per user — **deferred to FEAT-006** (decided
      2026-08-14, during Phase 3 review): no auth/user-identity infrastructure
      exists yet in this codebase for rate limits to key on (see
      `context/plans/upload-endpoint-authentication.md`).

### FR-3: Large File Upload Finalization

**Requirement**: Provide `POST /upload/finalize` endpoint to commit completed presigned URL upload

#### Acceptance Criteria

- [x] Accepts JSON body: `{"upload_id": "...", "etag": "..."}`
- [x] Verifies file exists in storage at presigned location
- [x] Returns complete file metadata matching small file response format
- [x] Returns `404 Not Found` if upload_id is unknown or already finalized
- [x] Returns `410 Gone` if upload_id is valid but its presigned URL expired
      (split out from the original "invalid or expired" wording during Phase 3
      implementation, 2026-08-14 — see TD-002 §5/§7, which already documented
      these as two separate response shapes)
- [x] Returns `400 Bad Request` if file not found in storage (upload incomplete)
- [x] Returns `400 Bad Request` if client-supplied `etag` doesn't match storage's
      reported ETag (resolves TD-002 §13's ETag open question, decided during
      Phase 3 implementation — see `EtagMismatchError`)

### FR-4: Size-Based Routing Validation

**Requirement**: Enforce file size constraints at API boundary to prevent incorrect upload path usage

#### Acceptance Criteria

- [x] `/upload` rejects files >xMB with clear error message
- [x] `/upload/initiate` rejects requests for files ≤2MB with guidance to use `/upload`
- [x] Error responses include recommended endpoint for size
- [x] Size validation occurs before any storage operations

### FR-5: Consistent Response Format

**Requirement**: Both upload paths return identical metadata structure for client compatibility

#### Acceptance Criteria

- [x] Both paths return: `{"file_id", "storage_key", "filename", "size", "mime_type", "upload_url", "created_at"}`
- [x] Field types match (e.g., size is integer, created_at is ISO8601)
- [x] `upload_url` points to file download location (generated after upload) —
      note: an expiring presigned GET URL, not the permanent CDN-style link
      shown in TD-002 §5's example; flagged and accepted during Phase 2's review
- [x] Documentation clearly states response schema

---

# 5. Success Metrics

- **Small file upload latency**: p95 <500ms (includes validation + storage write)
- **Presigned URL generation latency**: p95 <200ms (fast orchestration)
- **Large file finalization latency**: p95 <2s (includes storage verification)
- **Upload success rate**: >99.5% (excluding client-side network failures)
- **Backend bandwidth usage**: <10% of total upload traffic (most goes direct to storage)

---

# 6. Dependencies

- Depends on: **FEAT-001** (Storage Provider Abstraction) — requires storage adapter interface for upload operations
- Blocks: **FEAT-003** (Content Deduplication) — dedup logic hooks into upload flow
- Blocks: **FEAT-005** (Multipart Upload Support) — extends large file path with chunking
- Related: **FEAT-006** (Rate Limiting) — rate limits apply to initiate/finalize calls

---

# 7. Implementation Plan

## Multi-PR Implementation

**Rationale**: Feature spans data models, two distinct upload flows, and API design. Splitting by capability allows incremental review and testing without blocking dependent features.

### PR1: [FEAT-002a] - Upload Foundation

**Scope**: Database schema, file metadata models, validation utilities

**Deliverables**:

- [x] `files` table schema with migration (file_id, storage_key, filename, size, mime_type, created_at, updated_at)
- [x] `FileMetadata` Pydantic model
- [x] `UploadValidator` class (size, type, mime validation)
- [x] Configuration for allowed file types and size limits
- [x] Unit tests for validation logic

**Estimated Size**: ~8 files, ~300 LOC

**Merge Requirements**: All tests pass, migration tested locally

### PR2: [FEAT-002b] - Small File Upload (Mediated)

**Scope**: `POST /upload` endpoint with backend-mediated upload flow

**Dependencies**: Must merge after PR1

**Deliverables**:

- [x] `POST /upload` FastAPI endpoint (multipart/form-data handler)
- [x] `UploadService.upload_small_file()` method
- [x] Integration with storage provider (via FEAT-001 interface)
- [x] File metadata persistence to database
- [x] Error handling (size exceeded, invalid type, storage failure)
- [x] Unit tests + integration tests (moto-backed S3, matching this repo's existing convention over a real MinIO container)
- [x] OpenAPI schema documentation

**Estimated Size**: ~6 files, ~400 LOC

**Merge Requirements**: Integration tests pass with MinIO, OpenAPI validated

### PR3: [FEAT-002c] - Large File Upload (Presigned URLs)

**Scope**: `POST /upload/initiate` and `POST /upload/finalize` endpoints

**Dependencies**: Must merge after PR2

**Deliverables**:

- [x] `POST /upload/initiate` endpoint (generate presigned URL)
- [x] `POST /upload/finalize` endpoint (verify and commit upload)
- [x] `UploadService.initiate_large_upload()` method
- [x] `UploadService.finalize_large_upload()` method
- [x] Presigned URL generation via storage provider
- [x] Storage verification (HEAD request to confirm file exists)
- [x] Error handling (expiry, file not found, verification failure, ETag mismatch)
- [x] Integration tests (moto-backed S3, matching this repo's existing convention)
- [x] OpenAPI schema documentation

**Estimated Size**: ~8 files, ~450 LOC

**Merge Requirements**: All tests pass, presigned URLs validated with MinIO, TTL enforcement tested

---

# 8. Open Questions

- [ ] Should we support custom TTLs for presigned URLs via query parameter (e.g., `?ttl=3600`)?
- [ ] How do we handle timezone display for `created_at` (UTC everywhere, or client localization)?
- [ ] Should we return checksums (MD5/SHA256) in upload response for client-side verification?
- [ ] Do we need webhook notifications for completed uploads (async callback pattern)?
