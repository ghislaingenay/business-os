"""Top-level exception-handler registration.

Domain code (services, repositories) raises domain-specific exceptions and
never `HTTPException` (see `context/coding-standards.md` §11). Each domain
owns the HTTP mapping for its own exceptions (e.g.
`upload.exception_handlers`); this module only handles exceptions from
shared, cross-domain infrastructure and aggregates every domain's
registration into one call for `main.py`.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from dedup.exceptions import DedupDatabaseUnavailableError
from shared.storage.exceptions import StorageError
from upload.exception_handlers import register_upload_exception_handlers


def register_exception_handlers(app: FastAPI) -> None:
    register_upload_exception_handlers(app)
    # See note in upload/exception_handlers.py on this ignore.
    app.add_exception_handler(StorageError, _handle_storage_error)  # type: ignore[arg-type]
    app.add_exception_handler(
        DedupDatabaseUnavailableError,
        _handle_dedup_database_unavailable,  # type: ignore[arg-type]
    )


async def _handle_storage_error(_request: Request, _exc: StorageError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "error": "storage_unavailable",
            "message": "Storage provider is temporarily unavailable",
        },
    )


async def _handle_dedup_database_unavailable(
    _request: Request, _exc: DedupDatabaseUnavailableError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "error": "dedup_database_unavailable",
            "message": "Deduplication check failed: database temporarily unavailable",
        },
    )
