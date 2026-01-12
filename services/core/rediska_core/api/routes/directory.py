"""Directory API routes.

Provides endpoints for:
- GET /directories/analyzed - List analyzed accounts
- GET /directories/contacted - List contacted accounts
- GET /directories/engaged - List engaged accounts
- GET /directories/counts - Get counts for all directories
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from rediska_core.api.deps import CurrentUser, get_db
from rediska_core.api.schemas.directory import (
    DirectoryCountsResponse,
    DirectoryEntryResponse,
    DirectoryListResponse,
)
from rediska_core.domain.services.directory import DirectoryService

router = APIRouter(prefix="/directories", tags=["directories"])


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_directory_service(db: Session = Depends(get_db)) -> DirectoryService:
    """Get the directory service."""
    return DirectoryService(db=db)


def _entry_to_response(entry) -> DirectoryEntryResponse:
    """Convert a DirectoryEntry to a DirectoryEntryResponse."""
    return DirectoryEntryResponse(
        id=entry.id,
        provider_id=entry.provider_id,
        external_username=entry.external_username,
        external_user_id=entry.external_user_id,
        remote_status=entry.remote_status,
        analysis_state=entry.analysis_state,
        contact_state=entry.contact_state,
        engagement_state=entry.engagement_state,
        first_analyzed_at=entry.first_analyzed_at,
        first_contacted_at=entry.first_contacted_at,
        first_inbound_after_contact_at=entry.first_inbound_after_contact_at,
        created_at=entry.created_at,
        latest_summary=entry.latest_summary,
        lead_count=entry.lead_count,
    )


# =============================================================================
# ANALYZED DIRECTORY
# =============================================================================


@router.get(
    "/analyzed",
    response_model=DirectoryListResponse,
    summary="List analyzed accounts",
    description="List accounts that have been analyzed, with optional filtering.",
)
async def list_analyzed(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    provider_id: Optional[str] = Query(default=None, description="Filter by provider"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Maximum results"),
):
    """List analyzed accounts."""
    service = DirectoryService(db=db)

    entries = service.list_analyzed(
        provider_id=provider_id,
        limit=limit,
        offset=offset,
    )
    total = service.count_analyzed(provider_id=provider_id)

    return DirectoryListResponse(
        entries=[_entry_to_response(e) for e in entries],
        total=total,
        directory_type="analyzed",
    )


# =============================================================================
# CONTACTED DIRECTORY
# =============================================================================


@router.get(
    "/contacted",
    response_model=DirectoryListResponse,
    summary="List contacted accounts",
    description="List accounts that have been contacted, with optional filtering.",
)
async def list_contacted(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    provider_id: Optional[str] = Query(default=None, description="Filter by provider"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Maximum results"),
):
    """List contacted accounts."""
    service = DirectoryService(db=db)

    entries = service.list_contacted(
        provider_id=provider_id,
        limit=limit,
        offset=offset,
    )
    total = service.count_contacted(provider_id=provider_id)

    return DirectoryListResponse(
        entries=[_entry_to_response(e) for e in entries],
        total=total,
        directory_type="contacted",
    )


# =============================================================================
# ENGAGED DIRECTORY
# =============================================================================


@router.get(
    "/engaged",
    response_model=DirectoryListResponse,
    summary="List engaged accounts",
    description="List accounts that have engaged (responded after contact).",
)
async def list_engaged(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    provider_id: Optional[str] = Query(default=None, description="Filter by provider"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Maximum results"),
):
    """List engaged accounts."""
    service = DirectoryService(db=db)

    entries = service.list_engaged(
        provider_id=provider_id,
        limit=limit,
        offset=offset,
    )
    total = service.count_engaged(provider_id=provider_id)

    return DirectoryListResponse(
        entries=[_entry_to_response(e) for e in entries],
        total=total,
        directory_type="engaged",
    )


# =============================================================================
# COUNTS
# =============================================================================


@router.get(
    "/counts",
    response_model=DirectoryCountsResponse,
    summary="Get directory counts",
    description="Get counts for all directory types.",
)
async def get_counts(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    provider_id: Optional[str] = Query(default=None, description="Filter by provider"),
):
    """Get counts for all directories."""
    service = DirectoryService(db=db)

    return DirectoryCountsResponse(
        analyzed=service.count_analyzed(provider_id=provider_id),
        contacted=service.count_contacted(provider_id=provider_id),
        engaged=service.count_engaged(provider_id=provider_id),
    )
