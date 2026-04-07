"""Conversation list API schemas."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class ConversationListCreate(BaseModel):
    """Request to create a conversation list."""
    name: str = Field(..., min_length=1, max_length=128)


class ConversationListUpdate(BaseModel):
    """Request to update a conversation list."""
    name: str = Field(..., min_length=1, max_length=128)


class ConversationListResponse(BaseModel):
    """Response for a conversation list."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    conversation_count: int = 0
    created_at: datetime
    updated_at: datetime


class ConversationListsResponse(BaseModel):
    """Response for list of conversation lists."""
    lists: list[ConversationListResponse]
