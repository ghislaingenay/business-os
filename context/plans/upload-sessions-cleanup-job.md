# PLAN: Cleanup Job for Stale `upload_sessions`

Status: Proposed
Created: 2026-08-14

Relates to: [FEAT-002 - Hybrid Upload Strategy](../features/FEAT-002-hybrid-upload-strategy.md) / [TD-002](../technical-designs/TD-002-hybrid-upload-strategy.md) §13

---

## Summary

TD-002 §13 asks: *"Should `upload_sessions` have a cleanup job (delete finalized
sessions >24h old)?"* — left unresolved. Phase 3 (`/upload/initiate` +
`/upload/finalize`) writes rows to `upload_sessions` on every initiate call but
never deletes any, whether they were later finalized or simply abandoned
(client never PUT the bytes, or the presigned URL expired unused). This plan
sketches a periodic cleanup job to bound that table's growth.

## Why

Every `/upload/initiate` call inserts a row, regardless of what happens next.
Three cases accumulate indefinitely with no cleanup:

- **Finalized sessions**: once `finalize_large_upload` succeeds, the session
  row has done its job (the `files` row is now the record of truth) but stays
  in the table forever.
- **Abandoned sessions**: a client that never calls `/upload/finalize` (gave
  up, crashed, or the presigned URL just expired unused) leaves a permanently
  "pending" row with no automatic follow-up.
- **Expired-and-retried sessions**: TD-002 §7's `presigned_url_expired` (410)
  path tells the client to re-initiate, which creates a *new* session row —
  the old expired one is orphaned, not reused or removed.

Per `idx_upload_sessions_expires_at` (already in the Phase 1 migration,
`WHERE NOT finalized`) and `idx_upload_sessions_finalized`, the schema was
clearly built anticipating this cleanup need — the indexes exist, the job
that would use them doesn't.

## Not built yet

Out of Phase 3's scope as defined in TD-002 §9 ("Implementation Phases"):
Phase 3's file list is `router.py`, `service.py`, and tests only — no
scheduler, worker, or job runner. This plan is a proposed follow-up, not
scheduled against a specific phase/PR.

## Sketch (for future implementation, not final)

- **Deletion policy** (per TD-002 §13's own framing — "delete finalized
  sessions >24h old"):
  - Finalized sessions older than some retention window (TD-002 suggests
    24h) — safe to delete, `files` already has the durable record.
  - Non-finalized sessions past `expires_at` by some grace window — safe to
    delete, the presigned URL is dead and unusable regardless.
- **Mechanism**: per `context/coding-standards.md` §14 (Background Work),
  this is explicitly *not* a `BackgroundTasks` fit ("short, non-critical
  in-process work" only) — a periodic sweep over a growing table is
  "scheduling" work, which that same section says needs "a real task queue."
  A scheduled job (cron-triggered script, Celery beat, or equivalent —
  whatever this project's chosen task-queue technology ends up being) calling
  a new `UploadSessionRepository.delete_stale(before: datetime) -> int`
  method is the natural shape; no new domain needed, this stays inside
  `upload/`.
- **Alternative**: a Postgres-native approach (e.g. a scheduled `DELETE ...
  WHERE` via `pg_cron` or an external cron hitting a small admin endpoint)
  instead of an application-level task queue, if this project ends up not
  needing a general-purpose task queue for anything else.

## Open Questions

- Exact retention windows — TD-002 §13 suggests "24h" for finalized sessions
  but doesn't specify a grace period for expired-unfinalized ones. Reusing
  `PRESIGNED_URL_TTL` (900s) as that grace period seems reasonable but isn't
  decided.
- Task queue technology — this project has none yet (no Celery, no cron
  runner, no equivalent) as of FEAT-002 Phase 3. Introducing one is a bigger
  architectural decision than this cleanup job alone justifies; may be worth
  deciding project-wide rather than per-feature.
- Should deletion be hard (`DELETE`) or soft (a `deleted_at` column), given
  `upload_sessions` currently has no soft-delete precedent anywhere in this
  codebase?
