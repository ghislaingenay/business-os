# PLAN: Per-Project Upload Validation Settings

Status: Proposed
Created: 2026-08-13

Relates to: [FEAT-002 - Hybrid Upload Strategy](../features/FEAT-002-hybrid-upload-strategy.md) / [TD-002](../technical-designs/TD-002-hybrid-upload-strategy.md)

---

## Summary

FEAT-002/TD-002 Phase 1 ships a single **global** upload validation config: one
`MAX_SMALL_FILE_SIZE` threshold and one `ALLOWED_FILE_TYPES` allowlist for the
whole app. This plan proposes replacing that with **per-project (per-bucket)**
validation settings, where each upload target ("project", e.g. `food-menu-items`,
`profile-pictures`) has its own list of allowed `(content_type, format, max_size)`
combinations, looked up by a project code before validating a file.

This mirrors a pattern from a reference implementation (TypeScript/AdonisJS,
`FileValidator` + `FileMetadata`), where:

- Each `FileProject` has a `code` and a list of `FileProjectSettings`
  (`fileProjectId`, `fileType`, `format`, `contentType`, `maxSize`).
- Validation looks up the project by code, matches the uploaded file's MIME
  type against that project's settings, checks the filename extension agrees
  with the matched setting's `format`, then checks `size` against that
  setting's `maxSize` — not a single global limit.

## Why

A single global size/type allowlist can't express that, say, profile pictures
should cap at 2MB/JPEG-PNG while a "documents" project should allow PDFs up to
20MB. Per-project settings let each upload consumer declare its own limits
without changing global config or forking the validator.

## Not built yet

Phase 1 of FEAT-002 (this session) deliberately kept the flat global config
(`src/upload/config.py` → `UploadSettings`) to match TD-002 as written. This
plan is a proposed amendment, not yet approved or scheduled.

## Sketch (for future TD amendment, not final)

- New tables: `file_projects` (code, name, description) and
  `file_project_settings` (file_project_id FK, content_type, format, file_type,
  max_size).
- `UploadValidator` gains a project `code` parameter; looks up matching
  settings before validating size/type/mime instead of using
  `UploadSettings.allowed_file_types` / `max_small_file_size`.
- Existing global `UploadSettings` env vars become a fallback/default project,
  or are removed once all upload call sites specify a project code.

## Open Questions

- Do project settings live in the database (dynamic, admin-editable) or in
  code/config (static, deploy-time)? The TS reference example hardcodes them
  in-memory, which suggests a starting point but not necessarily the target
  shape.
- Is a project code passed by the client (e.g. `POST /upload?project=food-menu-items`)
  or inferred from the authenticated caller/route?
- Does this replace TD-002's `ALLOWED_FILE_TYPES`/`MAX_SMALL_FILE_SIZE` env
  vars entirely, or coexist as a global default when no project is specified?
- Should this land before or after FEAT-002 Phase 2/3 ship, given Phase 2/3
  build directly on the current flat `UploadValidator` signature?
