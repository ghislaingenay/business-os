# FEAT-004: Async Variant Generation

Status: Not Started
Owner: TBD
Created: 2026-08-11
Last Updated: 2026-08-11

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

- [ ] Generated for all image uploads (JPEG, PNG, GIF)
- [ ] Stored with key pattern: `webp/{YYYY}/{MM}/{DD}/{UUID}.webp`
- [ ] Quality setting: 85 (balance size vs. visual quality)
- [ ] Original aspect ratio preserved

### FR-2: Thumbnail Generation

**Requirement**: Generate 256x256 thumbnail with letterboxing (fit, not crop)

#### Acceptance Criteria

- [ ] Generated for all image uploads
- [ ] Stored with key pattern: `thumbnails/{YYYY}/{MM}/{DD}/{UUID}_thumb.jpg`
- [ ] Size: 256x256 max (preserve aspect ratio, letterbox if needed)
- [ ] Quality: 80 (acceptable for small previews)

### FR-3: Job Queueing

**Requirement**: Enqueue variant generation job after upload completes

#### Acceptance Criteria

- [ ] Job payload: `{"file_id": "...", "storage_key": "...", "mime_type": "..."}`
- [ ] Queue: Redis-backed arq queue
- [ ] Job timeout: 60 seconds per job
- [ ] Retry policy: 3 attempts with exponential backoff (1s, 5s, 25s)

### FR-4: Metadata Update

**Requirement**: Update file metadata with variant URLs after generation completes

#### Acceptance Criteria

- [ ] Database fields: `webp_url`, `thumbnail_url`
- [ ] Atomic update (both variants or neither)
- [ ] API response includes variant URLs if available

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

- [ ] `src/worker/tasks.py` (variant generation task)
- [ ] `src/worker/__init__.py` (arq configuration)
- [ ] `src/image/processor.py` (Pillow WebP/thumbnail logic)
- [ ] Update `src/upload/service.py` (enqueue job after upload)
- [ ] Add `webp_url`, `thumbnail_url` columns to `files` table
- [ ] Integration tests (end-to-end with worker)
- [ ] Docker Compose worker service configuration

**Estimated Size**: ~8 files, ~400 LOC

---

# 8. Open Questions

- [ ] Should we support custom thumbnail sizes (e.g., 128x128 for avatars)?
- [ ] Do we generate variants for uploaded videos (extract thumbnail frame)?
- [ ] Should we skip variant generation for already-optimized WebP uploads?
