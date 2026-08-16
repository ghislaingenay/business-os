"""Upload-domain exception to HTTP-response mappings (TD-002 §5, §7).

Registered onto the FastAPI app by `exceptions.register_exception_handlers`.
Kept in the owning domain since the response shapes (messages,
`suggested_endpoint`, etc.) are upload API contract, not shared infra.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from upload.exceptions import (
    EtagMismatchError,
    FileTooLargeError,
    FileTooSmallError,
    FileTooSmallForMultipartError,
    IncompletePartsError,
    InvalidFileTypeError,
    InvalidPartNumberError,
    MimeMismatchError,
    MultipartSessionExpiredError,
    MultipartSessionNotFoundError,
    PresignedUrlExpiredError,
    UploadIncompleteError,
    UploadNotFoundError,
)


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
    app.add_exception_handler(FileTooSmallError, _handle_file_too_small)  # type: ignore[arg-type]
    app.add_exception_handler(UploadNotFoundError, _handle_upload_not_found)  # type: ignore[arg-type]
    app.add_exception_handler(
        UploadIncompleteError,
        _handle_upload_incomplete,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        PresignedUrlExpiredError,
        _handle_presigned_url_expired,  # type: ignore[arg-type]
    )
    app.add_exception_handler(EtagMismatchError, _handle_etag_mismatch)  # type: ignore[arg-type]
    app.add_exception_handler(
        FileTooSmallForMultipartError,
        _handle_file_too_small_for_multipart,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        MultipartSessionNotFoundError,
        _handle_multipart_session_not_found,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        MultipartSessionExpiredError,
        _handle_multipart_session_expired,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        InvalidPartNumberError,
        _handle_invalid_part_number,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        IncompletePartsError,
        _handle_incomplete_parts,  # type: ignore[arg-type]
    )


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
            "detected_mime": exc.mime_type,
            "filename": exc.filename,
        },
    )


async def _handle_file_too_small(_request: Request, exc: FileTooSmallError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "file_too_small",
            "message": (
                f"File size ({exc.size} bytes) is <= {exc.max_size} byte limit. "
                "Use /upload endpoint for small files."
            ),
            "suggested_endpoint": "/upload",
        },
    )


async def _handle_upload_not_found(_request: Request, exc: UploadNotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": "upload_not_found",
            "message": "Upload session not found or already finalized",
            "upload_id": str(exc.upload_id),
        },
    )


async def _handle_upload_incomplete(_request: Request, exc: UploadIncompleteError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "upload_incomplete",
            "message": "File not found in storage. Upload may not have completed successfully.",
            "storage_key": exc.storage_key,
        },
    )


async def _handle_presigned_url_expired(
    _request: Request, exc: PresignedUrlExpiredError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_410_GONE,
        content={
            "error": "presigned_url_expired",
            "message": "Presigned URL expired. Initiate a new upload.",
            "expired_at": exc.expired_at.isoformat(),
        },
    )


async def _handle_etag_mismatch(_request: Request, exc: EtagMismatchError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "etag_mismatch",
            "message": "Uploaded file's ETag does not match the reported ETag.",
            "expected_etag": exc.expected,
            "actual_etag": exc.actual,
        },
    )


async def _handle_file_too_small_for_multipart(
    _request: Request, exc: FileTooSmallForMultipartError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "file_too_small_for_multipart",
            "message": (
                f"File size ({exc.size} bytes) is <= {exc.min_size} byte multipart threshold. "
                "Use /upload/initiate without multipart for this file size."
            ),
            "min_multipart_size": exc.min_size,
        },
    )


async def _handle_multipart_session_not_found(
    _request: Request, exc: MultipartSessionNotFoundError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": "multipart_session_not_found",
            "message": "Multipart session not found or already finalized",
            "upload_id": str(exc.upload_id),
        },
    )


async def _handle_multipart_session_expired(
    _request: Request, exc: MultipartSessionExpiredError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_410_GONE,
        content={
            "error": "multipart_session_expired",
            "message": "Multipart session expired. Initiate a new upload.",
            "expired_at": exc.expired_at.isoformat(),
        },
    )


async def _handle_invalid_part_number(
    _request: Request, exc: InvalidPartNumberError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "invalid_part_number",
            "message": (
                f"Part number {exc.part_number} is outside the valid range "
                f"[1, {exc.total_parts}]"
            ),
            "total_parts": exc.total_parts,
        },
    )


async def _handle_incomplete_parts(_request: Request, exc: IncompletePartsError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "incomplete_parts",
            "message": "Not all parts were provided for this multipart upload",
            "upload_id": str(exc.upload_id),
            "missing_parts": exc.missing_parts,
        },
    )
