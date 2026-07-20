"""Schemas for inbox export, import, and clear operations."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# =============================================================================
# EXPORT SCHEMAS
# =============================================================================


class ExportInitiateRequest(BaseModel):
    confirm_clear: bool = False
    description: str = ""


class ExportInitiateResponse(BaseModel):
    task_id: str
    message: str


class ExportStatusResponse(BaseModel):
    status: str  # queued, running, completed, failed
    progress_message: Optional[str] = None
    messages_exported: Optional[int] = None
    conversations_exported: Optional[int] = None
    attachments_verified: Optional[int] = None
    missing_files_count: Optional[int] = None
    file_path: Optional[str] = None
    total_size_bytes: Optional[int] = None


# =============================================================================
# IMPORT SCHEMAS
# =============================================================================


class ImportResponse(BaseModel):
    task_id: str
    status: str  # queued, running, completed, failed
    message: str


class ExportFileEntry(BaseModel):
    """Single exported attachment reference."""

    filename: str
    mime_type: str
    size_bytes: int
    original_path_hash: str = ""
    sha256: Optional[str] = None


# =============================================================================
# CLEAR SCHEMAS
# =============================================================================


class ClearInitiateRequest(BaseModel):
    confirm_clear: bool = True


class ClearInitiateResponse(BaseModel):
    status: str  # queued, completed
    message: str
