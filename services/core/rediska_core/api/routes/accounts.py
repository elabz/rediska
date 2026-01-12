"""Accounts API routes.

Provides endpoints for:
- GET /accounts/{id} - Get account details
- GET /accounts/{id}/profile-items - Get account's posts/comments/images
- GET /accounts/{id}/snapshots - Get profile snapshots history
- GET /accounts/{id}/conversations - Get conversations with this account
- POST /accounts/{id}/analyze - Trigger re-analysis
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from rediska_core.api.deps import CurrentUser, get_db, DBSession
from rediska_core.domain.models import (
    AuditLog,
    Conversation,
    ExternalAccount,
    Message,
    ProfileItem,
    ProfileSnapshot,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])


# =============================================================================
# Schemas
# =============================================================================


class ProfileSnapshotResponse(BaseModel):
    """Profile snapshot response."""

    id: int
    fetched_at: datetime
    summary_text: Optional[str] = None
    signals_json: Optional[dict] = None
    risk_flags_json: Optional[dict] = None
    model_info_json: Optional[dict] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AccountDetailResponse(BaseModel):
    """Account detail response."""

    id: int
    provider_id: str
    external_username: str
    external_user_id: Optional[str] = None
    remote_status: str
    analysis_state: str
    contact_state: str
    engagement_state: str
    first_analyzed_at: Optional[datetime] = None
    first_contacted_at: Optional[datetime] = None
    first_inbound_after_contact_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    latest_snapshot: Optional[ProfileSnapshotResponse] = None

    class Config:
        from_attributes = True


class ProfileItemResponse(BaseModel):
    """Profile item response."""

    id: int
    item_type: str
    external_item_id: str
    item_created_at: Optional[datetime] = None
    text_content: Optional[str] = None
    attachment_id: Optional[int] = None
    remote_visibility: str
    created_at: datetime

    class Config:
        from_attributes = True


class ProfileItemsListResponse(BaseModel):
    """Profile items list response."""

    items: list[ProfileItemResponse]
    total: int
    item_type: Optional[str] = None


class SnapshotsListResponse(BaseModel):
    """Snapshots list response."""

    snapshots: list[ProfileSnapshotResponse]
    total: int


class ConversationSummaryResponse(BaseModel):
    """Conversation summary for profile page."""

    id: int
    identity_id: int
    last_activity_at: Optional[datetime] = None
    message_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationsListResponse(BaseModel):
    """Conversations list response."""

    conversations: list[ConversationSummaryResponse]
    total: int


class AnalyzeResponse(BaseModel):
    """Analyze trigger response."""

    status: str
    message: str
    job_id: Optional[str] = None


# =============================================================================
# Routes
# =============================================================================


@router.get(
    "/{account_id}",
    response_model=AccountDetailResponse,
    summary="Get account details",
    description="Get detailed information about an external account including latest snapshot.",
)
async def get_account(
    account_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """Get account by ID with latest profile snapshot."""
    account = (
        db.query(ExternalAccount)
        .filter(
            ExternalAccount.id == account_id,
            ExternalAccount.deleted_at.is_(None),
        )
        .first()
    )

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    # Get latest snapshot
    latest_snapshot = (
        db.query(ProfileSnapshot)
        .filter(ProfileSnapshot.account_id == account_id)
        .order_by(desc(ProfileSnapshot.fetched_at))
        .first()
    )

    snapshot_response = None
    if latest_snapshot:
        snapshot_response = ProfileSnapshotResponse(
            id=latest_snapshot.id,
            fetched_at=latest_snapshot.fetched_at,
            summary_text=latest_snapshot.summary_text,
            signals_json=latest_snapshot.signals_json,
            risk_flags_json=latest_snapshot.risk_flags_json,
            model_info_json=latest_snapshot.model_info_json,
            created_at=latest_snapshot.created_at,
        )

    return AccountDetailResponse(
        id=account.id,
        provider_id=account.provider_id,
        external_username=account.external_username,
        external_user_id=account.external_user_id,
        remote_status=account.remote_status,
        analysis_state=account.analysis_state,
        contact_state=account.contact_state,
        engagement_state=account.engagement_state,
        first_analyzed_at=account.first_analyzed_at,
        first_contacted_at=account.first_contacted_at,
        first_inbound_after_contact_at=account.first_inbound_after_contact_at,
        created_at=account.created_at,
        updated_at=account.updated_at,
        latest_snapshot=snapshot_response,
    )


@router.get(
    "/{account_id}/profile-items",
    response_model=ProfileItemsListResponse,
    summary="Get profile items",
    description="Get posts, comments, or images for an account.",
)
async def get_profile_items(
    account_id: int,
    current_user: CurrentUser,
    db: DBSession,
    item_type: Optional[str] = Query(None, description="Filter by type: post, comment, image"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
):
    """Get profile items for an account."""
    # Verify account exists
    account = db.query(ExternalAccount).filter_by(id=account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    # Build query
    query = db.query(ProfileItem).filter(
        ProfileItem.account_id == account_id,
        ProfileItem.deleted_at.is_(None),
    )

    if item_type:
        query = query.filter(ProfileItem.item_type == item_type)

    # Get total
    total = query.count()

    # Get items
    items = (
        query.order_by(desc(ProfileItem.item_created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )

    return ProfileItemsListResponse(
        items=[
            ProfileItemResponse(
                id=item.id,
                item_type=item.item_type,
                external_item_id=item.external_item_id,
                item_created_at=item.item_created_at,
                text_content=item.text_content,
                attachment_id=item.attachment_id,
                remote_visibility=item.remote_visibility,
                created_at=item.created_at,
            )
            for item in items
        ],
        total=total,
        item_type=item_type,
    )


@router.get(
    "/{account_id}/snapshots",
    response_model=SnapshotsListResponse,
    summary="Get profile snapshots",
    description="Get all profile snapshots for an account (analysis history).",
)
async def get_snapshots(
    account_id: int,
    current_user: CurrentUser,
    db: DBSession,
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
):
    """Get profile snapshots for an account."""
    # Verify account exists
    account = db.query(ExternalAccount).filter_by(id=account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    # Get total
    total = db.query(ProfileSnapshot).filter_by(account_id=account_id).count()

    # Get snapshots
    snapshots = (
        db.query(ProfileSnapshot)
        .filter_by(account_id=account_id)
        .order_by(desc(ProfileSnapshot.fetched_at))
        .offset(offset)
        .limit(limit)
        .all()
    )

    return SnapshotsListResponse(
        snapshots=[
            ProfileSnapshotResponse(
                id=snap.id,
                fetched_at=snap.fetched_at,
                summary_text=snap.summary_text,
                signals_json=snap.signals_json,
                risk_flags_json=snap.risk_flags_json,
                model_info_json=snap.model_info_json,
                created_at=snap.created_at,
            )
            for snap in snapshots
        ],
        total=total,
    )


@router.get(
    "/{account_id}/conversations",
    response_model=ConversationsListResponse,
    summary="Get conversations with account",
    description="Get all conversations with this external account.",
)
async def get_conversations(
    account_id: int,
    current_user: CurrentUser,
    db: DBSession,
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
):
    """Get conversations with an account."""
    # Verify account exists
    account = db.query(ExternalAccount).filter_by(id=account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    # Get total
    total = (
        db.query(Conversation)
        .filter(
            Conversation.counterpart_account_id == account_id,
            Conversation.deleted_at.is_(None),
        )
        .count()
    )

    # Get conversations
    conversations = (
        db.query(Conversation)
        .filter(
            Conversation.counterpart_account_id == account_id,
            Conversation.deleted_at.is_(None),
        )
        .order_by(desc(Conversation.last_activity_at))
        .offset(offset)
        .limit(limit)
        .all()
    )

    result = []
    for conv in conversations:
        # Get message count
        msg_count = (
            db.query(Message)
            .filter(
                Message.conversation_id == conv.id,
                Message.deleted_at.is_(None),
            )
            .count()
        )

        result.append(
            ConversationSummaryResponse(
                id=conv.id,
                identity_id=conv.identity_id,
                last_activity_at=conv.last_activity_at,
                message_count=msg_count,
                created_at=conv.created_at,
            )
        )

    return ConversationsListResponse(
        conversations=result,
        total=total,
    )


@router.post(
    "/{account_id}/analyze",
    response_model=AnalyzeResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger profile analysis",
    description="Queue a job to analyze or re-analyze this account's profile.",
)
async def trigger_analyze(
    account_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """Trigger profile analysis for an account."""
    # Verify account exists
    account = db.query(ExternalAccount).filter_by(id=account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    # TODO: Queue analysis job when agent tasks are implemented
    # For now, just update the analysis state and create audit log

    # Audit log
    audit_entry = AuditLog(
        ts=datetime.now(timezone.utc),
        actor="user",
        action_type="account.analyze",
        result="ok",
        provider_id=account.provider_id,
        entity_type="external_account",
        entity_id=account_id,
        request_json={"account_id": account_id},
        response_json={"status": "queued"},
    )
    db.add(audit_entry)
    db.commit()

    return AnalyzeResponse(
        status="queued",
        message="Profile analysis has been queued. This feature requires the agent worker to be running.",
        job_id=None,  # Would be set once job infrastructure is in place
    )
