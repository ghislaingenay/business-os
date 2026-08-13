# Current Feature

FEAT-002: Hybrid Upload Strategy — Phase 1 (Upload Foundation)

## File

[FEAT-002 - Hybrid Upload Strategy](features/FEAT-002-hybrid-upload-strategy.md) ([TD-002](technical-designs/TD-002-hybrid-upload-strategy.md))

## Goals

- [x] `files` table schema with migration (file_id, storage_key, filename, size, mime_type, sha256_hash, upload_strategy, created_at, updated_at)
- [x] `upload_sessions` table schema with migration (upload_id, filename, size, mime_type, presigned_url, storage_key, expires_at, finalized, created_at)
- [x] `FileMetadata` Pydantic model
- [x] `UploadValidator` class (size, type, mime validation)
- [x] Configuration for allowed file types and size limits
- [x] Unit tests for validation logic

## Notes

Phase 1 of 3 for FEAT-002. Scope is limited to data model, validation utilities,
and config — no endpoints or storage integration yet (that's Phase 2/3). Depends
on FEAT-001 (Storage Provider Abstraction), already Done.
