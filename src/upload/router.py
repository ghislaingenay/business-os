"""FastAPI router for the mediated small-file upload endpoint (TD-002 §5)."""

from fastapi import APIRouter, Depends, UploadFile, status
from fastapi import File as FormFile

from upload.dependencies import get_upload_service
from upload.schemas import FileMetadata
from upload.service import UploadService

router = APIRouter(tags=["upload"])


@router.post(
    "/upload",
    response_model=FileMetadata,
    status_code=status.HTTP_200_OK,
    summary="Upload a small file via backend-mediated transfer (size limit enforced by server config)",
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
