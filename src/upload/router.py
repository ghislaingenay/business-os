"""FastAPI router for the mediated, presigned, and multipart upload
endpoints (TD-002 §5, TD-005 §4).
"""

import uuid

from fastapi import APIRouter, Depends, UploadFile, status
from fastapi import File as FormFile

from upload.dependencies import get_multipart_service, get_upload_service
from upload.multipart_service import MultipartService
from upload.schemas import (
    FileMetadata,
    FinalizeUploadRequest,
    InitiateUploadRequest,
    MultipartUploadSessionMetadata,
    MultipartUploadStatus,
    RetryPartRequest,
    RetryPartResponse,
    UploadSessionMetadata,
)
from upload.service import UploadService

router = APIRouter(tags=["upload"])


@router.post(
    "/upload",
    response_model=FileMetadata,
    status_code=status.HTTP_200_OK,
    summary="Upload a small file via backend-mediated transfer",
)
async def upload_small_file(
    file: UploadFile = FormFile(...),
    service: UploadService = Depends(get_upload_service),
) -> FileMetadata:
    return await service.upload_small_file(
        filename=file.filename or "",
        mime_type=file.content_type or "",
        stream=file,
    )


@router.post(
    "/upload/initiate",
    response_model=UploadSessionMetadata | MultipartUploadSessionMetadata,
    status_code=status.HTTP_200_OK,
    summary=(
        "Initiate a large file upload: a single presigned PUT URL, or (with "
        "`multipart: true`) a chunked multipart session"
    ),
)
async def initiate_large_upload(
    body: InitiateUploadRequest,
    service: UploadService = Depends(get_upload_service),
    multipart_service: MultipartService = Depends(get_multipart_service),
) -> UploadSessionMetadata | MultipartUploadSessionMetadata:
    if body.multipart:
        return await multipart_service.initiate(
            filename=body.filename, size=body.size, mime_type=body.mime_type
        )
    return await service.initiate_large_upload(
        filename=body.filename,
        size=body.size,
        mime_type=body.mime_type,
    )


@router.get(
    "/upload/{upload_id}/status",
    response_model=MultipartUploadStatus,
    status_code=status.HTTP_200_OK,
    summary="Get part-level progress for a multipart upload session",
)
async def get_multipart_upload_status(
    upload_id: uuid.UUID,
    multipart_service: MultipartService = Depends(get_multipart_service),
) -> MultipartUploadStatus:
    return await multipart_service.get_status(upload_id)


@router.post(
    "/upload/{upload_id}/retry-part",
    response_model=RetryPartResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a fresh presigned URL for a single part of a multipart upload",
)
async def retry_multipart_part(
    upload_id: uuid.UUID,
    body: RetryPartRequest,
    multipart_service: MultipartService = Depends(get_multipart_service),
) -> RetryPartResponse:
    return await multipart_service.retry_part(upload_id, body.part_number)


@router.post(
    "/upload/finalize",
    response_model=FileMetadata,
    status_code=status.HTTP_200_OK,
    summary=(
        "Finalize a large file upload: either a single presigned PUT (via "
        "`etag`) or a multipart session (via `parts`)"
    ),
)
async def finalize_large_upload(
    body: FinalizeUploadRequest,
    service: UploadService = Depends(get_upload_service),
    multipart_service: MultipartService = Depends(get_multipart_service),
) -> FileMetadata:
    if body.parts is not None:
        return await multipart_service.finalize(upload_id=body.upload_id, parts=body.parts)
    assert body.etag is not None  # enforced by FinalizeUploadRequest's model_validator
    return await service.finalize_large_upload(upload_id=body.upload_id, etag=body.etag)
