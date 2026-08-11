# FEAT-005: Multipart Upload Support

Status: Not Started
Owner: TBD
Created: 2026-08-11
Last Updated: 2026-08-11

Technical Design: [TD-005 - Multipart Upload Support](../technical-designs/TD-005-multipart-upload-support.md)

---

# 1. Overview

## Summary

Extend large file upload (FEAT-001) with multipart upload capability for files >100MB, enabling resilient uploads via chunked transfer, part-level retry, and pause/resume functionality. Leverages storage provider's native multipart APIs (S3 Multipart Upload, GCS Resumable Upload).

## Problem

- **Large file upload failures**: 1GB file upload fails after 15 minutes due to network interruption — entire upload lost
- **No resume capability**: Users must restart uploads from beginning on failure
- **Memory exhaustion**: Uploading 500MB file in single request loads entire file into memory
- **Timeout risks**: Large files exceed gateway/load balancer timeouts (typically 30-60 seconds)

## Goals

- Support chunked uploads for files >100MB (recommended chunk size: 10MB)
- Enable pause/resume (upload parts independently, finalize when all complete)
- Provide part-level retry (re-upload failed parts without affecting completed parts)
- Track upload progress (parts completed, percentage progress)
- Automatic cleanup of abandoned multipart sessions (>24 hours old)

## Non-Goals

- Automatic resume from server side (client responsible for tracking parts)
- Cross-session resume (sessions expire after 24 hours)
- Adaptive chunk sizing (fixed 10MB chunks)

---

# 2. Users

## Primary Users

- **Mobile app users**: Upload large videos over unreliable networks
- **Content creators**: Upload multi-gigabyte files (raw footage, datasets)

## Stakeholders

- **Backend engineers**: Maintain multipart session state, cleanup logic
- **Frontend developers**: Implement chunked upload UI with progress bar

---

# 3. User Stories

### Story 1: Resume Interrupted Video Upload

As a **content creator uploading a 2GB video**
I want to **resume my upload from 60% complete after network interruption**
So that **I don't waste 15 minutes of upload time and bandwidth**

### Story 2: Part-Level Retry

As a **developer uploading a large dataset**
I want to **retry only the failed parts (not the entire file)**
So that **transient storage failures don't require full re-upload**

### Story 3: Progress Tracking

As a **mobile app user**
I want to **see upload progress (parts completed, MB uploaded, ETA)**
So that **I know the upload is progressing and can estimate completion time**

---

# 4. Product Requirements

## Functional Requirements

### FR-1: Multipart Upload Initiation

**Requirement**: Extend `POST /upload/initiate` to support multipart mode for files >100MB

#### Acceptance Criteria

- [ ] Request includes `"multipart": true` flag if file >100MB
- [ ] Response includes: `upload_id`, `part_size` (10MB), `total_parts`, `part_upload_urls[]`
- [ ] Session stored in `multipart_sessions` table with 24-hour TTL
- [ ] Part upload URLs are presigned PUT URLs (15-minute TTL per part)

### FR-2: Part Upload Tracking

**Requirement**: Provide `GET /upload/{upload_id}/status` endpoint to query upload progress

#### Acceptance Criteria

- [ ] Returns: `parts_completed[]`, `parts_remaining[]`, `progress_percentage`
- [ ] Checks storage provider for completed parts (via ListParts API)
- [ ] Response includes: `completed: 15/20`, `bytes_uploaded: 157286400`, `eta_seconds: 120`

### FR-3: Part Upload Retry

**Requirement**: Allow client to request new presigned URL for failed part

#### Acceptance Criteria

- [ ] Endpoint: `POST /upload/{upload_id}/retry-part` with `{"part_number": 5}`
- [ ] Returns new presigned URL for specified part (15-minute TTL)
- [ ] Validates part number is within valid range (1 to total_parts)

### FR-4: Multipart Upload Finalization

**Requirement**: Extend `POST /upload/finalize` to complete multipart upload

#### Acceptance Criteria

- [ ] Client sends: `{"upload_id": "...", "parts": [{"part_number": 1, "etag": "..."}, ...]}`
- [ ] Server calls storage provider's CompleteMultipartUpload API
- [ ] Server verifies all parts present (1 to total_parts with no gaps)
- [ ] Returns complete file metadata (same format as small file upload)

### FR-5: Abandoned Session Cleanup

**Requirement**: Scheduled job aborts multipart sessions older than 24 hours

#### Acceptance Criteria

- [ ] Daily cron job queries `multipart_sessions WHERE created_at < NOW() - INTERVAL '24 hours' AND finalized=false`
- [ ] Calls storage provider's AbortMultipartUpload API for each session
- [ ] Deletes session from database
- [ ] Logs cleanup metrics: `sessions_aborted`, `storage_parts_deleted`

---

# 5. Success Metrics

- **Multipart upload success rate**: >98% (higher than single-part due to retry capability)
- **Avg completion time for 1GB file**: <10 minutes (100Mbps network)
- **Part retry rate**: <5% (most parts succeed on first attempt)
- **Abandoned session cleanup rate**: <1% of total sessions (most uploads complete)

---

# 6. Dependencies

- Depends on: **FEAT-001** (Hybrid Upload) — extends large file path with multipart
- Depends on: **FEAT-003** (Storage Provider) — uses provider's multipart APIs
- Related: **FEAT-002** (Deduplication) — hash calculated after all parts uploaded

---

# 7. Implementation Plan

## Multi-PR Implementation

### PR1: [FEAT-005a] - Multipart Initiation and Tracking

**Scope**: Multipart session management, part URL generation, status endpoint

**Deliverables**:

- [ ] `multipart_sessions` table schema with migration
- [ ] `POST /upload/initiate` multipart mode support
- [ ] `GET /upload/{upload_id}/status` endpoint
- [ ] `POST /upload/{upload_id}/retry-part` endpoint
- [ ] Unit tests for session management
- [ ] Integration tests with MinIO

**Estimated Size**: ~8 files, ~450 LOC

### PR2: [FEAT-005b] - Multipart Finalization and Cleanup

**Scope**: CompleteMultipartUpload integration, cleanup job

**Dependencies**: Must merge after PR1

**Deliverables**:

- [ ] Update `POST /upload/finalize` for multipart completion
- [ ] Scheduled cleanup job (arq task)
- [ ] Error handling (incomplete parts, expired sessions)
- [ ] Integration tests (end-to-end multipart workflow)
- [ ] Metrics logging (session duration, part counts)

**Estimated Size**: ~6 files, ~350 LOC

---

# 8. Open Questions

- [ ] Should we support custom chunk sizes (e.g., 5MB for slow networks)?
- [ ] Do we need server-side pause/resume (store last completed part)?
- [ ] Should we calculate hash incrementally (per part) or after completion?
- [ ] How do we handle partial uploads across server restarts (session recovery)?
