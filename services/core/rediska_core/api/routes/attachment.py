"""Attachment management API routes.

Provides endpoints for:
- POST /attachments/upload - Upload a new attachment (multipart)
- GET /attachments/{id} - Download attachment content (streaming)
- GET /attachments/{id}/meta - Get attachment metadata
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response

from rediska_core.api.deps import CurrentUser, DBSession
from rediska_core.domain.models import AuditLog
from rediska_core.api.schemas.attachment import (
    AttachmentMetaResponse,
    AttachmentUploadResponse,
)
from rediska_core.config import get_settings
from rediska_core.domain.services.attachment import (
    AttachmentService,
    FileTooLargeError,
    InvalidMimeTypeError,
)

router = APIRouter(prefix="/attachments", tags=["attachments"])


def get_attachment_service(db: DBSession) -> AttachmentService:
    """Get the attachment service with configured storage path."""
    settings = get_settings()
    return AttachmentService(
        db=db,
        storage_path=settings.attachments_path,
    )


AttachmentServiceDep = Annotated[AttachmentService, Depends(get_attachment_service)]


@router.post(
    "/upload",
    response_model=AttachmentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an attachment",
    description="Upload a file as an attachment. Maximum size is 10MB. "
                "Supported formats include images, PDFs, text files, and common documents.",
)
async def upload_attachment(
    current_user: CurrentUser,
    attachment_service: AttachmentServiceDep,
    db: DBSession,
    file: UploadFile = File(..., description="File to upload"),
):
    """Upload a new attachment.

    The file will be validated for:
    - Size (max 10MB)
    - MIME type (must be in allowlist)

    For images, dimensions will be extracted automatically.

    Returns attachment details including ID and SHA256 hash.
    """
    from datetime import datetime, timezone

    # Read file content
    content = await file.read()

    # Validate content type
    content_type = file.content_type or "application/octet-stream"

    try:
        result = attachment_service.upload(
            file_data=content,
            filename=file.filename or "upload",
            content_type=content_type,
        )

        # Audit log for successful upload
        audit_entry = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="attachment.upload",
            result="ok",
            entity_type="attachment",
            entity_id=result.attachment_id,
            request_json={
                "filename": file.filename,
                "content_type": content_type,
                "size_bytes": len(content),
            },
            response_json={
                "attachment_id": result.attachment_id,
                "sha256": result.sha256,
            },
        )
        db.add(audit_entry)
        db.commit()

        return AttachmentUploadResponse.from_upload_result(result)

    except FileTooLargeError as e:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(e),
        )

    except InvalidMimeTypeError as e:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(e),
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/{attachment_id}",
    response_class=Response,
    summary="Download attachment",
    description="Download the attachment content. Streams the file with appropriate "
                "Content-Type and Content-Disposition headers.",
)
async def download_attachment(
    attachment_id: int,
    current_user: CurrentUser,
    attachment_service: AttachmentServiceDep,
):
    """Download an attachment by ID.

    Returns the file content with:
    - Correct Content-Type header
    - Content-Disposition header for inline viewing
    - Content-Length header
    """
    attachment = attachment_service.get_by_id(attachment_id)

    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attachment {attachment_id} not found",
        )

    file_path = attachment_service.get_file_path(attachment_id)

    if not file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attachment file not found on disk",
        )

    # Use FileResponse for efficient streaming
    return FileResponse(
        path=file_path,
        media_type=attachment.mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{attachment.storage_key.split("/")[-1]}"',
        },
    )


@router.get(
    "/{attachment_id}/meta",
    response_model=AttachmentMetaResponse,
    summary="Get attachment metadata",
    description="Get attachment metadata without downloading the content.",
)
async def get_attachment_metadata(
    attachment_id: int,
    current_user: CurrentUser,
    attachment_service: AttachmentServiceDep,
):
    """Get attachment metadata by ID.

    Returns attachment details including:
    - ID, SHA256 hash
    - MIME type, size
    - Dimensions (for images)
    - Created timestamp
    """
    attachment = attachment_service.get_by_id(attachment_id)

    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attachment {attachment_id} not found",
        )

    return AttachmentMetaResponse.from_model(attachment)
