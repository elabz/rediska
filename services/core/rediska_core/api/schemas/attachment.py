"""Attachment API schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from rediska_core.domain.models import Attachment


class AttachmentResponse(BaseModel):
    """Response schema for attachment details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sha256: str
    storage_key: str
    mime_type: str
    size_bytes: int
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    remote_visibility: str
    created_at: datetime

    @classmethod
    def from_model(cls, attachment: Attachment) -> "AttachmentResponse":
        """Create response from Attachment model."""
        return cls(
            id=attachment.id,
            sha256=attachment.sha256,
            storage_key=attachment.storage_key,
            mime_type=attachment.mime_type,
            size_bytes=attachment.size_bytes,
            width_px=attachment.width_px,
            height_px=attachment.height_px,
            remote_visibility=attachment.remote_visibility,
            created_at=attachment.created_at,
        )


class AttachmentUploadResponse(BaseModel):
    """Response schema for successful upload."""

    id: int
    sha256: str
    mime_type: str
    size_bytes: int
    width_px: Optional[int] = None
    height_px: Optional[int] = None

    @classmethod
    def from_upload_result(cls, result) -> "AttachmentUploadResponse":
        """Create response from AttachmentUploadResult."""
        return cls(
            id=result.attachment_id,
            sha256=result.sha256,
            mime_type=result.mime_type,
            size_bytes=result.size_bytes,
            width_px=result.width_px,
            height_px=result.height_px,
        )


class AttachmentMetaResponse(BaseModel):
    """Response schema for attachment metadata."""

    id: int
    sha256: str
    mime_type: str
    size_bytes: int
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    created_at: datetime

    @classmethod
    def from_model(cls, attachment: Attachment) -> "AttachmentMetaResponse":
        """Create response from Attachment model."""
        return cls(
            id=attachment.id,
            sha256=attachment.sha256,
            mime_type=attachment.mime_type,
            size_bytes=attachment.size_bytes,
            width_px=attachment.width_px,
            height_px=attachment.height_px,
            created_at=attachment.created_at,
        )
