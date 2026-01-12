"""Audit log API routes."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query

from rediska_core.api.deps import CurrentUser, DBSession
from rediska_core.api.schemas.audit import AuditEntryResponse, AuditListResponse
from rediska_core.domain.services.audit import AuditService

router = APIRouter(prefix="/audit", tags=["audit"])


def get_audit_service(db: DBSession) -> AuditService:
    """Get the audit service."""
    return AuditService(db)


AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]


@router.get("", response_model=AuditListResponse)
async def list_audit_entries(
    current_user: CurrentUser,
    audit_service: AuditServiceDep,
    action_type: Optional[str] = Query(None, description="Filter by action type"),
    actor: Optional[str] = Query(None, description="Filter by actor (user, system, agent)"),
    result: Optional[str] = Query(None, description="Filter by result (ok, error)"),
    provider_id: Optional[str] = Query(None, description="Filter by provider ID"),
    identity_id: Optional[int] = Query(None, description="Filter by identity ID"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    limit: int = Query(50, ge=1, le=100, description="Number of entries to return"),
    cursor: Optional[str] = Query(None, description="Cursor for pagination"),
):
    """List audit log entries with optional filtering and pagination.

    Returns audit entries ordered by timestamp (newest first).
    Use cursor-based pagination for large result sets.
    """
    entries, next_cursor = audit_service.list_entries(
        action_type=action_type,
        actor=actor,
        result=result,
        provider_id=provider_id,
        identity_id=identity_id,
        entity_type=entity_type,
        limit=limit,
        cursor=cursor,
    )

    # Get total count (with same filters)
    total = audit_service.count_entries(
        action_type=action_type,
        actor=actor,
        result=result,
        provider_id=provider_id,
        identity_id=identity_id,
        entity_type=entity_type,
    )

    return AuditListResponse(
        entries=[AuditEntryResponse.model_validate(e) for e in entries],
        total=total,
        limit=limit,
        next_cursor=next_cursor,
    )
