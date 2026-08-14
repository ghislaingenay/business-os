"""FastAPI router for the mediated and presigned upload endpoints (TD-002 §5)."""

from fastapi import APIRouter, Depends, UploadFile, status
from fastapi import File as FormFile

from upload.dependencies import get_upload_service
from upload.schemas import (
    FileMetadata,
    FinalizeUploadRequest,
    InitiateUploadRequest,
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
    response_model=UploadSessionMetadata,
    status_code=status.HTTP_200_OK,
    summary="Initiate a large file upload, receiving a presigned PUT URL",
)
async def initiate_large_upload(
    body: InitiateUploadRequest,
    service: UploadService = Depends(get_upload_service),
) -> UploadSessionMetadata:
    return await service.initiate_large_upload(
        filename=body.filename,
        size=body.size,
        mime_type=body.mime_type,
    )


@router.post(
    "/upload/finalize",
    response_model=FileMetadata,
    status_code=status.HTTP_200_OK,
    summary="Finalize a large file upload after the client PUTs bytes to the presigned URL",
)
async def finalize_large_upload(
    body: FinalizeUploadRequest,
    service: UploadService = Depends(get_upload_service),
) -> FileMetadata:
    return await service.finalize_large_upload(upload_id=body.upload_id, etag=body.etag)
