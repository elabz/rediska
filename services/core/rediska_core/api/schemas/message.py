"""Message API schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SendMessageRequest(BaseModel):
    """Request schema for sending a message."""

    body_text: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="The message body text",
    )
    attachment_ids: Optional[list[int]] = Field(
        default=None,
        description="Optional list of attachment IDs to include",
    )


class SendMessageResponse(BaseModel):
    """Response schema for a queued message send."""

    job_id: int = Field(..., description="ID of the send job")
    message_id: int = Field(..., description="ID of the created message")
    status: str = Field(..., description="Status of the job (queued)")


class MessageResponse(BaseModel):
    """Response schema for a message."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    identity_id: Optional[int] = None
    direction: str
    body_text: Optional[str] = None
    sent_at: datetime
    remote_visibility: str
    external_message_id: Optional[str] = None
    created_at: datetime


class PendingMessageResponse(BaseModel):
    """Response schema for a pending (unsent) message."""

    id: int
    conversation_id: int
    body_text: Optional[str] = None
    sent_at: datetime
    remote_visibility: str = "unknown"
    can_retry: bool = True


class SyncMessagesResponse(BaseModel):
    """Response schema for message sync operation."""

    conversations_synced: int = Field(..., description="Number of conversations processed")
    messages_synced: int = Field(..., description="Number of messages processed")
    new_conversations: int = Field(..., description="Number of new conversations created")
    new_messages: int = Field(..., description="Number of new messages created")
    errors: list[str] = Field(default_factory=list, description="Any errors encountered")


class SyncJobResponse(BaseModel):
    """Response schema for triggering a sync job."""

    job_id: str = Field(..., description="Celery task ID for tracking the job")
    status: str = Field(..., description="Initial job status (queued)")
    message: str = Field(..., description="Human-readable status message")


class SyncJobStatusResponse(BaseModel):
    """Response schema for checking sync job status."""

    job_id: str = Field(..., description="Celery task ID")
    status: str = Field(..., description="Job status (pending, success, failure)")
    result: Optional[dict] = Field(None, description="Job result if completed")


class DeleteMessageResponse(BaseModel):
    """Response schema for message deletion."""

    message: str = Field(..., description="Success message")
    message_id: int = Field(..., description="ID of deleted message")
    job_cancelled: bool = Field(..., description="Whether associated job was cancelled")
