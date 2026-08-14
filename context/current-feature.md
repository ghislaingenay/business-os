# Current Feature

FEAT-002: Hybrid Upload Strategy — Phase 3 (Large File Upload - Presigned URLs)

## File

[FEAT-002 - Hybrid Upload Strategy](features/FEAT-002-hybrid-upload-strategy.md) ([TD-002](technical-designs/TD-002-hybrid-upload-strategy.md))

## Goals

- [ ] `POST /upload/initiate` endpoint (generate presigned URL)
- [ ] `POST /upload/finalize` endpoint (verify and commit upload)
- [ ] `UploadService.initiate_large_upload()` method
- [ ] `UploadService.finalize_large_upload()` method
- [ ] Presigned URL generation via storage provider (15-minute TTL)
- [ ] Storage verification (HEAD request to confirm file exists) before finalizing
- [ ] Error handling: 400 file_too_small, 400 invalid_file_type, 429 rate_limit_exceeded (initiate); 404 upload_not_found, 400 upload_incomplete, 410 presigned_url_expired (finalize)
- [ ] Integration tests (presigned URL workflow, TTL enforcement)

## Notes

Phase 3 of 3 for FEAT-002 — the final phase. Depends on Phase 2 merged
(`feature/hybrid-upload-b`, complete). Scope is `/upload/initiate` +
`/upload/finalize` only; FR-4's `/upload/initiate` ≤2MB-rejection bullet and
all of FR-5 (consistent response format across both paths) complete here too,
since they need both paths to exist. Rate limiting (FR-2's last AC) is
"Related" to FEAT-006, not a hard dependency — plan to stub/defer per TD-002
open questions unless FEAT-006 is already available.
