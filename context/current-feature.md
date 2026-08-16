# Current Feature

FEAT-005: Multipart Upload Support

## File

[FEAT-005 - Multipart Upload Support](features/FEAT-005-multipart-upload-support.md)

## Goals

- [ ] FR-1: Multipart Upload Initiation — `POST /upload/initiate` accepts `multipart: true` for files >100MB, returns `upload_id`, `part_size` (10MB), `total_parts`, `part_upload_urls[]`; session stored in `multipart_sessions` with 24h TTL; part URLs are presigned PUT with 15-min TTL
- [ ] FR-2: Part Upload Tracking — `GET /upload/{upload_id}/status` returns `parts_completed[]`, `parts_remaining[]`, `progress_percentage`, checked against storage's ListParts-equivalent
- [ ] FR-3: Part Upload Retry — `POST /upload/{upload_id}/retry-part` issues a new presigned URL for a given part number, validated against `[1, total_parts]`
- [ ] FR-4: Multipart Upload Finalization — `POST /upload/finalize` completes multipart uploads via CompleteMultipartUpload-equivalent, verifying no gaps in parts
- [ ] FR-5: Abandoned Session Cleanup — scheduled job aborts multipart sessions older than 24h and deletes their DB rows

## Notes

Implementing the entire feature (both TD-005 phases) as a single PR on branch
`feature/multipart-upload-support`, per explicit user instruction — no PR
Progress/phase-decomposition tracking. Depends on FEAT-001 (storage
abstraction) and FEAT-002 (hybrid upload), both Done.
