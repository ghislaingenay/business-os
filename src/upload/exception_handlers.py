"""Upload-domain exception to HTTP-response mappings (TD-002 §5, §7).

Registered onto the FastAPI app by `exceptions.register_exception_handlers`.
Kept in the owning domain since the response shapes (messages,
`suggested_endpoint`, etc.) are upload API contract, not shared infra.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from upload.exceptions import FileTooLargeError, InvalidFileTypeError, MimeMismatchError


def register_upload_exception_handlers(app: FastAPI) -> None:
    # Starlette's add_exception_handler is typed invariant on `Exception`, so a
    # handler narrowed to a specific subclass always fails strict mypy here
    # even though it's the documented, correct usage.
    app.add_exception_handler(FileTooLargeError, _handle_file_too_large)  # type: ignore[arg-type]
    app.add_exception_handler(
        InvalidFileTypeError,
        _handle_invalid_file_type,  # type: ignore[arg-type]
    )
    app.add_exception_handler(MimeMismatchError, _handle_mime_mismatch)  # type: ignore[arg-type]


async def _handle_file_too_large(_request: Request, exc: FileTooLargeError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        content={
            "error": "file_too_large",
            "message": (
                f"File size ({exc.size} bytes) exceeds {exc.max_size} byte limit. "
                "Use /upload/initiate for large files."
            ),
            "max_size": exc.max_size,
            "suggested_endpoint": "/upload/initiate",
        },
    )


async def _handle_invalid_file_type(_request: Request, exc: InvalidFileTypeError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "invalid_file_type",
            "message": f"File type {exc.mime_type!r} is not allowed",
            "allowed_types": list(exc.allowed_types),
        },
    )


async def _handle_mime_mismatch(_request: Request, exc: MimeMismatchError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "mime_mismatch",
            "message": (
                f"MIME type {exc.mime_type!r} does not match file extension of {exc.filename!r}"
            ),
            "mime_type": exc.mime_type,
            "filename": exc.filename,
        },
    )
