# Database Migrations (Alembic)

This project uses [Alembic](https://alembic.sqlalchemy.org/) for schema migrations,
configured for SQLAlchemy 2.0's async engine. Migration scripts live in
`alembic/versions/`; config lives in `alembic.ini` and `alembic/env.py`.

`alembic/env.py` reads the database URL from `DatabaseSettings` (`src/database.py`,
env var `DATABASE_URL`) — it does not use the static `sqlalchemy.url` placeholder
in `alembic.ini`. `env.py` also imports every domain's `models.py` (e.g.
`src/upload/models.py`) so `Base.metadata` includes all ORM models, which is what
`--autogenerate` diffs against.

## Prerequisites

- Local dependencies installed: `uv pip install -e ".[dev]"` (or `./setup.sh`)
- `DATABASE_URL` set, e.g. via `.env` (copy `.env.example`) or exported directly:

  ```bash
  export DATABASE_URL="postgresql+asyncpg://business_os:business_os@localhost:5432/business_os"
  ```

## Quickstart

1. Start Postgres:

   ```bash
   docker compose up -d postgres
   ```

2. Apply all migrations up to the latest revision:

   ```bash
   PYTHONPATH=src alembic upgrade head
   ```

3. Verify tables/indexes were created:

   ```bash
   docker compose exec postgres psql -U business_os -d business_os -c "\dt"
   docker compose exec postgres psql -U business_os -d business_os -c "\di"
   ```

`PYTHONPATH=src` is required because `alembic/env.py` imports first-party modules
(`database`, `upload.models`, ...) the same way the app does — Alembic itself
doesn't add `src/` to the import path.

## Common commands

| Task                                   | Command                                                       |
| --------------------------------------- | -------------------------------------------------------------- |
| Apply all pending migrations            | `PYTHONPATH=src alembic upgrade head`                          |
| Roll back one migration                 | `PYTHONPATH=src alembic downgrade -1`                          |
| Roll back all migrations                | `PYTHONPATH=src alembic downgrade base`                        |
| Show current revision                   | `PYTHONPATH=src alembic current`                                |
| Show migration history                  | `PYTHONPATH=src alembic history`                                |
| Create a new empty revision             | `PYTHONPATH=src alembic revision --rev-id 003 -m "short description"` |
| Autogenerate a revision from model diff | `PYTHONPATH=src alembic revision --rev-id 003 --autogenerate -m "description"` |

## Writing a migration

- Use sequential, zero-padded revision IDs (`001`, `002`, `003`, ...) via
  `--rev-id`, instead of Alembic's default random hex ID — pick the next
  number after whatever `alembic history` shows as the current head. This
  trades away Alembic's collision-avoidance for parallel branches in exchange
  for migrations that read in the same order they apply, matching this
  project's technical-design numbering (e.g. `migrations/001_create_files_table.sql`
  in a TD's Data Model section refers to the same revision `001` here).
- Prefer `--autogenerate` as a starting point, then read the generated file —
  Alembic's diffing misses some things (e.g. check constraints, some index
  options) and can be wrong about column type changes.
- Every migration must define both `upgrade()` and `downgrade()`. Migrations in
  this project are additive-only where possible (see each feature's technical
  design for its rollback plan).
- Match the target table/column definitions to the technical design's "Data
  Model" section exactly (types, constraints, indexes) — the TD is the source
  of truth, not whatever SQLAlchemy happens to autogenerate.
- Run the new migration locally (`alembic upgrade head`) against the Docker
  Postgres instance before opening a PR.

## Existing migrations

| Revision | Description                     | Feature          |
| -------- | -------------------------------- | ----------------- |
| `001`    | Create `files` table             | FEAT-002 Phase 1 |
| `002`    | Create `upload_sessions` table   | FEAT-002 Phase 1 |
