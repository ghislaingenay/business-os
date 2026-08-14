# PLAN: user_id / tenant_id Scoping for Uploads

Status: Proposed
Created: 2026-08-14

Relates to: [FEAT-002 - Hybrid Upload Strategy](../features/FEAT-002-hybrid-upload-strategy.md) / [TD-002](../technical-designs/TD-002-hybrid-upload-strategy.md) §10, [upload-endpoint-authentication.md](upload-endpoint-authentication.md)

---

## Summary

TD-002 §10 states "Upload sessions tied to user_id (prevent finalization by
different user)" as a security requirement, but neither `files` nor
`upload_sessions` has a `user_id` column, and nothing scopes lookups by user.
This plan sketches where that linkage would go. It is **fully blocked on**
`upload-endpoint-authentication.md` — there is no way to obtain a `user_id`
without that auth work landing first, so nothing here can start independently.

`tenant_id` is included in the title because it came up alongside `user_id`
in discussion, but unlike `user_id` it has **no existing precedent anywhere
in this codebase** — there is no `users`, `organizations`, or `workspaces`
concept at all yet. Introducing `tenant_id` isn't a column addition, it's a
from-scratch design decision (what is a tenant here? an org? a workspace?)
that should be made deliberately, not smuggled in as a side effect of adding
`user_id`.

## Why

Without `user_id` scoping, `UploadSessionRepository.find_active_by_id`
(`src/upload/repository.py`) matches purely on `upload_id` — any caller who
knows or guesses a valid `upload_id` UUID can finalize someone else's upload
session. TD-002 notes `upload_id` is a UUID v4 specifically to make guessing
impractical, but that's a mitigation against enumeration, not a substitute
for actual authorization scoping.

## Sketch (for future implementation, not final — nothing here has been built)

- **Database schema**: `files` and `upload_sessions`
  (`alembic/versions/001_create_files_table.py`,
  `002_create_upload_sessions_table.py`) would each need a `user_id` column.
  Whether it's a real FK or an unconstrained UUID depends on whether a
  `users` table exists by the time this is built — it doesn't today.
- **ORM models**: `src/upload/models.py`'s `File` and `UploadSession` would
  each need `user_id: Mapped[uuid.UUID]`, likely indexed.
- **Repository layer** — the part that actually matters for the security
  mitigation, not just bookkeeping: `UploadSessionRepository.find_active_by_id`
  would need to become `find_active_by_id(upload_id, user_id)`, filtering by
  *both* in the query (`WHERE upload_id = ? AND user_id = ? AND NOT finalized`).
  A different user's finalize attempt should look identical to an unknown
  `upload_id` (404 `UploadNotFoundError`) — scoping at the query level is what
  prevents cross-user finalization, not a check performed after fetching.
- **Service layer**: `upload_small_file`, `initiate_large_upload`, and
  `finalize_large_upload` (`src/upload/service.py`) would each need a
  `user_id: uuid.UUID` parameter threaded through, both to stamp new rows and
  to pass into the now-scoped repository lookups.
- **Router layer**: each of the three endpoints
  (`src/upload/router.py`) would add
  `user: AuthenticatedUser = Depends(get_current_user)` (the dependency
  sketched in `upload-endpoint-authentication.md`) and pass `user.user_id`
  into the service call — this is the actual entry point for `user_id`, so
  it's fully blocked on that auth work existing.
- **API responses**: `FileMetadata`/`UploadSessionMetadata` should probably
  *not* expose `user_id` — FR-5 fixes the response shape already — so it
  stays persistence-only, the same treatment as `files.etag`.

## Open Questions

- Everything in `upload-endpoint-authentication.md`'s Open Questions applies
  here first (in-house vs. third-party auth, JWT verification approach) —
  this plan can't proceed until those are resolved.
- Does `tenant_id` even belong on `files`/`upload_sessions` directly, or
  should tenant scoping be derived transitively through `user_id` → a future
  `users` table → its `tenant_id`? Depends entirely on how (or whether) this
  app ends up modeling multi-tenancy, which is undecided.
- Is `user_id` a hard requirement for *all* uploads, or should an anonymous/
  public upload tier remain possible (same question already listed in
  `upload-endpoint-authentication.md`)?
