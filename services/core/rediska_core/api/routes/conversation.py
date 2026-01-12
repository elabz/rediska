"""Conversation management API routes.

Provides endpoints for:
- GET /conversations - List conversations with pagination
- GET /conversations/{id} - Get a single conversation
- GET /conversations/{id}/messages - Get messages in a conversation
- POST /conversations/{id}/messages - Send a message to a conversation
- GET /conversations/{id}/pending - Get pending (unsent) messages
- POST /conversations/{id}/messages/{id}/retry - Retry sending a failed message
"""

import base64
import json
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, desc, or_
from sqlalchemy.orm import joinedload

from rediska_core.api.deps import CurrentUser, DBSession
from rediska_core.api.schemas.conversation import (
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationSummaryResponse,
    CounterpartResponse,
    MessageInConversationResponse,
    MessageListResponse,
)
from rediska_core.api.schemas.message import (
    PendingMessageResponse,
    SendMessageRequest,
    SendMessageResponse,
    SyncJobResponse,
    SyncJobStatusResponse,
)
from rediska_core.domain.models import Conversation, ExternalAccount, Identity, Message
from rediska_core.domain.services.send_message import (
    ConversationNotFoundError,
    CounterpartStatusError,
    EmptyMessageError,
    MissingCredentialsError,
    SendMessageService,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


def get_send_message_service(db: DBSession) -> SendMessageService:
    """Get the send message service."""
    return SendMessageService(db=db)


SendMessageServiceDep = Annotated[SendMessageService, Depends(get_send_message_service)]


def encode_cursor(last_activity_at: str, id: int) -> str:
    """Encode cursor for pagination."""
    data = {"last_activity_at": last_activity_at, "id": id}
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


def decode_cursor(cursor: str) -> dict:
    """Decode cursor for pagination."""
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return data
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid cursor",
        )


def encode_message_cursor(sent_at: str, id: int) -> str:
    """Encode cursor for message pagination."""
    data = {"sent_at": sent_at, "id": id}
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


def decode_message_cursor(cursor: str) -> dict:
    """Decode cursor for message pagination."""
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return data
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid cursor",
        )


@router.get(
    "",
    response_model=ConversationListResponse,
    summary="List conversations",
    description="Get a paginated list of conversations, optionally filtered by identity.",
)
async def list_conversations(
    current_user: CurrentUser,
    db: DBSession,
    identity_id: Optional[int] = Query(None, description="Filter by identity ID"),
    cursor: Optional[str] = Query(None, description="Pagination cursor"),
    limit: int = Query(20, ge=1, le=100, description="Number of results per page"),
    include_archived: bool = Query(False, description="Include archived conversations"),
):
    """List conversations with cursor-based pagination.

    Conversations are ordered by last_activity_at DESC, then by id DESC.
    The cursor encodes (last_activity_at, id) for stable pagination.
    """
    # Build base query
    query = (
        db.query(Conversation)
        .options(joinedload(Conversation.counterpart_account))
        .filter(Conversation.deleted_at.is_(None))
    )

    # Filter by identity if specified
    if identity_id is not None:
        # Verify the identity exists and is active
        identity = db.query(Identity).filter_by(id=identity_id, is_active=True).first()
        if not identity:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Identity not found",
            )
        query = query.filter(Conversation.identity_id == identity_id)
    else:
        # Filter to conversations belonging to active identities
        active_identity_ids = [i.id for i in db.query(Identity).filter_by(is_active=True).all()]
        if not active_identity_ids:
            return ConversationListResponse(conversations=[], has_more=False)
        query = query.filter(Conversation.identity_id.in_(active_identity_ids))

    # Exclude archived unless requested
    if not include_archived:
        query = query.filter(Conversation.archived_at.is_(None))

    # Apply cursor if provided
    if cursor:
        cursor_data = decode_cursor(cursor)
        cursor_time = cursor_data.get("last_activity_at")
        cursor_id = cursor_data.get("id")

        # Cursor condition: (last_activity_at, id) < (cursor_time, cursor_id)
        query = query.filter(
            or_(
                Conversation.last_activity_at < cursor_time,
                and_(
                    Conversation.last_activity_at == cursor_time,
                    Conversation.id < cursor_id,
                ),
            )
        )

    # Order and limit
    query = query.order_by(
        desc(Conversation.last_activity_at),
        desc(Conversation.id),
    ).limit(limit + 1)  # Fetch one extra to check if there are more

    conversations = query.all()

    # Check if there are more results
    has_more = len(conversations) > limit
    if has_more:
        conversations = conversations[:limit]

    # Build response
    result = []
    for conv in conversations:
        # Get last message preview
        last_message = (
            db.query(Message)
            .filter_by(conversation_id=conv.id)
            .filter(Message.deleted_at.is_(None))
            .order_by(desc(Message.sent_at))
            .first()
        )
        preview = None
        if last_message and last_message.body_text:
            preview = last_message.body_text[:100] + "..." if len(last_message.body_text) > 100 else last_message.body_text

        result.append(
            ConversationSummaryResponse(
                id=conv.id,
                provider_id=conv.provider_id,
                identity_id=conv.identity_id,
                external_conversation_id=conv.external_conversation_id,
                counterpart=CounterpartResponse(
                    id=conv.counterpart_account.id,
                    external_username=conv.counterpart_account.external_username,
                    external_user_id=conv.counterpart_account.external_user_id,
                    remote_status=conv.counterpart_account.remote_status,
                ),
                last_activity_at=conv.last_activity_at,
                last_message_preview=preview,
                unread_count=0,  # TODO: implement unread tracking
                archived_at=conv.archived_at,
                created_at=conv.created_at,
            )
        )

    # Generate next cursor
    next_cursor = None
    if has_more and conversations:
        last = conversations[-1]
        next_cursor = encode_cursor(
            last.last_activity_at.isoformat() if last.last_activity_at else "",
            last.id,
        )

    return ConversationListResponse(
        conversations=result,
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetailResponse,
    summary="Get a conversation",
    description="Get details of a single conversation.",
)
async def get_conversation(
    conversation_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """Get a single conversation by ID."""
    conversation = (
        db.query(Conversation)
        .options(joinedload(Conversation.counterpart_account))
        .filter_by(id=conversation_id)
        .filter(Conversation.deleted_at.is_(None))
        .first()
    )

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    # Verify the conversation's identity is active
    identity = db.query(Identity).filter_by(id=conversation.identity_id, is_active=True).first()
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    return ConversationDetailResponse(
        id=conversation.id,
        provider_id=conversation.provider_id,
        identity_id=conversation.identity_id,
        external_conversation_id=conversation.external_conversation_id,
        counterpart=CounterpartResponse(
            id=conversation.counterpart_account.id,
            external_username=conversation.counterpart_account.external_username,
            external_user_id=conversation.counterpart_account.external_user_id,
            remote_status=conversation.counterpart_account.remote_status,
        ),
        last_activity_at=conversation.last_activity_at,
        archived_at=conversation.archived_at,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


@router.get(
    "/{conversation_id}/messages",
    response_model=MessageListResponse,
    summary="List messages in a conversation",
    description="Get a paginated list of messages in a conversation.",
)
async def list_messages(
    conversation_id: int,
    current_user: CurrentUser,
    db: DBSession,
    cursor: Optional[str] = Query(None, description="Pagination cursor"),
    limit: int = Query(50, ge=1, le=100, description="Number of results per page"),
):
    """List messages in a conversation with cursor-based pagination.

    Messages are ordered by sent_at DESC, then by id DESC (newest first).
    The cursor encodes (sent_at, id) for stable pagination.
    """
    # Get the conversation and verify access
    conversation = db.query(Conversation).filter_by(id=conversation_id).first()
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    # Verify the conversation's identity is active
    identity = db.query(Identity).filter_by(id=conversation.identity_id, is_active=True).first()
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Build query
    query = (
        db.query(Message)
        .filter_by(conversation_id=conversation_id)
        .filter(Message.deleted_at.is_(None))
    )

    # Apply cursor if provided
    if cursor:
        cursor_data = decode_message_cursor(cursor)
        cursor_time = cursor_data.get("sent_at")
        cursor_id = cursor_data.get("id")

        # Cursor condition: (sent_at, id) < (cursor_time, cursor_id)
        query = query.filter(
            or_(
                Message.sent_at < cursor_time,
                and_(
                    Message.sent_at == cursor_time,
                    Message.id < cursor_id,
                ),
            )
        )

    # Order and limit
    query = query.order_by(
        desc(Message.sent_at),
        desc(Message.id),
    ).limit(limit + 1)

    messages = query.all()

    # Check if there are more results
    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]

    # Build response
    result = [
        MessageInConversationResponse(
            id=msg.id,
            direction=msg.direction,
            body_text=msg.body_text,
            sent_at=msg.sent_at,
            remote_visibility=msg.remote_visibility,
            identity_id=msg.identity_id,
            created_at=msg.created_at,
        )
        for msg in messages
    ]

    # Generate next cursor
    next_cursor = None
    if has_more and messages:
        last = messages[-1]
        next_cursor = encode_message_cursor(
            last.sent_at.isoformat(),
            last.id,
        )

    return MessageListResponse(
        messages=result,
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=SendMessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a message",
    description="Queue a message to be sent to the conversation counterpart. "
                "The message will be sent asynchronously by a background worker. "
                "Returns 202 Accepted with job details.",
)
async def send_message(
    conversation_id: int,
    request: SendMessageRequest,
    current_user: CurrentUser,
    send_service: SendMessageServiceDep,
):
    """Send a message to a conversation.

    The message is queued for sending by a background worker.
    Implements at-most-once delivery semantics:
    - Message is created with 'unknown' visibility
    - On success, visibility updates to 'visible'
    - On ambiguous failure, visibility stays 'unknown' (no auto-retry)
    - User can manually retry pending messages

    Returns 202 Accepted with job and message IDs.
    """
    try:
        result = send_service.enqueue_send(
            conversation_id=conversation_id,
            body_text=request.body_text,
            attachment_ids=request.attachment_ids,
        )

        return SendMessageResponse(
            job_id=result.job_id,
            message_id=result.message_id,
            status=result.status,
        )

    except ConversationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

    except CounterpartStatusError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    except EmptyMessageError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    except MissingCredentialsError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )


@router.get(
    "/{conversation_id}/pending",
    response_model=list[PendingMessageResponse],
    summary="Get pending messages",
    description="Get messages with unknown send status (may or may not have been sent).",
)
async def get_pending_messages(
    conversation_id: int,
    current_user: CurrentUser,
    send_service: SendMessageServiceDep,
):
    """Get pending messages for a conversation.

    Returns messages with 'unknown' visibility that may need
    manual reconciliation.
    """
    messages = send_service.get_pending_messages(
        conversation_id=conversation_id,
    )

    return [
        PendingMessageResponse(
            id=msg.id,
            conversation_id=msg.conversation_id,
            body_text=msg.body_text,
            sent_at=msg.sent_at,
            remote_visibility=msg.remote_visibility,
            can_retry=True,
        )
        for msg in messages
    ]


@router.post(
    "/{conversation_id}/messages/{message_id}/retry",
    response_model=SendMessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry sending a message",
    description="Manually retry sending a message that previously failed.",
)
async def retry_message(
    conversation_id: int,
    message_id: int,
    current_user: CurrentUser,
    send_service: SendMessageServiceDep,
):
    """Retry sending a pending message.

    Only messages with 'unknown' visibility can be retried.
    This is a manual action to handle ambiguous failures.
    """
    result = send_service.retry_failed_send(message_id=message_id)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message cannot be retried (not found or already sent)",
        )

    return SendMessageResponse(
        job_id=result.job_id,
        message_id=result.message_id,
        status=result.status,
    )


@router.post(
    "/sync",
    response_model=SyncJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger message sync from Reddit",
    description="Queue a background job to sync conversations and messages from Reddit.",
)
async def trigger_sync(
    current_user: CurrentUser,
    identity_id: Optional[int] = Query(None, description="Specific identity to sync (default: active identity)"),
):
    """Trigger a background sync job for Reddit messages.

    Queues a Celery task to fetch conversations and messages from Reddit's API
    and store them in the local database. Returns immediately with a job ID
    that can be used to check status.
    """
    from celery import Celery
    from rediska_core.config import get_settings

    settings = get_settings()
    celery_app = Celery(broker=settings.celery_broker_url, backend=settings.celery_result_backend)

    # Send the task to the worker
    task = celery_app.send_task(
        "ingest.sync_delta",
        kwargs={"provider_id": "reddit", "identity_id": identity_id},
        queue="ingest",
    )

    return SyncJobResponse(
        job_id=task.id,
        status="queued",
        message="Sync job queued. Messages will be synced in the background.",
    )


@router.get(
    "/sync/{job_id}",
    response_model=SyncJobStatusResponse,
    summary="Check sync job status",
    description="Check the status of a background sync job.",
)
async def get_sync_status(
    job_id: str,
    current_user: CurrentUser,
):
    """Check the status of a sync job.

    Returns the current status and result (if completed) of a sync job.
    """
    from celery import Celery
    from celery.result import AsyncResult
    from rediska_core.config import get_settings

    settings = get_settings()
    celery_app = Celery(broker=settings.celery_broker_url, backend=settings.celery_result_backend)

    result = AsyncResult(job_id, app=celery_app)

    if result.ready():
        if result.successful():
            return SyncJobStatusResponse(
                job_id=job_id,
                status="success",
                result=result.result,
            )
        else:
            return SyncJobStatusResponse(
                job_id=job_id,
                status="failure",
                result={"error": str(result.result)},
            )
    else:
        return SyncJobStatusResponse(
            job_id=job_id,
            status="pending",
            result=None,
        )
