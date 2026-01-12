"""Audit log schemas for request/response validation."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class AuditEntryResponse(BaseModel):
    """Response body for an audit entry."""

    id: int
    ts: datetime
    actor: str
    action_type: str
    result: str
    provider_id: Optional[str] = None
    identity_id: Optional[int] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    request_json: Optional[dict[str, Any]] = None
    response_json: Optional[dict[str, Any]] = None
    error_detail: Optional[str] = None

    class Config:
        from_attributes = True


class AuditListResponse(BaseModel):
    """Response body for listing audit entries."""

    entries: list[AuditEntryResponse]
    total: int
    limit: int
    next_cursor: Optional[str] = None
