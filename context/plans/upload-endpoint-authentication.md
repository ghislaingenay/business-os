# PLAN: Authentication for Upload Endpoints

Status: Proposed
Created: 2026-08-13

Relates to: [FEAT-002 - Hybrid Upload Strategy](../features/FEAT-002-hybrid-upload-strategy.md) / [TD-002](../technical-designs/TD-002-hybrid-upload-strategy.md) §10

---

## Summary

TD-002 §10 Security Considerations requires: *"All endpoints require valid JWT
token in `Authorization: Bearer <token>` header"* and *"Upload sessions tied to
user_id (prevent finalization by different user)."* Neither is implemented —
`POST /upload` (FEAT-002 Phase 2) currently has no auth dependency at all, and
no `auth` domain exists anywhere in this codebase yet. This plan sketches the
architecture needed to close that gap.

**Out of scope for this plan**: whether to build JWT issuance in-house or
delegate to an external third-party identity provider (Auth0, Clerk, AWS
Cognito, Supabase Auth, etc.). That decision affects only *where tokens come
from*, not the shape of how this app verifies and consumes them — it will be
discussed and decided separately. This plan assumes only that requests arrive
with a JWT in the `Authorization` header, however it was issued.

## Why

Per `context/coding-standards.md` §8, request-level authentication is a
FastAPI `Depends` concern, composed once and reused across routers — not
something each domain router should reimplement. Without it:

- Anyone can call `POST /upload` (and, once built, `/upload/initiate` /
  `/upload/finalize`) unauthenticated.
- There is no `user_id` to scope `upload_sessions`/`files` to, so TD-002's
  "prevent finalization by different user" mitigation has nothing to attach
  to — Phase 3's finalize endpoint cannot enforce it without this landing
  first (or growing its own ad hoc check, which coding-standards.md's DI
  section rules out).
- FEAT-006 (Rate Limiting, "Related" to FEAT-002) is specified as
  per-user — it also needs an authenticated identity to key on.

## Not built yet

FEAT-002 Phase 1 and Phase 2 (this session) shipped without auth, matching
what their TD phase scope actually listed (`router.py`, `service.py`, data
model, validators — no auth middleware). This plan is a proposed follow-up,
not yet approved or scheduled against a specific phase/PR.

## Architecture sketch (for future TD, not final)

Following `context/coding-standards.md`'s domain-oriented layout (no global
`services/`/`middleware/` folders) and this repo's existing shared-vs-domain
split (`shared/storage/` for reusable infra, `upload/` for the upload
domain):

- **New `src/auth/` domain** (technical-agnostic of the token issuer):
  - `models.py` / `schemas.py` — an `AuthenticatedUser` value object (at
    minimum: `user_id`, decoded from the JWT `sub` claim).
  - `dependencies.py` — `get_current_user(request) -> AuthenticatedUser`,
    the single FastAPI `Depends` every protected router imports. This is
    the one integration point that would change if the token issuer changes
    later (in-house vs. third-party) — everything downstream only ever sees
    `AuthenticatedUser`.
  - `exceptions.py` — `InvalidTokenError`, `TokenExpiredError`, etc., mapped
    to `401 Unauthorized` the same way `upload/exception_handlers.py` maps
    upload's domain exceptions (a matching `auth/exception_handlers.py`,
    aggregated into `src/exceptions.py::register_exception_handlers`
    alongside upload's, same pattern already established there).
  - `config.py` — whatever the verification step needs (issuer, audience,
    JWKS URL or shared secret) — deliberately not designed yet, since it
    depends on the in-house-vs-third-party decision this plan defers.
- **Upload domain changes**:
  - `upload/router.py`'s `/upload` (and future `/upload/initiate`,
    `/upload/finalize`) gain `user: AuthenticatedUser =
    Depends(get_current_user)`.
  - `files` and `upload_sessions` tables gain a `user_id` column (new
    migration), so `UploadService` can persist who uploaded what and Phase
    3's finalize can reject a mismatched `user_id` per TD-002 §10.
- **`src/main.py`** wires nothing extra beyond including whatever router
  `auth` exposes (likely none — `get_current_user` is consumed via
  `Depends`, not mounted as its own routes, unless a `/auth` domain later
  needs login/refresh endpoints, which is itself part of the deferred
  in-house-vs-third-party decision).

## Open Questions

- In-house JWT issuance vs. third-party identity provider — **explicitly
  deferred**, to be discussed separately before `auth/config.py` and the
  verification implementation are designed.
- Does `get_current_user` verify a JWT locally (shared secret / JWKS
  fetch+cache) or call out to an identity provider per request? This follows
  from the deferred decision above.
- Should unauthenticated access remain possible for any upload path (e.g. a
  public/anonymous upload tier), or is auth unconditionally required on all
  three endpoints as TD-002 §10 currently states?
- Does `user_id` on `files`/`upload_sessions` reference a `users` table this
  repo doesn't have yet, or just store the JWT `sub` claim as an opaque
  string/UUID with no FK (since no `users` domain exists)?
- Should this land before FEAT-002 Phase 3 (`/upload/initiate` +
  `/upload/finalize`), since Phase 3's "prevent finalization by different
  user" mitigation depends on it? If not, Phase 3 ships with that specific
  TD-002 mitigation unmet, same gap Phase 2 currently has.
