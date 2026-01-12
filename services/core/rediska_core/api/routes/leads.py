"""Leads API routes.

Provides endpoints for:
- POST /leads/save - Save a post as a lead
- GET /leads - List leads
- GET /leads/{id} - Get lead by ID
- PATCH /leads/{id}/status - Update lead status
- POST /leads/{id}/analyze - Analyze a lead's author
"""

import json
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from rediska_core.api.deps import CurrentUser, get_db
from rediska_core.config import get_settings
from rediska_core.domain.models import AuditLog, Identity
from rediska_core.api.schemas.leads import (
    AnalyzeLeadResponse,
    AuthorInfo,
    LeadResponse,
    ListLeadsResponse,
    SaveLeadRequest,
    UpdateLeadStatusRequest,
)
from rediska_core.domain.models import ExternalAccount, ProfileItem, ProfileSnapshot
from rediska_core.domain.services.analysis import AnalysisError, AnalysisService
from rediska_core.domain.services.credentials import CredentialsService
from rediska_core.domain.services.leads import LeadsService, VALID_STATUSES
from rediska_core.infrastructure.crypto import CryptoService
from rediska_core.providers.base import ProviderAdapter
from rediska_core.providers.reddit.adapter import RedditAdapter

router = APIRouter(prefix="/leads", tags=["leads"])
logger = logging.getLogger(__name__)


# =============================================================================
# PROVIDER AND SERVICE FACTORIES
# =============================================================================


def get_reddit_adapter(db: Session) -> Optional[RedditAdapter]:
    """Create a Reddit adapter with credentials from the default identity.

    Dynamically creates the adapter with OAuth credentials,
    similar to how sources.py handles it.
    """
    settings = get_settings()

    if not settings.encryption_key:
        logger.error("Encryption key not configured")
        return None

    # Get active identity
    identity = db.query(Identity).filter_by(is_active=True).first()
    if not identity:
        logger.error("No active identity found")
        return None

    # Get credentials
    crypto = CryptoService(settings.encryption_key)
    credentials_service = CredentialsService(db=db, crypto=crypto)
    credential = credentials_service.get_credential_decrypted(
        provider_id="reddit",
        identity_id=identity.id,
        credential_type="oauth_tokens",
    )

    if not credential:
        logger.error(f"No Reddit credentials found for identity {identity.id}")
        return None

    try:
        tokens = json.loads(credential)

        # Create token refresh callback
        def on_token_refresh(new_access_token: str) -> None:
            tokens["access_token"] = new_access_token
            credentials_service.store_credential(
                provider_id="reddit",
                identity_id=identity.id,
                credential_type="oauth_tokens",
                secret=json.dumps(tokens),
            )

        return RedditAdapter(
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            client_id=settings.provider_reddit_client_id,
            client_secret=settings.provider_reddit_client_secret,
            user_agent=settings.provider_reddit_user_agent,
            on_token_refresh=on_token_refresh,
        )
    except Exception as e:
        logger.error(f"Failed to create Reddit adapter: {e}")
        return None


def get_provider_adapter(provider_id: str, db: Session) -> Optional[ProviderAdapter]:
    """Get a provider adapter for the given provider."""
    if provider_id == "reddit":
        return get_reddit_adapter(db)
    return None


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
# RESPONSE HELPERS
# =============================================================================


def build_lead_response(lead, db: Session) -> LeadResponse:
    """Build a LeadResponse with author info if available.

    Fetches the author's ExternalAccount and ProfileSnapshot to
    provide detailed author information in the response.
    """
    from datetime import datetime

    # Get author account if linked
    author_info = None
    author_username = None

    if lead.author_account_id:
        account = db.query(ExternalAccount).filter(
            ExternalAccount.id == lead.author_account_id
        ).first()

        if account:
            author_username = account.external_username

            # Get latest profile snapshot for signals
            snapshot = db.query(ProfileSnapshot).filter(
                ProfileSnapshot.account_id == account.id
            ).order_by(ProfileSnapshot.fetched_at.desc()).first()

            # Count profile items
            post_count = db.query(ProfileItem).filter(
                ProfileItem.account_id == account.id,
                ProfileItem.item_type == "post",
            ).count()
            comment_count = db.query(ProfileItem).filter(
                ProfileItem.account_id == account.id,
                ProfileItem.item_type == "comment",
            ).count()

            # Parse signals from snapshot
            signals: dict = snapshot.signals_json if snapshot and snapshot.signals_json else {}
            account_created_at = None
            created_at_str = signals.get("created_at")
            if created_at_str:
                try:
                    account_created_at = datetime.fromisoformat(
                        str(created_at_str).replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError):
                    pass

            author_info = AuthorInfo(
                username=account.external_username,
                account_created_at=account_created_at,
                karma=signals.get("karma"),
                post_count=post_count if post_count > 0 else None,
                comment_count=comment_count if comment_count > 0 else None,
                analysis_state=account.analysis_state,
                bio=signals.get("bio"),
                is_verified=signals.get("is_verified"),
                is_suspended=signals.get("is_suspended"),
            )

    return LeadResponse(
        id=lead.id,
        provider_id=lead.provider_id,
        source_location=lead.source_location,
        external_post_id=lead.external_post_id,
        post_url=lead.post_url,
        title=lead.title,
        body_text=lead.body_text,
        author_account_id=lead.author_account_id,
        author_username=author_username,
        author_info=author_info,
        status=lead.status,
        score=None,  # TODO: Add lead scoring
        post_created_at=lead.post_created_at,
        created_at=lead.created_at,
    )


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
    db: Session = Depends(get_db),
):
    """Save a post as a lead.

    Creates a new lead_posts row or updates an existing one
    if the external_post_id already exists.
    """
    from datetime import datetime, timezone

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

    # Audit log for lead save
    audit_entry = AuditLog(
        ts=datetime.now(timezone.utc),
        actor="user",
        action_type="lead.save",
        result="ok",
        provider_id=request.provider_id,
        entity_type="lead_post",
        entity_id=lead.id,
        request_json={
            "source_location": request.source_location,
            "external_post_id": request.external_post_id,
            "author_username": request.author_username,
        },
    )
    db.add(audit_entry)
    db.commit()

    return build_lead_response(lead, db)


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
    db: Session = Depends(get_db),
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
        leads=[build_lead_response(lead, db) for lead in leads],
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
    db: Session = Depends(get_db),
):
    """Get a lead by ID."""
    lead = leads_service.get_lead(lead_id)

    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead {lead_id} not found",
        )

    return build_lead_response(lead, db)


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
    db: Session = Depends(get_db),
):
    """Update a lead's status."""
    from datetime import datetime, timezone

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

    # Audit log for status update
    audit_entry = AuditLog(
        ts=datetime.now(timezone.utc),
        actor="user",
        action_type="lead.status_update",
        result="ok",
        provider_id=lead.provider_id,
        entity_type="lead_post",
        entity_id=lead_id,
        request_json={"new_status": request.status},
    )
    db.add(audit_entry)
    db.commit()

    return build_lead_response(lead, db)


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
    from datetime import datetime, timezone

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
    provider_adapter = get_provider_adapter(lead.provider_id, db)
    if not provider_adapter:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Provider adapter not available. Check that credentials are configured.",
        )
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

        # Audit log for successful analysis
        audit_entry = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="lead.analyze",
            result="ok" if result.success else "error",
            provider_id=lead.provider_id,
            entity_type="lead_post",
            entity_id=lead_id,
            request_json={"author_account_id": lead.author_account_id},
            response_json={
                "profile_snapshot_id": result.profile_snapshot_id,
                "profile_items_count": result.profile_items_count,
                "indexed_count": result.indexed_count,
                "embedded_count": result.embedded_count,
            },
            error_detail=result.error if not result.success else None,
        )
        db.add(audit_entry)
        db.commit()

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

        # Audit log for failed analysis
        audit_entry = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="lead.analyze",
            result="error",
            provider_id=lead.provider_id,
            entity_type="lead_post",
            entity_id=lead_id,
            error_detail=error_msg,
        )
        db.add(audit_entry)
        db.commit()

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
        # Audit log for unexpected failure
        audit_entry = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="lead.analyze",
            result="error",
            provider_id=lead.provider_id,
            entity_type="lead_post",
            entity_id=lead_id,
            error_detail=str(e),
        )
        db.add(audit_entry)
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis failed: {e}",
        )
