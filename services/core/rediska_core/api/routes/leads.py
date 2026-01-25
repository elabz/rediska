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
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from rediska_core.api.deps import CurrentUser, get_db
from rediska_core.config import get_settings
from rediska_core.domain.models import AuditLog, Identity, LeadPost
from rediska_core.api.schemas.leads import (
    AnalyzeLeadResponse,
    AuthorInfo,
    LeadResponse,
    ListLeadsResponse,
    SaveLeadRequest,
    UpdateLeadStatusRequest,
)
from rediska_core.domain.models import ExternalAccount, ProfileItem, ProfileSnapshot
from rediska_core.domain.schemas.multi_agent_analysis import (
    MultiAgentAnalysisResponse,
    MultiAgentAnalysisSummary,
)
from rediska_core.domain.services.analysis import AnalysisError, AnalysisService
from rediska_core.domain.services.agent_prompt import AgentPromptService
from rediska_core.domain.services.credentials import CredentialsService
from rediska_core.domain.services.leads import LeadsService, VALID_STATUSES
from rediska_core.domain.services.multi_agent_analysis import (
    MultiAgentAnalysisService,
)
from rediska_core.domain.services.inference import InferenceClient, InferenceConfig
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
    """Get the indexing service with correct Elasticsearch URL.

    Returns None if not configured - will be set up in production.
    """
    try:
        from rediska_core.domain.services.indexing import IndexingService

        settings = get_settings()
        return IndexingService(db=db, es_url=settings.elastic_url)
    except Exception as e:
        logger.error(f"Failed to initialize indexing service: {e}")
        return None


def get_embedding_service(db: Session):
    """Get the embedding service.

    Returns None if not configured - will be set up in production.
    """
    try:
        from rediska_core.domain.services.embedding import EmbeddingService

        settings = get_settings()
        return EmbeddingService(db=db, es_url=settings.elastic_url)
    except Exception as e:
        logger.error(f"Failed to initialize embedding service: {e}")
        return None


def get_leads_service(db: Session = Depends(get_db)) -> LeadsService:
    """Get the leads service."""
    return LeadsService(db=db)


LeadsServiceDep = Annotated[LeadsService, Depends(get_leads_service)]


# =============================================================================
# RESPONSE HELPERS
# =============================================================================


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime has UTC timezone for proper JSON serialization."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Naive datetime from MySQL - assume UTC
        return dt.replace(tzinfo=timezone.utc)
    return dt


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
        lead_source=lead.lead_source,
        post_created_at=_ensure_utc(lead.post_created_at),
        created_at=_ensure_utc(lead.created_at),
        # Analysis fields
        latest_analysis_id=lead.latest_analysis_id,
        analysis_recommendation=lead.analysis_recommendation,
        analysis_confidence=lead.analysis_confidence,
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
    description="List saved leads with optional filters and search.",
)
async def list_leads(
    current_user: CurrentUser,
    leads_service: LeadsServiceDep,
    db: Session = Depends(get_db),
    provider_id: str | None = Query(default=None, description="Filter by provider"),
    source_location: str | None = Query(default=None, description="Filter by source location"),
    status: str | None = Query(default=None, description="Filter by status"),
    lead_source: str | None = Query(default=None, description="Filter by lead source (manual, scout_watch)"),
    search: str | None = Query(default=None, description="Search in title, body, author, subreddit"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Maximum results"),
):
    """List leads with optional filters and search."""
    leads = leads_service.list_leads(
        provider_id=provider_id,
        source_location=source_location,
        status=status,
        lead_source=lead_source,
        search=search,
        offset=offset,
        limit=limit,
    )

    total = leads_service.count_leads(
        provider_id=provider_id,
        source_location=source_location,
        status=status,
        lead_source=lead_source,
        search=search,
    )

    return ListLeadsResponse(
        leads=[build_lead_response(lead, db) for lead in leads],
        total=total,
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


# =============================================================================
# MULTI-AGENT ANALYSIS ENDPOINTS
# =============================================================================


@router.post("/{lead_id}/analyze-multi", response_model=MultiAgentAnalysisResponse)
async def analyze_lead_multi(
    lead_id: int,
    current_user: CurrentUser,
    regenerate_summaries: bool = Query(
        default=False,
        description="If true, regenerate user interest and character summaries even if they exist"
    ),
    db: Session = Depends(get_db),
) -> MultiAgentAnalysisResponse:
    """
    Run multi-agent analysis on a lead.

    Executes all 5 specialized analysis agents in parallel, then synthesizes
    results with a meta-analysis coordinator agent.

    This endpoint:
    1. Validates the lead exists
    2. Ensures profile data has been analyzed
    3. Generates or reuses user summaries (based on regenerate_summaries flag)
    4. Runs dimension agents (demographics, preferences, relationship goals, risk flags, sexual preferences)
    5. Runs meta-analysis coordinator
    6. Returns comprehensive analysis with suitability recommendation

    Manual trigger only (no autosend).

    Args:
        lead_id: ID of lead to analyze
        current_user: Current authenticated user
        regenerate_summaries: If true, regenerate summaries even if they exist
        db: Database session

    Returns:
        MultiAgentAnalysisResponse: Complete analysis results
    """
    # Fetch lead
    lead = db.query(LeadPost).filter(LeadPost.id == lead_id).first()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead not found: {lead_id}",
        )

    if not lead.author_account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lead has no author account",
        )

    try:
        # Check that profile has been analyzed (profile snapshot exists)
        profile_snapshot = (
            db.query(ProfileSnapshot)
            .filter(ProfileSnapshot.account_id == lead.author_account_id)
            .order_by(ProfileSnapshot.fetched_at.desc())
            .first()
        )

        if not profile_snapshot:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Lead's profile has not been analyzed yet. Analyze profile first.",
            )

        # Get inference client from settings
        settings = get_settings()
        if not settings.inference_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="LLM inference service not configured (INFERENCE_URL not set)",
            )

        inference_config = InferenceConfig(
            base_url=settings.inference_url,
            model_name=settings.inference_model or "default",
            timeout=settings.inference_timeout,
            api_key=settings.inference_api_key,
        )
        inference_client = InferenceClient(config=inference_config)

        try:
            # Run multi-agent analysis
            prompt_service = AgentPromptService(db)
            analysis_service = MultiAgentAnalysisService(
                db=db,
                inference_client=inference_client,
                prompt_service=prompt_service,
            )

            analysis = await analysis_service.analyze_lead(
                lead_id,
                regenerate_summaries=regenerate_summaries,
            )
        finally:
            # Ensure HTTP client is properly closed
            await inference_client.close()

        # Audit log
        audit_entry = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="lead.analyze_multi",
            result="ok",
            provider_id=lead.provider_id,
            entity_type="lead_post",
            entity_id=lead_id,
            request_json={"lead_id": lead_id, "regenerate_summaries": regenerate_summaries},
            response_json={
                "analysis_id": analysis.id,
                "recommendation": analysis.final_recommendation,
                "confidence": float(analysis.confidence_score or 0),
            },
        )
        db.add(audit_entry)
        db.commit()

        # Build response
        return MultiAgentAnalysisResponse(
            id=analysis.id,
            lead_id=analysis.lead_id,
            account_id=analysis.account_id,
            status=analysis.status,
            started_at=analysis.started_at.isoformat(),
            completed_at=analysis.completed_at.isoformat()
            if analysis.completed_at
            else None,
            final_recommendation=analysis.final_recommendation,
            recommendation_reasoning=analysis.recommendation_reasoning,
            confidence_score=analysis.confidence_score,
            prompt_versions=analysis.prompt_versions_json,
            meta_analysis=analysis.meta_analysis_json,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Multi-agent analysis failed for lead {lead_id}: {e}")

        # Audit log for error
        audit_entry = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="lead.analyze_multi",
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
            detail=f"Multi-agent analysis failed: {str(e)}",
        )


@router.get("/{lead_id}/analysis", response_model=MultiAgentAnalysisResponse)
async def get_lead_analysis(
    lead_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> MultiAgentAnalysisResponse:
    """
    Get the latest multi-agent analysis for a lead.

    Returns the most recent analysis results if one exists.

    Args:
        lead_id: ID of lead
        current_user: Current authenticated user
        db: Database session

    Returns:
        MultiAgentAnalysisResponse: Latest analysis results

    Raises:
        HTTPException: If lead or analysis not found
    """
    # Fetch lead
    lead = db.query(LeadPost).filter(LeadPost.id == lead_id).first()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead not found: {lead_id}",
        )

    # Get latest analysis
    if not lead.latest_analysis_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No analysis found for this lead",
        )

    from rediska_core.domain.models import LeadAnalysis

    analysis = db.query(LeadAnalysis).filter(
        LeadAnalysis.id == lead.latest_analysis_id
    ).first()

    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found",
        )

    return _build_analysis_response(analysis)


def _build_analysis_response(analysis) -> MultiAgentAnalysisResponse:
    """Build a full MultiAgentAnalysisResponse from a LeadAnalysis model."""
    from rediska_core.domain.schemas.multi_agent_analysis import DimensionAnalysisResult

    def build_dimension_result(
        dimension_name: str,
        dimensions_list: list,
    ) -> DimensionAnalysisResult | None:
        """Build a DimensionAnalysisResult from dimension records."""
        # Find the matching dimension record
        dim_record = next(
            (d for d in dimensions_list if d.dimension == dimension_name),
            None,
        )

        if not dim_record or not dim_record.output_json:
            return None

        return DimensionAnalysisResult(
            dimension=dimension_name,
            status=dim_record.status or "completed",
            output=dim_record.output_json,  # SQLAlchemy JSON type auto-parses
            error=dim_record.error_detail,
            model_info=dim_record.model_info_json,
            started_at=dim_record.started_at.isoformat() if dim_record.started_at else analysis.started_at.isoformat(),
            completed_at=dim_record.completed_at.isoformat() if dim_record.completed_at else None,
        )

    # Get dimension records from the relationship
    dimensions = analysis.dimensions if hasattr(analysis, 'dimensions') else []

    # Get meta_analysis output from dimensions
    meta_dim = next((d for d in dimensions if d.dimension == "meta_analysis"), None)
    meta_output = meta_dim.output_json if meta_dim else None

    return MultiAgentAnalysisResponse(
        id=analysis.id,
        lead_id=analysis.lead_id,
        account_id=analysis.account_id,
        status=analysis.status,
        started_at=analysis.started_at.isoformat(),
        completed_at=analysis.completed_at.isoformat() if analysis.completed_at else None,
        demographics=build_dimension_result("demographics", dimensions),
        preferences=build_dimension_result("preferences", dimensions),
        relationship_goals=build_dimension_result("relationship_goals", dimensions),
        risk_flags=build_dimension_result("risk_flags", dimensions),
        sexual_preferences=build_dimension_result("sexual_preferences", dimensions),
        final_recommendation=analysis.final_recommendation,
        recommendation_reasoning=analysis.recommendation_reasoning,
        confidence_score=analysis.confidence_score,
        prompt_versions=analysis.prompt_versions_json,
        meta_analysis=meta_output,
    )


@router.get("/{lead_id}/analysis/{analysis_id}", response_model=MultiAgentAnalysisResponse)
async def get_lead_analysis_by_id(
    lead_id: int,
    analysis_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> MultiAgentAnalysisResponse:
    """
    Get a specific analysis by ID with full dimension details.

    Returns complete analysis results including all agent outputs.

    Args:
        lead_id: ID of lead
        analysis_id: ID of the specific analysis to retrieve
        current_user: Current authenticated user
        db: Database session

    Returns:
        MultiAgentAnalysisResponse: Full analysis results

    Raises:
        HTTPException: If lead or analysis not found
    """
    # Fetch lead
    lead = db.query(LeadPost).filter(LeadPost.id == lead_id).first()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead not found: {lead_id}",
        )

    from rediska_core.domain.models import LeadAnalysis
    from sqlalchemy.orm import joinedload

    # Get specific analysis with dimensions eagerly loaded
    analysis = db.query(LeadAnalysis).options(
        joinedload(LeadAnalysis.dimensions)
    ).filter(
        LeadAnalysis.id == analysis_id,
        LeadAnalysis.lead_id == lead_id,
    ).first()

    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis not found: {analysis_id}",
        )

    return _build_analysis_response(analysis)


@router.get("/{lead_id}/analysis/history", response_model=list[MultiAgentAnalysisSummary])
async def get_lead_analysis_history(
    lead_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> list[MultiAgentAnalysisSummary]:
    """
    Get all analyses for a lead (for re-analysis tracking).

    Returns all historical analyses for a lead, ordered by most recent first.

    Args:
        lead_id: ID of lead
        current_user: Current authenticated user
        db: Database session

    Returns:
        list[MultiAgentAnalysisSummary]: All analyses for the lead
    """
    # Validate lead exists
    lead = db.query(LeadPost).filter(LeadPost.id == lead_id).first()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead not found: {lead_id}",
        )

    from rediska_core.domain.models import LeadAnalysis

    # Get all analyses
    analyses = (
        db.query(LeadAnalysis)
        .filter(LeadAnalysis.lead_id == lead_id)
        .order_by(LeadAnalysis.created_at.desc())
        .all()
    )

    return [
        MultiAgentAnalysisSummary(
            id=analysis.id,
            lead_id=analysis.lead_id,
            status=analysis.status,
            final_recommendation=analysis.final_recommendation,
            confidence_score=analysis.confidence_score,
            created_at=analysis.created_at.isoformat(),
            completed_at=analysis.completed_at.isoformat()
            if analysis.completed_at
            else None,
        )
        for analysis in analyses
    ]
