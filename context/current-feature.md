# Current Feature

FEAT-004: Async Variant Generation

## File

[FEAT-004 - Async Variant Generation](features/FEAT-004-async-variant-generation.md)

## Goals

- [x] FR-1: WebP Variant Generation — convert JPEG/PNG/GIF uploads to WebP (quality 85), stored at `webp/{YYYY}/{MM}/{DD}/{UUID}.webp`, aspect ratio preserved
- [x] FR-2: Thumbnail Generation — 256x256 letterboxed thumbnail (quality 80), stored at `thumbnails/{YYYY}/{MM}/{DD}/{UUID}_thumb.jpg`
- [x] FR-3: Job Queueing — enqueue arq job after upload completes, 60s timeout, 3 retries with exponential backoff (1s, 5s, 25s)
- [x] FR-4: Metadata Update — atomic update of `web_optimized_url` (renamed from `webp_url`)/`thumbnail_url` on the `files` row after generation

## Notes

Single-PR feature (no phase decomposition in TD-004). Depends on FEAT-001 (storage abstraction) and FEAT-002 (hybrid upload), both Done. Building on branch `feature/file-async-variant-generation`.
