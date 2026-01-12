"""Conversation API schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AttachmentInMessageResponse(BaseModel):
    """Response schema for an attachment in a message."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    mime_type: str
    size_bytes: int
    width_px: Optional[int] = None
    height_px: Optional[int] = None


class CounterpartResponse(BaseModel):
    """Response schema for a conversation counterpart."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    external_username: str
    external_user_id: Optional[str] = None
    remote_status: str = "unknown"


class ConversationSummaryResponse(BaseModel):
    """Response schema for a conversation in a list."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_id: str
    identity_id: int
    external_conversation_id: str
    counterpart: CounterpartResponse
    last_activity_at: Optional[datetime] = None
    last_message_preview: Optional[str] = None
    unread_count: int = 0
    archived_at: Optional[datetime] = None
    created_at: datetime


class ConversationDetailResponse(BaseModel):
    """Response schema for a single conversation."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_id: str
    identity_id: int
    external_conversation_id: str
    counterpart: CounterpartResponse
    last_activity_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    """Paginated response for conversation list."""

    conversations: list[ConversationSummaryResponse]
    next_cursor: Optional[str] = Field(
        None,
        description="Cursor for the next page (base64 encoded). None if no more pages.",
    )
    has_more: bool = False


class MessageInConversationResponse(BaseModel):
    """Response schema for a message in a conversation."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    direction: str  # "in", "out", "system"
    body_text: Optional[str] = None
    sent_at: datetime
    remote_visibility: str = "visible"
    identity_id: Optional[int] = None
    created_at: datetime
    attachments: list[AttachmentInMessageResponse] = Field(default_factory=list)


class MessageListResponse(BaseModel):
    """Paginated response for message list."""

    messages: list[MessageInConversationResponse]
    next_cursor: Optional[str] = Field(
        None,
        description="Cursor for the next page (base64 encoded). None if no more pages.",
    )
    has_more: bool = False
