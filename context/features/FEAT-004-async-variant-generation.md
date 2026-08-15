# FEAT-004: Async Variant Generation

Status: Doing
Owner: TBD
Created: 2026-08-11
Last Updated: 2026-08-15

Technical Design: [TD-004 - Async Variant Generation](../technical-designs/TD-004-async-variant-generation.md)

---

# 1. Overview

## Summary

Asynchronously generate optimized image variants (WebP conversion, thumbnails) after upload completes using background workers (arq), decoupling upload latency from variant processing. Variants stored alongside originals in storage provider.

## Problem

- **Synchronous processing blocks uploads**: Generating WebP + thumbnail adds 2-3 seconds to upload latency
- **Poor UX**: Users wait for processing before receiving upload confirmation
- **Scalability bottleneck**: Image processing is CPU-intensive, limits concurrent uploads
- **Wasted delivery bandwidth**: Serving full-size originals wastes bandwidth, slows page loads

## Goals

- Generate WebP variant (lossy compression, ~30% smaller than JPEG)
- Generate thumbnail (e.g., 256x256 for previews)
- Process variants asynchronously after upload completes
- Store variants in storage provider with predictable naming
- Update file metadata with variant URLs
- Retry failed jobs up to 3 times

## Non-Goals

- Real-time variant generation (blocking uploads)
- Video transcoding (Phase 2 feature)
- Custom variant sizes per request (fixed sizes only)

---

# 2. Users

## Primary Users

- **End users**: Experience fast uploads, optimized image delivery
- **Frontend developers**: Request thumbnail/WebP URLs for responsive UI

## Stakeholders

- **CDN operators**: Reduced bandwidth costs from smaller WebP files
- **Mobile users**: Faster page loads from optimized images

---

# 3. User Stories

### Story 1: Fast Upload with Background Processing

As a **mobile app user**
I want to **upload a 5MB photo and receive immediate confirmation**
So that **I don't wait for image processing before continuing my workflow**

### Story 2: Optimized Image Delivery

As a **web developer**
I want to **serve WebP images to modern browsers**
So that **page load times decrease by 30% compared to JPEG**

### Story 3: Thumbnail Previews

As a **gallery view user**
I want to **see thumbnail previews (not full images)**
So that **the gallery page loads in <1 second even with 100 images**

---

# 4. Product Requirements

## Functional Requirements

### FR-1: WebP Variant Generation

**Requirement**: Convert uploaded JPEG/PNG images to WebP format with 85% quality

#### Acceptance Criteria

- [x] Generated for all image uploads (JPEG, PNG, GIF)
- [x] Stored with key pattern: `webp/{YYYY}/{MM}/{DD}/{UUID}.webp`
- [x] Quality setting: 85 (balance size vs. visual quality)
- [x] Original aspect ratio preserved

### FR-2: Thumbnail Generation

**Requirement**: Generate 256x256 thumbnail with letterboxing (fit, not crop)

#### Acceptance Criteria

- [x] Generated for all image uploads
- [x] Stored with key pattern: `thumbnails/{YYYY}/{MM}/{DD}/{UUID}_thumb.jpg`
- [x] Size: 256x256 max (preserve aspect ratio, letterbox if needed)
- [x] Quality: 80 (acceptable for small previews)

### FR-3: Job Queueing

**Requirement**: Enqueue variant generation job after upload completes

#### Acceptance Criteria

- [x] Job payload: `{"file_id": "...", "storage_key": "...", "mime_type": "..."}`
      (passed as arq's positional job args, not a literal dict — arq jobs
      don't take a payload object, they take function arguments; carries the
      same three fields)
- [x] Queue: Redis-backed arq queue
- [x] Job timeout: 60 seconds per job
- [x] Retry policy: 3 attempts with exponential backoff (1s, 5s, 25s)

### FR-4: Metadata Update

**Requirement**: Update file metadata with variant URLs after generation completes

#### Acceptance Criteria

- [x] Database fields: `web_optimized_url` (renamed from `webp_url`, see TD-004 §4), `thumbnail_url`
- [x] Atomic update (both variants or neither)
- [x] API response includes variant URLs if available

---

# 5. Success Metrics

- **Variant generation latency**: p95 <5 seconds from upload complete
- **Success rate**: >99% (failed jobs logged for manual inspection)
- **WebP size reduction**: 25-35% smaller than original JPEG
- **Thumbnail generation time**: p95 <2 seconds

---

# 6. Dependencies

- Depends on: **FEAT-002** (Hybrid Upload) — variants generated after upload completes
- Depends on: **FEAT-001** (Storage Provider) — workers upload variants to storage
- Related: **FEAT-007** (Observability) — log variant generation metrics

---

# 7. Implementation Plan

## Single PR Implementation

**Scope**: arq worker, Pillow processing, job queueing, metadata update

**Deliverables**:

- [x] `src/worker/tasks.py` (variant generation task)
- [x] `src/worker/__init__.py` (arq configuration)
- [x] `src/shared/image/processor.py` (Pillow WebP/thumbnail logic — placed
      under `shared/` rather than a top-level `src/image/`, since it's a
      business-agnostic technical capability per coding-standards.md §12, not
      a domain)
- [x] `src/variants/` domain (`service.py`, `repository.py`, `config.py`,
      `exceptions.py`) — orchestrates download → generate → upload → persist;
      not called out by name in TD-004 §3 but required to keep business logic
      out of the arq task boundary per coding-standards.md's layering rules
- [x] `src/shared/queue/provider.py` (arq/Redis job-queue client)
- [x] Update `src/upload/service.py` (enqueue job after both mediated and
      presigned upload paths complete)
- [x] Add `web_optimized_url` (renamed from `webp_url`), `thumbnail_url`,
      `variants_processed_at` columns to `files` table
      (`alembic/versions/003_add_variant_columns_to_files.py`)
- [x] Unit/service-level tests for image processing, variant service, arq
      task retry/backoff, and job enqueueing (mocked storage/DB per this
      repo's existing test convention — no live-infra integration test, same
      as every other domain's test suite)
- [x] Docker Compose worker service configuration (`docker-compose.yml`) —
      required adding a `Dockerfile` too, since the app had none before this
      feature (it previously only ran locally via `uvicorn`); a `make worker`
      target was also added for local (non-Docker) dev

**Estimated Size**: ~8 files, ~400 LOC (actual: ~20 files — the domain/DI
wiring the TD's file list didn't spell out, e.g. `container.py`,
`upload/dependencies.py`, `upload/schemas.py`, plus the `variants` domain's
own repository/config/exceptions files)

---

# 8. Open Questions

- [ ] Should we support custom thumbnail sizes (e.g., 128x128 for avatars)?
      Out of scope for this implementation — Non-Goals explicitly states
      "Custom variant sizes per request (fixed sizes only)". Revisit only if
      a future feature requests per-request sizing.
- [ ] Do we generate variants for uploaded videos (extract thumbnail frame)?
      Out of scope for this implementation — Non-Goals explicitly states
      "Video transcoding (Phase 2 feature)". The worker skips any file whose
      `mime_type` isn't one of FR-1's listed image types.
- [x] Should we skip variant generation for already-optimized WebP uploads?
      **Resolved 2026-08-15**: Not applicable today — `upload.config.UploadSettings.allowed_file_types`
      does not include `image/webp` in its default allowlist, so a WebP
      original can't reach the upload pipeline in the first place. FR-1's
      acceptance criteria only requires variants for JPEG/PNG/GIF. If
      `image/webp` is ever added to the allowlist, this decision should be
      revisited.
