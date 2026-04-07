"""Conversation management API routes.

Provides endpoints for:
- GET /conversations - List conversations with pagination
- GET /conversations/{id} - Get a single conversation
- GET /conversations/{id}/messages - Get messages in a conversation
- POST /conversations/{id}/messages - Send a message to a conversation
- GET /conversations/{id}/pending - Get pending (unsent) messages
- POST /conversations/{id}/messages/{id}/retry - Retry sending a failed message
- POST /conversations/initiate/from-lead/{lead_id} - Start conversation with lead author
- POST /conversations/initiate/by-username - Start conversation by username
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
    ConversationSearchHit,
    ConversationSearchResponse,
    ConversationSummaryResponse,
    CounterpartResponse,
    InitiateByUsernameRequest,
    MessageInConversationResponse,
    MessageListResponse,
)
from rediska_core.api.schemas.message import (
    DeleteMessageResponse,
    PendingMessageResponse,
    RemoteDeleteBatchRequest,
    RemoteDeleteBatchResponse,
    RemoteDeleteResultItem,
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
    # Batch-check which conversations have failed messages
    conv_ids = [conv.id for conv in conversations]
    failed_conv_ids = set()
    if conv_ids:
        failed_rows = (
            db.query(Message.conversation_id)
            .filter(
                Message.conversation_id.in_(conv_ids),
                Message.remote_visibility == "send_failed",
                Message.deleted_at.is_(None),
            )
            .distinct()
            .all()
        )
        failed_conv_ids = {row[0] for row in failed_rows}

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
                    is_starred=conv.counterpart_account.is_starred,
                ),
                last_activity_at=last_message_time,
                last_message_preview=preview,
                unread_count=0,  # TODO: implement unread tracking
                has_failed_messages=conv.id in failed_conv_ids,
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
    "/search",
    response_model=ConversationSearchResponse,
    summary="Search conversations by message content",
    description="Full-text search across all message bodies using Elasticsearch. "
                "Returns exact matches first (sorted by recency), then fuzzy matches.",
)
async def search_conversations(
    current_user: CurrentUser,
    db: DBSession,
    q: str = Query(..., min_length=1, description="Search query"),
    identity_id: Optional[int] = Query(None, description="Filter by identity ID"),
):
    """Search conversations by message content.

    Two-pass search:
    1. Exact matches (no fuzziness) — sorted by most recent first
    2. Fuzzy matches — sorted by most recent first, excluding conversations
       already found in pass 1
    """
    import logging
    from rediska_core.config import get_settings
    from rediska_core.domain.services.search import SearchService, SearchError

    settings = get_settings()
    search_service = SearchService(
        es_url=settings.elastic_url,
        es_api_key=getattr(settings, "elastic_api_key", None),
    )

    # Validate identity if provided
    if identity_id is not None:
        identity = db.query(Identity).filter_by(id=identity_id, is_active=True).first()
        if not identity:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Identity not found",
            )

    # --- Pass 1: exact matches (no fuzziness) ---
    exact_per_conv: dict[int, dict] = {}
    try:
        exact_results = search_service.text_search(
            query=q, doc_types=["message"], identity_id=identity_id,
            limit=500, fuzziness=None,
        )
        for hit in exact_results.get("hits", []):
            conv_id = hit.get("source", {}).get("conversation_id")
            if conv_id is None:
                continue
            if conv_id not in exact_per_conv or hit.get("score", 0) > exact_per_conv[conv_id].get("score", 0):
                exact_per_conv[conv_id] = hit
    except SearchError as e:
        logging.error(f"Exact conversation search failed: {e}")

    # --- Pass 2: fuzzy matches ---
    fuzzy_per_conv: dict[int, dict] = {}
    try:
        fuzzy_results = search_service.text_search(
            query=q, doc_types=["message"], identity_id=identity_id,
            limit=500, fuzziness="AUTO",
        )
        for hit in fuzzy_results.get("hits", []):
            conv_id = hit.get("source", {}).get("conversation_id")
            if conv_id is None:
                continue
            # Only keep conversations NOT already found in exact pass
            if conv_id in exact_per_conv:
                continue
            if conv_id not in fuzzy_per_conv or hit.get("score", 0) > fuzzy_per_conv[conv_id].get("score", 0):
                fuzzy_per_conv[conv_id] = hit
    except SearchError as e:
        logging.error(f"Fuzzy conversation search failed: {e}")

    all_conv_ids = list(exact_per_conv.keys()) + list(fuzzy_per_conv.keys())
    if not all_conv_ids:
        return ConversationSearchResponse(conversations=[], total=0)

    # Load all matching conversations from DB in one query
    convs = (
        db.query(Conversation)
        .options(joinedload(Conversation.counterpart_account))
        .filter(Conversation.id.in_(all_conv_ids))
        .filter(Conversation.deleted_at.is_(None))
        .all()
    )
    conv_map = {c.id: c for c in convs}

    # Check for failed messages
    failed_conv_ids = set()
    if all_conv_ids:
        failed_rows = (
            db.query(Message.conversation_id)
            .filter(
                Message.conversation_id.in_(all_conv_ids),
                Message.remote_visibility == "send_failed",
                Message.deleted_at.is_(None),
            )
            .distinct()
            .all()
        )
        failed_conv_ids = {row[0] for row in failed_rows}

    # Helper: build a ConversationSearchHit from a conversation + best hit
    def build_hit(conv_id: int, best_hit: dict) -> Optional[ConversationSearchHit]:
        conv = conv_map.get(conv_id)
        if not conv:
            return None

        source = best_hit.get("source", {})
        content = source.get("content", "")
        snippet = content[:150] + "..." if len(content) > 150 else content

        last_message = (
            db.query(Message)
            .filter_by(conversation_id=conv.id)
            .filter(Message.deleted_at.is_(None))
            .order_by(desc(Message.sent_at))
            .first()
        )
        preview = None
        last_message_time = last_message.sent_at if last_message else conv.last_activity_at
        if last_message and last_message.body_text:
            preview = last_message.body_text[:100] + "..." if len(last_message.body_text) > 100 else last_message.body_text

        return ConversationSearchHit(
            id=conv.id,
            provider_id=conv.provider_id,
            identity_id=conv.identity_id,
            external_conversation_id=conv.external_conversation_id,
            counterpart=CounterpartResponse(
                id=conv.counterpart_account.id,
                external_username=conv.counterpart_account.external_username,
                external_user_id=conv.counterpart_account.external_user_id,
                remote_status=conv.counterpart_account.remote_status,
                is_starred=conv.counterpart_account.is_starred,
            ),
            last_activity_at=last_message_time,
            last_message_preview=preview,
            unread_count=0,
            has_failed_messages=conv.id in failed_conv_ids,
            archived_at=conv.archived_at,
            created_at=conv.created_at,
            matching_snippet=snippet,
        )

    # Build exact results sorted by most recent first
    exact_hits = []
    for conv_id, best_hit in exact_per_conv.items():
        hit = build_hit(conv_id, best_hit)
        if hit:
            exact_hits.append(hit)
    exact_hits.sort(key=lambda h: h.last_activity_at or h.created_at, reverse=True)

    # Build fuzzy results sorted by most recent first
    fuzzy_hits = []
    for conv_id, best_hit in fuzzy_per_conv.items():
        hit = build_hit(conv_id, best_hit)
        if hit:
            fuzzy_hits.append(hit)
    fuzzy_hits.sort(key=lambda h: h.last_activity_at or h.created_at, reverse=True)

    # Exact first, then fuzzy
    result = exact_hits + fuzzy_hits
    return ConversationSearchResponse(conversations=result, total=len(result))


@router.get(
    "/export-dataset",
    summary="Export conversations as fine-tuning dataset",
    description="Download a ChatML JSONL file for fine-tuning with Unsloth or similar tools.",
)
async def export_dataset(
    current_user: CurrentUser,
    db: DBSession,
    format: str = Query("chatml", description="Export format (chatml)"),
    identity_id: Optional[int] = Query(None, description="Filter by identity"),
    system_prompt: str = Query(
        "You are having a private conversation on Reddit.",
        description="System prompt to prepend",
    ),
    max_tokens: int = Query(4096, description="Max sequence length hint"),
    test_only: bool = Query(False, description="Only export [TEST] conversations"),
    list_id: Optional[int] = Query(None, description="Filter by conversation list ID"),
):
    """Export conversations as a ChatML JSONL dataset for fine-tuning."""
    from datetime import datetime, timezone
    from fastapi.responses import StreamingResponse
    from rediska_core.domain.models import ConversationListMember
    import json as _json
    import io

    # Query conversations
    conv_query = (
        db.query(Conversation)
        .filter(Conversation.deleted_at.is_(None))
    )
    if identity_id is not None:
        conv_query = conv_query.filter(Conversation.identity_id == identity_id)
    if test_only:
        conv_query = conv_query.filter(Conversation.external_conversation_id.like("[TEST]%"))
    if list_id is not None:
        conv_query = conv_query.filter(
            Conversation.id.in_(
                db.query(ConversationListMember.conversation_id)
                .filter(ConversationListMember.list_id == list_id)
            )
        )

    all_conversations = conv_query.order_by(Conversation.id).all()

    output_lines = []
    conv_count = 0

    for conv in all_conversations:
        # Load valid messages
        msg_query = (
            db.query(Message)
            .filter(
                Message.conversation_id == conv.id,
                Message.deleted_at.is_(None),
                Message.send_error.is_(None),
                Message.body_text.isnot(None),
                Message.body_text != "",
                Message.remote_visibility.in_(["visible", "unknown"]),
            )
            .order_by(Message.sent_at, Message.id)
        )
        raw_messages = msg_query.all()

        if not raw_messages:
            continue

        # Thread-aware ordering: group by thread, order threads by earliest message
        has_threads = any(m.thread_external_id for m in raw_messages)
        if has_threads:
            from collections import OrderedDict
            threads: dict[str, list] = OrderedDict()
            no_thread: list = []
            for m in raw_messages:
                tid = m.thread_external_id or ""
                if tid:
                    threads.setdefault(tid, []).append(m)
                else:
                    no_thread.append(m)
            sorted_threads = sorted(threads.values(), key=lambda msgs: msgs[0].sent_at)
            ordered_messages = []
            for thread_msgs in sorted_threads:
                ordered_messages.extend(thread_msgs)
            ordered_messages.extend(no_thread)
        else:
            ordered_messages = raw_messages

        # Map roles and filter
        turns = []
        for m in ordered_messages:
            if m.direction == "system":
                continue
            role = "assistant" if m.direction == "out" else "user"
            text = (m.body_text or "").strip()
            if not text:
                continue
            turns.append({"role": role, "content": text})

        if not turns:
            continue

        # Merge consecutive same-role messages
        merged = [turns[0]]
        for t in turns[1:]:
            if t["role"] == merged[-1]["role"]:
                merged[-1]["content"] += "\n\n" + t["content"]
            else:
                merged.append(t)

        # Ensure starts with user
        if merged[0]["role"] != "user":
            merged.insert(0, {"role": "user", "content": "[conversation initiated]"})

        # Ensure ends with assistant — drop trailing user turns
        while merged and merged[-1]["role"] == "user":
            merged.pop()

        if not merged:
            continue

        # Need at least one user-assistant exchange
        has_user = any(t["role"] == "user" for t in merged)
        has_assistant = any(t["role"] == "assistant" for t in merged)
        if not has_user or not has_assistant:
            continue

        # Prepend system prompt
        chatml_messages = [{"role": "system", "content": system_prompt}] + merged

        output_lines.append(_json.dumps({"conversations": chatml_messages}, ensure_ascii=False))
        conv_count += 1

    # Audit log
    audit_entry = AuditLog(
        ts=datetime.now(timezone.utc),
        actor="user",
        action_type="dataset.export",
        result="ok",
        entity_type="conversation",
        entity_id=0,
        request_json={
            "format": format,
            "conversation_count": conv_count,
            "test_only": test_only,
            "identity_id": identity_id,
            "list_id": list_id,
        },
    )
    db.add(audit_entry)
    db.commit()

    content = "\n".join(output_lines) + ("\n" if output_lines else "")
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"dataset-{date_str}.jsonl"

    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="application/jsonl",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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

    # Get the counterpart's latest post title for Reddit compose link
    from rediska_core.domain.models import ProfileItem
    last_post = (
        db.query(ProfileItem.link_title)
        .filter(
            ProfileItem.account_id == conversation.counterpart_account_id,
            ProfileItem.item_type == "post",
            ProfileItem.link_title.isnot(None),
            ProfileItem.deleted_at.is_(None),
        )
        .order_by(desc(ProfileItem.item_created_at))
        .first()
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
            is_starred=conversation.counterpart_account.is_starred,
        ),
        last_activity_at=conversation.last_activity_at,
        counterpart_last_post_title=last_post[0] if last_post else None,
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
            send_error=msg.send_error,
            identity_id=msg.identity_id,
            external_message_id=msg.external_message_id,
            thread_external_id=msg.thread_external_id,
            parent_external_message_id=msg.parent_external_message_id,
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
    """Retry sending a failed or pending message.

    Only messages with 'unknown' or 'send_failed' visibility can be retried.
    This is a manual action to handle send failures.
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


@router.get(
    "/{conversation_id}/export",
    summary="Export conversation as HTML",
    description="Download a self-contained HTML file of the conversation.",
)
async def export_conversation_html(
    conversation_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """Export a conversation as a self-contained HTML file."""
    from datetime import datetime, timezone
    from fastapi.responses import HTMLResponse
    from html import escape

    # Load conversation with counterpart
    conversation = (
        db.query(Conversation)
        .options(joinedload(Conversation.counterpart_account))
        .filter_by(id=conversation_id)
        .filter(Conversation.deleted_at.is_(None))
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    identity = db.query(Identity).filter_by(id=conversation.identity_id, is_active=True).first()
    if not identity:
        raise HTTPException(status_code=403, detail="Access denied")

    # Load ALL messages ordered by sent_at ASC, excluding soft-deleted
    messages = (
        db.query(Message)
        .filter_by(conversation_id=conversation_id)
        .filter(Message.deleted_at.is_(None))
        .order_by(Message.sent_at, Message.id)
        .all()
    )

    # Eager-load attachments
    message_ids = [m.id for m in messages]
    attachments_by_msg: dict[int, list[Attachment]] = {}
    if message_ids:
        all_atts = (
            db.query(Attachment)
            .filter(Attachment.message_id.in_(message_ids))
            .filter(Attachment.remote_visibility != "removed")
            .all()
        )
        for att in all_atts:
            attachments_by_msg.setdefault(att.message_id, []).append(att)

    counterpart_username = conversation.counterpart_account.external_username
    identity_name = identity.display_name or "You"
    export_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    filename_date = datetime.now(timezone.utc).strftime("%Y%m%d")

    # Collect unique dates for calendar
    date_set = set()
    for msg in messages:
        if msg.sent_at:
            date_set.add(msg.sent_at.strftime("%Y-%m-%d"))

    # Build message HTML
    messages_html = ""
    prev_date = None
    for msg in messages:
        ts = msg.sent_at
        iso_ts = ts.isoformat() + "Z" if ts else ""
        time_display = ts.strftime("%I:%M %p") if ts else ""
        date_display = ts.strftime("%b %d, %Y") if ts else ""
        date_key = ts.strftime("%Y-%m-%d") if ts else ""
        full_display = f"{date_display} {time_display}"

        # Insert date separator
        if date_key and date_key != prev_date:
            messages_html += f'<div class="date-sep" id="date-{date_key}"><span>{date_display}</span></div>\n'
            prev_date = date_key

        body = escape(msg.body_text or "")
        body = body.replace("\n", "<br>")

        atts = attachments_by_msg.get(msg.id, [])
        att_html = ""
        for att in atts:
            att_html += f'<div class="att">[{escape(att.mime_type)} attachment, {att.size_bytes} bytes]</div>'

        # Status badges
        badge = ""
        if msg.remote_visibility == "deleted_by_author":
            badge = '<span class="badge badge-del">Deleted</span>'
        elif msg.remote_visibility == "unknown":
            badge = '<span class="badge badge-pending">Pending</span>'
        elif msg.remote_visibility == "send_failed":
            badge = '<span class="badge badge-fail">Failed</span>'

        # Threading data attributes
        thread_id = escape(msg.thread_external_id or "")
        parent_id = escape(msg.parent_external_message_id or "")
        thread_attrs = f' data-thread="{thread_id}" data-parent="{parent_id}"' if thread_id else ""

        # Thread indicator CSS class
        thread_cls = " threaded" if thread_id else ""

        if msg.direction == "system":
            messages_html += f'<div class="msg system" data-date="{date_key}" data-text=""{thread_attrs}><div class="pill">{body}</div></div>\n'
        elif msg.direction == "out":
            messages_html += f'''<div class="msg out{thread_cls}" data-date="{date_key}" data-text=""{thread_attrs}>
  <div class="sender">You ({escape(identity_name)})</div>
  <div class="bubble out-bubble">{body}{att_html}</div>
  <div class="meta"><span class="ts" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'">{full_display}</span><span class="iso" style="display:none">{iso_ts}</span> {badge}</div>
</div>\n'''
        else:
            messages_html += f'''<div class="msg in{thread_cls}" data-date="{date_key}" data-text=""{thread_attrs}>
  <div class="sender">u/{escape(counterpart_username)}</div>
  <div class="bubble in-bubble">{body}{att_html}</div>
  <div class="meta"><span class="ts" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'">{full_display}</span><span class="iso" style="display:none">{iso_ts}</span> {badge}</div>
</div>\n'''

    # Serialize dates as JSON for JS calendar
    import json as _json
    dates_json = _json.dumps(sorted(date_set))

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Conversation with u/{escape(counterpart_username)}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f5f5f5;color:#1a1a1a;margin:0;padding:0}}
.app-header{{position:sticky;top:0;z-index:100;background:#fff;border-bottom:1px solid #e5e7eb;padding:12px 20px;display:flex;align-items:center;gap:12px}}
.app-header h1{{font-size:1.1rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex-shrink:1;min-width:0}}
.header-spacer{{flex:1}}
.cal-toggle{{background:none;border:1px solid #d1d5db;border-radius:8px;padding:6px 10px;cursor:pointer;font-size:0.85rem;display:flex;align-items:center;gap:4px;color:#374151;white-space:nowrap}}
.cal-toggle:hover{{background:#f3f4f6}}
.cal-toggle svg{{width:16px;height:16px}}
.search-box{{display:flex;align-items:center;border:1px solid #d1d5db;border-radius:8px;padding:4px 10px;gap:6px;min-width:200px;max-width:320px}}
.search-box svg{{width:16px;height:16px;color:#9ca3af;flex-shrink:0}}
.search-box input{{border:none;outline:none;font-size:0.85rem;width:100%;background:transparent}}
.search-info{{font-size:0.75rem;color:#6b7280;white-space:nowrap;display:none}}
.search-info.active{{display:block}}
.search-nav{{display:none;gap:2px}}
.search-nav.active{{display:flex}}
.search-nav button{{background:none;border:none;cursor:pointer;padding:2px;color:#6b7280;font-size:1rem;line-height:1}}
.search-nav button:hover{{color:#374151}}
.content-wrap{{max-width:800px;margin:0 auto;padding:20px}}
.conv-info{{background:#fff;border-radius:12px;padding:16px 20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,0.1);font-size:0.85rem;color:#666}}
.messages{{display:flex;flex-direction:column;gap:12px}}
.msg{{display:flex;flex-direction:column;max-width:75%;transition:opacity 0.15s}}
.msg.out{{align-self:flex-end;align-items:flex-end}}
.msg.in{{align-self:flex-start;align-items:flex-start}}
.msg.system{{align-self:center}}
.msg.search-hidden{{display:none}}
.msg.search-dim{{opacity:0.2}}
.sender{{font-size:0.75rem;color:#888;margin-bottom:2px;padding:0 4px}}
.bubble{{padding:10px 14px;border-radius:16px;font-size:0.9rem;line-height:1.45;word-break:break-word}}
.out-bubble{{background:#3b82f6;color:#fff;border-bottom-right-radius:4px}}
.in-bubble{{background:#e5e7eb;color:#1a1a1a;border-bottom-left-radius:4px}}
.pill{{background:#e5e7eb;padding:6px 16px;border-radius:999px;font-size:0.8rem;color:#666}}
.meta{{font-size:0.75rem;color:#999;margin-top:3px;padding:0 4px}}
.ts{{cursor:pointer}}.ts:hover{{text-decoration:underline}}
.iso{{font-size:0.7rem;color:#aaa;margin-top:2px}}
.att{{font-size:0.8rem;margin-top:6px;padding:4px 8px;background:rgba(0,0,0,0.1);border-radius:4px}}
.badge{{font-size:0.7rem;padding:1px 6px;border-radius:4px;margin-left:4px}}
.badge-del{{background:#e5e7eb;color:#666}}
.badge-pending{{background:#fef3c7;color:#92400e}}
.badge-fail{{background:#fee2e2;color:#dc2626}}
.date-sep{{text-align:center;margin:16px 0 8px;font-size:0.8rem;color:#9ca3af}}
.date-sep span{{background:#f5f5f5;padding:2px 12px;border-radius:999px}}
.msg.threaded{{border-left:3px solid #d1d5db;padding-left:8px;margin-left:4px}}
.msg.threaded.out{{border-left:none;border-right:3px solid #93c5fd;padding-left:0;padding-right:8px;margin-left:0;margin-right:4px}}
mark{{background:#fde68a;color:inherit;border-radius:2px;padding:0 1px}}
.footer{{text-align:center;font-size:0.8rem;color:#999;margin-top:30px;padding:20px}}
/* Calendar panel */
.cal-overlay{{display:none;position:fixed;top:0;left:0;width:100%;height:100%;z-index:200}}
.cal-overlay.open{{display:flex}}
.cal-backdrop{{position:absolute;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.2)}}
.cal-panel{{position:relative;width:280px;background:#fff;height:100%;box-shadow:4px 0 20px rgba(0,0,0,0.12);padding:16px;overflow-y:auto;animation:slideIn 0.2s ease}}
@keyframes slideIn{{from{{transform:translateX(-100%)}}to{{transform:translateX(0)}}}}
.cal-head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}}
.cal-head button{{background:none;border:none;cursor:pointer;font-size:1.2rem;color:#374151;padding:4px 8px;border-radius:4px}}
.cal-head button:hover{{background:#f3f4f6}}
.cal-head span{{font-size:0.95rem;font-weight:600}}
.cal-grid{{display:grid;grid-template-columns:repeat(7,1fr);gap:2px;text-align:center}}
.cal-grid .day-label{{font-size:0.7rem;color:#9ca3af;padding:4px 0;font-weight:500}}
.cal-grid .day{{font-size:0.8rem;padding:6px 2px;border-radius:6px;cursor:default;color:#9ca3af;position:relative}}
.cal-grid .day.has-msg{{color:#1a1a1a;cursor:pointer;font-weight:500}}
.cal-grid .day.has-msg:hover{{background:#eff6ff}}
.cal-grid .day.has-msg::after{{content:'';position:absolute;bottom:2px;left:50%;transform:translateX(-50%);width:4px;height:4px;background:#3b82f6;border-radius:50%}}
.cal-grid .day.today{{background:#eff6ff;font-weight:600}}
.cal-close{{position:absolute;top:12px;right:12px;background:none;border:none;cursor:pointer;font-size:1.1rem;color:#6b7280}}
</style>
</head>
<body>
<div class="app-header">
  <button class="cal-toggle" onclick="toggleCal()" title="Calendar navigation">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
    Cal
  </button>
  <h1>u/{escape(counterpart_username)}</h1>
  <div class="header-spacer"></div>
  <div class="search-box">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
    <input type="text" id="searchInput" placeholder="Search messages..." oninput="doSearch(this.value)" onkeydown="searchKey(event)">
    <span class="search-info" id="searchInfo"></span>
    <div class="search-nav" id="searchNav">
      <button onclick="searchPrev()" title="Previous">&uarr;</button>
      <button onclick="searchNext()" title="Next">&darr;</button>
    </div>
  </div>
</div>

<div class="cal-overlay" id="calOverlay">
  <div class="cal-backdrop" onclick="toggleCal()"></div>
  <div class="cal-panel">
    <button class="cal-close" onclick="toggleCal()">&times;</button>
    <div class="cal-head">
      <button onclick="calPrev()">&lsaquo;</button>
      <span id="calTitle"></span>
      <button onclick="calNext()">&rsaquo;</button>
    </div>
    <div class="cal-grid" id="calGrid"></div>
  </div>
</div>

<div class="content-wrap">
  <div class="conv-info">
    Identity: {escape(identity_name)} &middot; {len(messages)} messages &middot; Exported {export_date}
  </div>
  <div class="messages" id="messagesContainer">
{messages_html}
  </div>
  <div class="footer">Exported from Rediska on {export_date}</div>
</div>

<script>
(function(){{
/* Calendar */
var MSG_DATES={dates_json};
var dateSet=new Set(MSG_DATES);
var calMonth,calYear;
var now=new Date();
/* Start at earliest message date or today */
if(MSG_DATES.length>0){{var p=MSG_DATES[0].split('-');calYear=+p[0];calMonth=+p[1]-1}}
else{{calYear=now.getFullYear();calMonth=now.getMonth()}}

window.toggleCal=function(){{
  var o=document.getElementById('calOverlay');
  o.classList.toggle('open');
  if(o.classList.contains('open'))renderCal();
}};
window.calPrev=function(){{calMonth--;if(calMonth<0){{calMonth=11;calYear--}}renderCal()}};
window.calNext=function(){{calMonth++;if(calMonth>11){{calMonth=0;calYear++}}renderCal()}};

function pad(n){{return n<10?'0'+n:''+n}}
function renderCal(){{
  document.getElementById('calTitle').textContent=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][calMonth]+' '+calYear;
  var g=document.getElementById('calGrid');
  g.innerHTML='';
  var labels=['Su','Mo','Tu','We','Th','Fr','Sa'];
  for(var i=0;i<7;i++){{var d=document.createElement('div');d.className='day-label';d.textContent=labels[i];g.appendChild(d)}}
  var first=new Date(calYear,calMonth,1).getDay();
  var dim=new Date(calYear,calMonth+1,0).getDate();
  var todayStr=now.getFullYear()+'-'+pad(now.getMonth()+1)+'-'+pad(now.getDate());
  for(var i=0;i<first;i++){{var e=document.createElement('div');e.className='day';g.appendChild(e)}}
  for(var d=1;d<=dim;d++){{
    var el=document.createElement('div');
    el.className='day';
    el.textContent=d;
    var ds=calYear+'-'+pad(calMonth+1)+'-'+pad(d);
    if(ds===todayStr)el.classList.add('today');
    if(dateSet.has(ds)){{
      el.classList.add('has-msg');
      el.setAttribute('data-date',ds);
      el.onclick=function(){{var t=document.getElementById('date-'+this.getAttribute('data-date'));if(t){{t.scrollIntoView({{behavior:'smooth',block:'start'}});toggleCal()}}}};
    }}
    g.appendChild(el);
  }}
}}

/* Search */
var allMsgs=document.querySelectorAll('.msg');
var matchEls=[],matchIdx=-1;

function highlightTextNodes(el,re){{
  /* Walk text nodes and wrap matches in <mark> */
  var walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT,null,false);
  var nodes=[];
  while(walker.nextNode())nodes.push(walker.currentNode);
  for(var i=0;i<nodes.length;i++){{
    var node=nodes[i];
    var text=node.nodeValue;
    if(!re.test(text))continue;
    re.lastIndex=0;
    var frag=document.createDocumentFragment();
    var lastIdx=0,match;
    while((match=re.exec(text))!==null){{
      if(match.index>lastIdx)frag.appendChild(document.createTextNode(text.slice(lastIdx,match.index)));
      var mark=document.createElement('mark');
      mark.textContent=match[0];
      frag.appendChild(mark);
      lastIdx=re.lastIndex;
    }}
    if(lastIdx<text.length)frag.appendChild(document.createTextNode(text.slice(lastIdx)));
    node.parentNode.replaceChild(frag,node);
  }}
}}

function clearHighlights(el){{
  var marks=el.querySelectorAll('mark');
  for(var i=0;i<marks.length;i++){{
    var m=marks[i];
    var parent=m.parentNode;
    parent.replaceChild(document.createTextNode(m.textContent),m);
    parent.normalize();
  }}
}}

window.doSearch=function(q){{
  /* Clear previous highlights */
  allMsgs.forEach(function(m){{
    m.classList.remove('search-hidden','search-dim');
    var bub=m.querySelector('.bubble,.pill');
    if(bub)clearHighlights(bub);
  }});
  matchEls=[];matchIdx=-1;
  var info=document.getElementById('searchInfo');
  var nav=document.getElementById('searchNav');

  if(!q.trim()){{info.classList.remove('active');nav.classList.remove('active');
    /* Also un-hide date separators */
    document.querySelectorAll('.date-sep').forEach(function(d){{d.style.display=''}});
    return}}

  var ql=q.trim().toLowerCase();
  var re;
  try{{re=new RegExp('('+q.replace(/[.*+?^${{}}()|[\\]\\\\]/g,'\\\\$&')+')','gi')}}catch(e){{return}}

  allMsgs.forEach(function(m){{
    var bub=m.querySelector('.bubble,.pill');
    if(!bub){{m.classList.add('search-dim');return}}
    /* Use textContent for matching — avoids HTML entity issues (&#x27; etc.) */
    var txt=(bub.textContent||'').toLowerCase();
    if(txt.indexOf(ql)!==-1){{
      matchEls.push(m);
      /* Highlight matches by walking text nodes */
      highlightTextNodes(bub,re);
    }}else{{
      m.classList.add('search-dim');
    }}
  }});

  /* Hide date separators that have no visible messages after them */
  document.querySelectorAll('.date-sep').forEach(function(ds){{
    var next=ds.nextElementSibling;
    var hasVisible=false;
    while(next&&!next.classList.contains('date-sep')){{
      if(next.classList.contains('msg')&&!next.classList.contains('search-dim')&&!next.classList.contains('search-hidden'))hasVisible=true;
      next=next.nextElementSibling;
    }}
    ds.style.display=hasVisible?'':'none';
  }});

  if(matchEls.length>0){{
    matchIdx=0;scrollToMatch();
    info.textContent='1/'+matchEls.length;
  }}else{{
    info.textContent='0 results';
  }}
  info.classList.add('active');
  nav.classList.toggle('active',matchEls.length>1);
}};

function scrollToMatch(){{
  if(matchIdx<0||matchIdx>=matchEls.length)return;
  matchEls[matchIdx].scrollIntoView({{behavior:'smooth',block:'center'}});
  document.getElementById('searchInfo').textContent=(matchIdx+1)+'/'+matchEls.length;
}}

window.searchNext=function(){{if(matchEls.length===0)return;matchIdx=(matchIdx+1)%matchEls.length;scrollToMatch()}};
window.searchPrev=function(){{if(matchEls.length===0)return;matchIdx=(matchIdx-1+matchEls.length)%matchEls.length;scrollToMatch()}};
window.searchKey=function(e){{if(e.key==='Enter'){{e.shiftKey?searchPrev():searchNext();e.preventDefault()}}}}
}})();
</script>
</body>
</html>'''

    # Audit log
    audit_entry = AuditLog(
        ts=datetime.now(timezone.utc),
        actor="user",
        action_type="conversation.export",
        result="ok",
        entity_type="conversation",
        entity_id=conversation_id,
        request_json={"conversation_id": conversation_id, "message_count": len(messages)},
    )
    db.add(audit_entry)
    db.commit()

    filename = f"conversation-{counterpart_username}-{filename_date}.html"
    return HTMLResponse(
        content=html,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/{conversation_id}/messages/{message_id}/remote-delete",
    summary="Delete a single message from Reddit",
    description="Delete an outgoing message from Reddit. Local copy is preserved as deleted_by_author.",
)
async def remote_delete_message(
    conversation_id: int,
    message_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """Delete a single outgoing message from Reddit."""
    from datetime import datetime, timezone

    # Load the message
    msg = (
        db.query(Message)
        .filter_by(id=message_id, conversation_id=conversation_id)
        .filter(Message.deleted_at.is_(None))
        .first()
    )
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    # Validate: must be outgoing
    if msg.direction != "out":
        raise HTTPException(status_code=400, detail="Can only delete outgoing messages")

    # Validate: must be visible
    if msg.remote_visibility != "visible":
        raise HTTPException(
            status_code=409,
            detail=f"Message remote_visibility is '{msg.remote_visibility}', expected 'visible'",
        )

    # Validate: must have external_message_id
    if not msg.external_message_id:
        raise HTTPException(status_code=400, detail="Message has no external ID, cannot delete from Reddit")

    # Get Reddit adapter
    from rediska_core.api.routes.leads import get_reddit_adapter
    adapter = get_reddit_adapter(db)
    if not adapter:
        raise HTTPException(status_code=503, detail="Reddit adapter unavailable (check credentials)")

    # Call Reddit delete
    result = await adapter.delete_message(msg.external_message_id)

    if not result.success:
        raise HTTPException(
            status_code=502,
            detail=f"Reddit API error: {result.error_message}",
        )

    # Update local record
    msg.remote_visibility = "deleted_by_author"
    msg.remote_deleted_at = datetime.now(timezone.utc)

    # Audit log
    audit_entry = AuditLog(
        ts=datetime.now(timezone.utc),
        actor="user",
        action_type="message.remote_delete",
        result="ok",
        entity_type="message",
        entity_id=message_id,
        request_json={
            "conversation_id": conversation_id,
            "message_id": message_id,
            "external_message_id": msg.external_message_id,
        },
    )
    db.add(audit_entry)
    db.commit()

    return {"message": "Message deleted from Reddit", "message_id": message_id}


@router.post(
    "/{conversation_id}/messages/remote-delete-batch",
    summary="Batch delete messages from Reddit (scrub conversation)",
    description="Delete multiple outgoing messages from Reddit in one conversation.",
)
async def remote_delete_batch(
    conversation_id: int,
    current_user: CurrentUser,
    db: DBSession,
    body: RemoteDeleteBatchRequest,
):
    """Batch delete outgoing messages from Reddit within a single conversation."""
    from datetime import datetime, timezone
    import asyncio

    # Verify conversation exists
    conversation = db.query(Conversation).filter_by(id=conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Get eligible messages
    if body.all:
        # All deletable outgoing messages in this conversation
        candidates = (
            db.query(Message)
            .filter_by(conversation_id=conversation_id, direction="out", remote_visibility="visible")
            .filter(Message.deleted_at.is_(None))
            .filter(Message.external_message_id.isnot(None))
            .order_by(Message.sent_at)
            .all()
        )
    elif body.message_ids:
        candidates = (
            db.query(Message)
            .filter(
                Message.id.in_(body.message_ids),
                Message.conversation_id == conversation_id,
            )
            .filter(Message.deleted_at.is_(None))
            .all()
        )
    else:
        raise HTTPException(status_code=400, detail="Provide message_ids or set all=True")

    if not candidates:
        return RemoteDeleteBatchResponse(total=0, deleted=0, failed=0, skipped=0, results=[])

    # Get Reddit adapter
    from rediska_core.api.routes.leads import get_reddit_adapter
    adapter = get_reddit_adapter(db)
    if not adapter:
        raise HTTPException(status_code=503, detail="Reddit adapter unavailable (check credentials)")

    results: list[RemoteDeleteResultItem] = []
    deleted_count = 0
    failed_count = 0
    skipped_count = 0

    for msg in candidates:
        # Skip non-eligible
        if msg.direction != "out" or msg.remote_visibility != "visible" or not msg.external_message_id:
            results.append(RemoteDeleteResultItem(
                message_id=msg.id,
                success=False,
                error="Not eligible for remote delete",
            ))
            skipped_count += 1
            continue

        # Call Reddit delete
        delete_result = await adapter.delete_message(msg.external_message_id)

        if delete_result.success:
            msg.remote_visibility = "deleted_by_author"
            msg.remote_deleted_at = datetime.now(timezone.utc)
            deleted_count += 1
            results.append(RemoteDeleteResultItem(message_id=msg.id, success=True))
        else:
            failed_count += 1
            results.append(RemoteDeleteResultItem(
                message_id=msg.id,
                success=False,
                error=delete_result.error_message,
            ))

        # Rate limit delay between deletes (1 second)
        if msg != candidates[-1]:
            await asyncio.sleep(1)

    # Audit log
    audit_entry = AuditLog(
        ts=datetime.now(timezone.utc),
        actor="user",
        action_type="message.remote_delete_batch",
        result="ok",
        entity_type="conversation",
        entity_id=conversation_id,
        request_json={
            "conversation_id": conversation_id,
            "all": body.all,
            "message_ids": body.message_ids,
        },
        response_json={
            "total": len(candidates),
            "deleted": deleted_count,
            "failed": failed_count,
            "skipped": skipped_count,
        },
    )
    db.add(audit_entry)
    db.commit()

    return RemoteDeleteBatchResponse(
        total=len(candidates),
        deleted=deleted_count,
        failed=failed_count,
        skipped=skipped_count,
        results=results,
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
        is_starred=author_external_account.is_starred,
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


@router.post(
    "/initiate/by-username",
    response_model=ConversationSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Initiate a conversation by username",
    description="Create or get a conversation with a user by their username. "
    "Creates an ExternalAccount if the user is not yet known.",
)
async def initiate_conversation_by_username(
    request: InitiateByUsernameRequest,
    current_user: CurrentUser,
    db: DBSession,
):
    """Initiate a conversation with a user by username.

    This endpoint:
    1. Looks up or creates an ExternalAccount for the given username
    2. Gets the default identity for the provider
    3. Gets or creates a Conversation between identity and account
    4. Returns the conversation details
    """
    from datetime import datetime, timezone

    username = request.username.strip()
    provider_id = request.provider_id.strip()

    if not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username must not be empty",
        )

    # Look up or create the ExternalAccount
    external_account = (
        db.query(ExternalAccount)
        .filter(
            ExternalAccount.provider_id == provider_id,
            ExternalAccount.external_username == username,
        )
        .first()
    )

    if not external_account:
        external_account = ExternalAccount(
            provider_id=provider_id,
            external_username=username,
            remote_status="unknown",
            analysis_state="not_analyzed",
            contact_state="not_contacted",
            engagement_state="not_engaged",
        )
        db.add(external_account)
        db.flush()

    # Get the default identity
    identity = (
        db.query(Identity)
        .filter_by(provider_id=provider_id, is_active=True, is_default=True)
        .first()
    )

    if not identity:
        identity = (
            db.query(Identity)
            .filter_by(provider_id=provider_id, is_active=True)
            .first()
        )

    if not identity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active identity configured",
        )

    # Get or create conversation
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.provider_id == provider_id,
            Conversation.identity_id == identity.id,
            Conversation.counterpart_account_id == external_account.id,
        )
        .first()
    )

    if not conversation:
        conversation = Conversation(
            provider_id=provider_id,
            external_conversation_id=f"{provider_id}:pair:{identity.external_username.lower()}:{username.lower()}",
            counterpart_account_id=external_account.id,
            identity_id=identity.id,
            last_activity_at=datetime.now(timezone.utc),
        )
        db.add(conversation)
        db.flush()

        audit_entry = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="conversation.initiate",
            result="ok",
            entity_type="conversation",
            entity_id=conversation.id,
            request_json={"username": username, "provider_id": provider_id},
            response_json={"conversation_id": conversation.id},
        )
        db.add(audit_entry)
        db.commit()

    counterpart = CounterpartResponse(
        id=external_account.id,
        external_username=external_account.external_username,
        external_user_id=external_account.external_user_id,
        remote_status=external_account.remote_status,
        is_starred=external_account.is_starred,
    )

    return ConversationSummaryResponse(
        id=conversation.id,
        provider_id=conversation.provider_id,
        identity_id=identity.id,
        external_conversation_id=conversation.external_conversation_id,
        counterpart=counterpart,
        last_activity_at=conversation.last_activity_at,
        unread_count=0,
        archived_at=conversation.archived_at,
        created_at=conversation.created_at,
    )
