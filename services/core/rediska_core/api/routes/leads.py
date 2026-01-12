"""Leads API routes.

Provides endpoints for:
- POST /leads/save - Save a post as a lead
- GET /leads - List leads
- GET /leads/{id} - Get lead by ID
- PATCH /leads/{id}/status - Update lead status
- POST /leads/{id}/analyze - Analyze a lead's author
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from rediska_core.api.deps import CurrentUser, get_db
from rediska_core.api.schemas.leads import (
    AnalyzeLeadResponse,
    LeadResponse,
    ListLeadsResponse,
    SaveLeadRequest,
    UpdateLeadStatusRequest,
)
from rediska_core.domain.services.analysis import AnalysisError, AnalysisService
from rediska_core.domain.services.leads import LeadsService, VALID_STATUSES
from rediska_core.providers.base import ProviderAdapter

router = APIRouter(prefix="/leads", tags=["leads"])


# =============================================================================
# PROVIDER AND SERVICE FACTORIES
# =============================================================================


# Global provider adapter registry (can be overridden in tests)
_provider_adapters: dict[str, ProviderAdapter] = {}


def register_provider_adapter(provider_id: str, adapter: ProviderAdapter) -> None:
    """Register a provider adapter for a given provider."""
    _provider_adapters[provider_id] = adapter


def get_provider_adapter(provider_id: str) -> Optional[ProviderAdapter]:
    """Get a provider adapter for the given provider."""
    return _provider_adapters.get(provider_id)


def get_indexing_service(db: Session):
    """Get the indexing service.

    Returns None if not configured - will be set up in production.
    """
    try:
        from rediska_core.domain.services.indexing import IndexingService

        return IndexingService(db=db)
    except Exception:
        return None


def get_embedding_service(db: Session):
    """Get the embedding service.

    Returns None if not configured - will be set up in production.
    """
    try:
        from rediska_core.domain.services.embedding import EmbeddingService

        return EmbeddingService(db=db)
    except Exception:
        return None


def get_leads_service(db: Session = Depends(get_db)) -> LeadsService:
    """Get the leads service."""
    return LeadsService(db=db)


LeadsServiceDep = Annotated[LeadsService, Depends(get_leads_service)]


# =============================================================================
# SAVE LEAD
# =============================================================================


@router.post(
    "/save",
    response_model=LeadResponse,
    summary="Save post as lead",
    description="Save a post from a provider location as a lead. "
                "Creates a new lead or updates an existing one if the post was previously saved.",
)
async def save_lead(
    request: SaveLeadRequest,
    current_user: CurrentUser,
    leads_service: LeadsServiceDep,
):
    """Save a post as a lead.

    Creates a new lead_posts row or updates an existing one
    if the external_post_id already exists.
    """
    lead = leads_service.save_lead(
        provider_id=request.provider_id,
        source_location=request.source_location,
        external_post_id=request.external_post_id,
        post_url=request.post_url,
        title=request.title,
        body_text=request.body_text,
        author_username=request.author_username,
        author_external_id=request.author_external_id,
        post_created_at=request.post_created_at,
    )

    return LeadResponse.model_validate(lead)


# =============================================================================
# LIST LEADS
# =============================================================================


@router.get(
    "",
    response_model=ListLeadsResponse,
    summary="List leads",
    description="List saved leads with optional filters.",
)
async def list_leads(
    current_user: CurrentUser,
    leads_service: LeadsServiceDep,
    provider_id: str | None = Query(default=None, description="Filter by provider"),
    source_location: str | None = Query(default=None, description="Filter by source location"),
    status: str | None = Query(default=None, description="Filter by status"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Maximum results"),
):
    """List leads with optional filters."""
    leads = leads_service.list_leads(
        provider_id=provider_id,
        source_location=source_location,
        status=status,
        offset=offset,
        limit=limit,
    )

    return ListLeadsResponse(
        leads=[LeadResponse.model_validate(lead) for lead in leads],
        total=len(leads),  # TODO: Add proper count query for pagination
    )


# =============================================================================
# GET LEAD
# =============================================================================


@router.get(
    "/{lead_id}",
    response_model=LeadResponse,
    summary="Get lead by ID",
    description="Get a lead by its ID.",
)
async def get_lead(
    lead_id: int,
    current_user: CurrentUser,
    leads_service: LeadsServiceDep,
):
    """Get a lead by ID."""
    lead = leads_service.get_lead(lead_id)

    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead {lead_id} not found",
        )

    return LeadResponse.model_validate(lead)


# =============================================================================
# UPDATE STATUS
# =============================================================================


@router.patch(
    "/{lead_id}/status",
    response_model=LeadResponse,
    summary="Update lead status",
    description="Update the status of a lead.",
)
async def update_lead_status(
    lead_id: int,
    request: UpdateLeadStatusRequest,
    current_user: CurrentUser,
    leads_service: LeadsServiceDep,
):
    """Update a lead's status."""
    # Validate status
    if request.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status: {request.status}. Must be one of {VALID_STATUSES}",
        )

    lead = leads_service.update_status(lead_id, request.status)

    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead {lead_id} not found",
        )

    return LeadResponse.model_validate(lead)


# =============================================================================
# ANALYZE LEAD
# =============================================================================


@router.post(
    "/{lead_id}/analyze",
    response_model=AnalyzeLeadResponse,
    summary="Analyze lead author",
    description="Analyze a lead's author profile. Fetches profile and content "
    "from the provider, stores profile data, indexes content, and generates embeddings.",
)
async def analyze_lead(
    lead_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """Analyze a lead's author.

    Fetches the author's profile and content from the provider,
    stores profile data locally, indexes for search, and generates embeddings.
    """
    # Get the lead to determine provider
    leads_service = LeadsService(db=db)
    lead = leads_service.get_lead(lead_id)

    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead {lead_id} not found",
        )

    if not lead.author_account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lead has no author - cannot analyze",
        )

    # Get services
    provider_adapter = get_provider_adapter(lead.provider_id)
    indexing_service = get_indexing_service(db)
    embedding_service = get_embedding_service(db)

    # Create analysis service and run
    analysis_service = AnalysisService(
        db=db,
        provider_adapter=provider_adapter,
        indexing_service=indexing_service,
        embedding_service=embedding_service,
    )

    try:
        result = await analysis_service.analyze_lead(lead_id)

        return AnalyzeLeadResponse(
            lead_id=result.lead_id,
            account_id=result.account_id,
            profile_snapshot_id=result.profile_snapshot_id,
            profile_items_count=result.profile_items_count,
            indexed_count=result.indexed_count,
            embedded_count=result.embedded_count,
            success=result.success,
            error=result.error,
        )

    except AnalysisError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg,
            )
        if "no author" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_msg,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis failed: {e}",
        )
