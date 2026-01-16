"""Conversation management API routes.

Provides endpoints for:
- GET /conversations - List conversations with pagination
- GET /conversations/{id} - Get a single conversation
- GET /conversations/{id}/messages - Get messages in a conversation
- POST /conversations/{id}/messages - Send a message to a conversation
- GET /conversations/{id}/pending - Get pending (unsent) messages
- POST /conversations/{id}/messages/{id}/retry - Retry sending a failed message
- POST /conversations/initiate/from-lead/{lead_id} - Start conversation with lead author
"""

import base64
import json
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import and_, desc, or_
from sqlalchemy.orm import joinedload

from rediska_core.api.deps import CurrentUser, DBSession, get_db
from rediska_core.domain.models import AuditLog
from rediska_core.api.schemas.conversation import (
    AttachmentInMessageResponse,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationSummaryResponse,
    CounterpartResponse,
    MessageInConversationResponse,
    MessageListResponse,
)
from rediska_core.api.schemas.message import (
    DeleteMessageResponse,
    PendingMessageResponse,
    SendMessageRequest,
    SendMessageResponse,
    SyncJobResponse,
    SyncJobStatusResponse,
)
from rediska_core.domain.models import Attachment, Conversation, ExternalAccount, Identity, Message
from rediska_core.domain.services.send_message import (
    ConversationNotFoundError,
    CounterpartStatusError,
    EmptyMessageError,
    MessageAccessDeniedError,
    MessageNotFoundError,
    MessageNotPendingError,
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
    has_attachments: Optional[bool] = Query(None, description="Filter to conversations with attachments"),
    has_replies: Optional[bool] = Query(None, description="Filter to conversations with incoming replies"),
):
    """List conversations with cursor-based pagination.

    Conversations are ordered by the timestamp of their last message DESC, then by id DESC.
    The cursor encodes (last_message_sent_at, id) for stable pagination.
    """
    from sqlalchemy import func

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

    # Filter for conversations with attachments
    if has_attachments is True:
        # Subquery to find conversation IDs that have at least one attachment
        conversations_with_attachments = (
            db.query(Message.conversation_id)
            .join(Attachment, Attachment.message_id == Message.id)
            .filter(Message.deleted_at.is_(None))
            .filter(Attachment.remote_visibility != "removed")
            .distinct()
            .subquery()
        )
        query = query.filter(Conversation.id.in_(
            db.query(conversations_with_attachments.c.conversation_id)
        ))

    # Filter for conversations with incoming replies
    if has_replies is True:
        # Subquery to find conversation IDs that have at least one incoming message
        conversations_with_replies = (
            db.query(Message.conversation_id)
            .filter(Message.deleted_at.is_(None))
            .filter(Message.direction == "in")
            .distinct()
            .subquery()
        )
        query = query.filter(Conversation.id.in_(
            db.query(conversations_with_replies.c.conversation_id)
        ))

    # Create a subquery to get the max message sent_at for each conversation
    # This ensures we order by actual last message time, not stale last_activity_at
    max_message_time = (
        db.query(
            Message.conversation_id,
            func.max(Message.sent_at).label('max_sent_at')
        )
        .filter(Message.deleted_at.is_(None))
        .group_by(Message.conversation_id)
        .subquery()
    )

    # Left join with the subquery to get the actual last message time
    query = query.outerjoin(
        max_message_time,
        Conversation.id == max_message_time.c.conversation_id
    )

    # Apply cursor if provided
    if cursor:
        cursor_data = decode_cursor(cursor)
        cursor_time = cursor_data.get("last_activity_at")
        cursor_id = cursor_data.get("id")

        # Cursor condition: (max_sent_at, id) < (cursor_time, cursor_id)
        # We need to compare with the subquery's max_sent_at
        query = query.filter(
            or_(
                max_message_time.c.max_sent_at < cursor_time,
                and_(
                    max_message_time.c.max_sent_at == cursor_time,
                    Conversation.id < cursor_id,
                ),
            )
        )

    # Order by actual last message time (max_sent_at) DESC, then by id DESC
    query = query.order_by(
        desc(max_message_time.c.max_sent_at),
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
        # Get last message preview and actual timestamp
        last_message = (
            db.query(Message)
            .filter_by(conversation_id=conv.id)
            .filter(Message.deleted_at.is_(None))
            .order_by(desc(Message.sent_at))
            .first()
        )
        preview = None
        # Use the actual last message timestamp
        last_message_time = last_message.sent_at if last_message else conv.last_activity_at
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
                last_activity_at=last_message_time,
                last_message_preview=preview,
                unread_count=0,  # TODO: implement unread tracking
                archived_at=conv.archived_at,
                created_at=conv.created_at,
            )
        )

    # Generate next cursor using the actual last message time
    next_cursor = None
    if has_more and conversations:
        last = conversations[-1]
        last_message = (
            db.query(Message)
            .filter_by(conversation_id=last.id)
            .filter(Message.deleted_at.is_(None))
            .order_by(desc(Message.sent_at))
            .first()
        )
        last_message_time = last_message.sent_at if last_message else last.last_activity_at
        next_cursor = encode_cursor(
            last_message_time.isoformat() if last_message_time else "",
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

    # Fetch attachments for all messages in one query
    message_ids = [msg.id for msg in messages]
    attachments_by_message: dict[int, list[Attachment]] = {}
    if message_ids:
        all_attachments = (
            db.query(Attachment)
            .filter(Attachment.message_id.in_(message_ids))
            .filter(Attachment.remote_visibility != "removed")
            .all()
        )
        for att in all_attachments:
            if att.message_id not in attachments_by_message:
                attachments_by_message[att.message_id] = []
            attachments_by_message[att.message_id].append(att)

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
            attachments=[
                AttachmentInMessageResponse(
                    id=att.id,
                    mime_type=att.mime_type,
                    size_bytes=att.size_bytes,
                    width_px=att.width_px,
                    height_px=att.height_px,
                )
                for att in attachments_by_message.get(msg.id, [])
            ],
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
    db: DBSession,
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
    from datetime import datetime, timezone
    from celery import Celery

    try:
        result = send_service.enqueue_send(
            conversation_id=conversation_id,
            body_text=request.body_text,
            attachment_ids=request.attachment_ids,
        )

        # Get the job to retrieve the payload
        from rediska_core.domain.models import Job
        from rediska_core.config import get_settings

        job = db.query(Job).filter(Job.id == result.job_id).first()
        job_payload = job.payload_json if job else None

        # IMPORTANT: Commit the message and job BEFORE sending to Celery
        # This ensures the worker can find the message when it processes the task
        db.commit()

        # Now send the actual Celery task (after commit)
        if job_payload:
            try:
                settings = get_settings()
                # Create a properly configured Celery app instance matching worker config
                from celery import Celery
                celery_app = Celery(
                    "rediska",
                    broker=settings.celery_broker_url,
                    backend=settings.celery_result_backend,
                )
                # Configure with exact same serialization as worker
                celery_app.conf.update(
                    task_serializer="json",
                    accept_content=["json"],
                    result_serializer="json",
                    timezone="UTC",
                    enable_utc=True,
                    task_acks_late=True,
                    task_reject_on_worker_lost=True,
                    task_soft_time_limit=300,
                    task_time_limit=600,
                    task_default_retry_delay=60,
                    task_max_retries=10,
                    task_routes={
                        "message.send_manual": {"queue": "messages"},
                    },
                )
                celery_app.send_task(
                    "message.send_manual",
                    kwargs={"payload": job_payload},
                    queue="messages",
                )
            except Exception as e:
                # Log the error but don't fail the request
                import logging
                logging.error(f"Error enqueueing message send task: {e}", exc_info=True)

        # Audit log for successful message queue
        audit_entry = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="message.send",
            result="ok",
            entity_type="message",
            entity_id=result.message_id,
            request_json={
                "conversation_id": conversation_id,
                "body_length": len(request.body_text) if request.body_text else 0,
                "has_attachments": bool(request.attachment_ids),
            },
            response_json={"job_id": result.job_id, "message_id": result.message_id},
        )
        db.add(audit_entry)
        db.commit()

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
    db: DBSession,
):
    """Retry sending a pending message.

    Only messages with 'unknown' visibility can be retried.
    This is a manual action to handle ambiguous failures.
    """
    from datetime import datetime, timezone
    from celery import Celery

    result = send_service.retry_failed_send(message_id=message_id)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message cannot be retried (not found or already sent)",
        )

    # Get job payload before committing
    from rediska_core.config import get_settings
    from rediska_core.domain.models import Job

    job = db.query(Job).filter(Job.id == result.job_id).first()
    job_payload = job.payload_json if job else None

    # IMPORTANT: Commit the job BEFORE sending to Celery
    # This ensures the worker can find the message when it processes the task
    db.commit()

    # Now send the actual Celery task (after commit)
    if job_payload:
        try:
            settings = get_settings()
            # Create a properly configured Celery app instance matching worker config
            celery_app = Celery(
                "rediska",
                broker=settings.celery_broker_url,
                backend=settings.celery_result_backend,
            )
            # Configure with exact same serialization as worker
            celery_app.conf.update(
                task_serializer="json",
                accept_content=["json"],
                result_serializer="json",
                timezone="UTC",
                enable_utc=True,
                task_acks_late=True,
                task_reject_on_worker_lost=True,
                task_soft_time_limit=300,
                task_time_limit=600,
                task_default_retry_delay=60,
                task_max_retries=10,
                task_routes={
                    "message.send_manual": {"queue": "messages"},
                },
            )
            celery_app.send_task(
                "message.send_manual",
                kwargs={"payload": job_payload},
                queue="messages",
            )
        except Exception as e:
            # Log the error but don't fail the request
            import logging
            logging.error(f"Error enqueueing message retry task: {e}", exc_info=True)

    # Audit log for message retry
    audit_entry = AuditLog(
        ts=datetime.now(timezone.utc),
        actor="user",
        action_type="message.retry",
        result="ok",
        entity_type="message",
        entity_id=message_id,
        request_json={"conversation_id": conversation_id, "message_id": message_id},
        response_json={"job_id": result.job_id},
    )
    db.add(audit_entry)
    db.commit()

    return SendMessageResponse(
        job_id=result.job_id,
        message_id=result.message_id,
        status=result.status,
    )


@router.delete(
    "/{conversation_id}/messages/{message_id}",
    response_model=DeleteMessageResponse,
    summary="Delete a pending message",
    description="Delete a pending (unsent) message. Only messages with 'unknown' "
                "visibility can be deleted. Attempts to cancel the associated send job.",
)
async def delete_pending_message(
    conversation_id: int,
    message_id: int,
    current_user: CurrentUser,
    send_service: SendMessageServiceDep,
    db: DBSession,
):
    """Delete a pending message.

    Only pending outgoing messages (remote_visibility='unknown') can be deleted.
    The message is soft-deleted and the associated send job is cancelled if possible.

    Args:
        conversation_id: The conversation ID (for audit logging)
        message_id: The message ID to delete
        current_user: Current authenticated user
        send_service: Send message service
        db: Database session

    Raises:
        HTTPException: If message not found (404), not pending (409), or access denied (403)

    Returns:
        DeleteMessageResponse with deletion details
    """
    from datetime import datetime, timezone

    try:
        result = send_service.delete_pending_message(message_id=message_id)

        # Audit log for message deletion
        audit_entry = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="message.delete",
            result="ok",
            entity_type="message",
            entity_id=message_id,
            request_json={
                "message_id": message_id,
                "conversation_id": conversation_id,
            },
            response_json=result,
        )
        db.add(audit_entry)
        db.commit()

        return DeleteMessageResponse(
            message="Message deleted successfully",
            message_id=result["message_id"],
            job_cancelled=result["job_cancelled"],
        )

    except MessageNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )

    except MessageNotPendingError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    except MessageAccessDeniedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
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
    db: DBSession,
    identity_id: Optional[int] = Query(None, description="Specific identity to sync (default: active identity)"),
):
    """Trigger a background sync job for Reddit messages.

    Queues a Celery task to fetch conversations and messages from Reddit's API
    and store them in the local database. Returns immediately with a job ID
    that can be used to check status.
    """
    from datetime import datetime, timezone
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

    # Audit log for sync trigger
    audit_entry = AuditLog(
        ts=datetime.now(timezone.utc),
        actor="user",
        action_type="sync.trigger",
        result="ok",
        provider_id="reddit",
        identity_id=identity_id,
        request_json={"identity_id": identity_id},
        response_json={"job_id": task.id},
    )
    db.add(audit_entry)
    db.commit()

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


@router.post(
    "/{conversation_id}/attachments",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an attachment for a conversation message",
    description="Upload a file as an attachment for a conversation. Maximum size is 10MB.",
)
async def upload_conversation_attachment(
    conversation_id: int,
    db: DBSession,
    file: UploadFile = File(..., description="File to upload"),
):
    """Upload an attachment for a conversation message.

    The file will be validated for size and MIME type.

    Returns attachment ID for use when sending messages.
    """
    from datetime import datetime, timezone
    from rediska_core.domain.services.attachment import (
        AttachmentService,
        FileTooLargeError,
        InvalidMimeTypeError,
    )
    from rediska_core.config import get_settings

    settings = get_settings()
    attachment_service = AttachmentService(db=db, storage_path=settings.attachments_path)

    # Read file content
    content = await file.read()

    # Validate content type
    content_type = file.content_type or "application/octet-stream"

    try:
        result = attachment_service.upload(
            file_data=content,
            filename=file.filename or "upload",
            content_type=content_type,
        )

        # Audit log for successful upload
        audit_entry = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="attachment.upload",
            result="ok",
            entity_type="attachment",
            entity_id=result.attachment_id,
            request_json={
                "filename": file.filename,
                "content_type": content_type,
                "size_bytes": len(content),
                "conversation_id": conversation_id,
            },
            response_json={
                "attachment_id": result.attachment_id,
                "sha256": result.sha256,
            },
        )
        db.add(audit_entry)
        db.commit()

        return {
            "attachment_id": result.attachment_id,
            "sha256": result.sha256,
            "size_bytes": len(content),
            "mime_type": content_type,
        }

    except InvalidMimeTypeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File type not supported. Allowed types: images, PDFs, and common documents.",
        )
    except FileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File size exceeds 10MB limit.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}",
        )


@router.post(
    "/initiate/from-lead/{lead_id}",
    response_model=ConversationSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Initiate a conversation with a lead author",
    description="Create or get a conversation with the author of a saved lead.",
)
async def initiate_conversation_from_lead(
    lead_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """Initiate a new conversation with a lead author.

    This endpoint:
    1. Fetches the lead and its author
    2. Gets or creates an ExternalAccount for the author
    3. Gets or creates a Conversation between the default identity and that account
    4. Returns the conversation details

    The user can then send messages through the conversation endpoint.
    """
    from rediska_core.domain.models import LeadPost

    # Get the lead
    lead = (
        db.query(LeadPost)
        .filter(LeadPost.id == lead_id)
        .first()
    )

    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found",
        )

    if not lead.author_account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lead has no author information",
        )

    # Get the author's external account
    author_external_account = (
        db.query(ExternalAccount)
        .filter(ExternalAccount.id == lead.author_account_id)
        .first()
    )

    if not author_external_account:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Author account not found",
        )

    author_username = author_external_account.external_username

    # Get the default identity
    identity = (
        db.query(Identity)
        .filter_by(provider_id="reddit", is_active=True, is_default=True)
        .first()
    )

    if not identity:
        # Fall back to first active identity
        identity = (
            db.query(Identity)
            .filter_by(provider_id="reddit", is_active=True)
            .first()
        )

    if not identity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active identity configured",
        )

    # Get or create conversation with the lead author
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.provider_id == "reddit",
            Conversation.identity_id == identity.id,
            Conversation.counterpart_account_id == author_external_account.id,
        )
        .first()
    )

    if not conversation:
        # Create new conversation
        from datetime import datetime, timezone

        conversation = Conversation(
            provider_id="reddit",
            external_conversation_id=f"reddit:pair:{identity.external_username.lower()}:{author_username.lower()}",
            counterpart_account_id=author_external_account.id,
            identity_id=identity.id,
            last_activity_at=datetime.now(timezone.utc),
        )
        db.add(conversation)
        db.flush()

        # Audit log
        audit_entry = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="conversation.initiate",
            result="ok",
            entity_type="conversation",
            entity_id=conversation.id,
            request_json={"lead_id": lead_id, "author_username": author_username},
            response_json={"conversation_id": conversation.id},
        )
        db.add(audit_entry)
        db.commit()

    # Build counterpart response
    from rediska_core.api.schemas.conversation import CounterpartResponse

    counterpart = CounterpartResponse(
        id=author_external_account.id,
        external_username=author_external_account.external_username,
        external_user_id=author_external_account.external_user_id,
        remote_status=author_external_account.remote_status,
    )

    return ConversationSummaryResponse(
        id=conversation.id,
        provider_id=conversation.provider_id,
        identity_id=identity.id,
        external_conversation_id=conversation.external_conversation_id,
        counterpart=counterpart,
        last_activity_at=conversation.last_activity_at,
        unread_count=0,  # Newly created conversation has no unread messages
        archived_at=conversation.archived_at,
        created_at=conversation.created_at,
    )
