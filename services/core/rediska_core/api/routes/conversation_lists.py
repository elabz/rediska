"""Conversation lists API routes.

Provides endpoints for:
- GET /lists - List all conversation lists
- POST /lists - Create a new list
- PUT /lists/{id} - Rename a list
- DELETE /lists/{id} - Delete a list
- POST /lists/{id}/conversations/{conversation_id} - Add conversation to list
- DELETE /lists/{id}/conversations/{conversation_id} - Remove conversation from list
- GET /lists/{id}/conversations - List conversations in a list
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func

from rediska_core.api.deps import CurrentUser, DBSession
from rediska_core.api.schemas.conversation_list import (
    ConversationListCreate,
    ConversationListResponse,
    ConversationListsResponse,
    ConversationListUpdate,
)
from rediska_core.domain.models import (
    AuditLog,
    Conversation,
    ConversationList,
    ConversationListMember,
)

router = APIRouter(prefix="/lists", tags=["conversation-lists"])


@router.get(
    "",
    response_model=ConversationListsResponse,
    summary="List all conversation lists",
)
async def get_lists(current_user: CurrentUser, db: DBSession):
    """Get all conversation lists with conversation counts."""
    lists = db.query(ConversationList).order_by(ConversationList.name).all()

    result = []
    for lst in lists:
        count = (
            db.query(func.count(ConversationListMember.id))
            .filter(ConversationListMember.list_id == lst.id)
            .scalar()
        )
        result.append(
            ConversationListResponse(
                id=lst.id,
                name=lst.name,
                conversation_count=count or 0,
                created_at=lst.created_at,
                updated_at=lst.updated_at,
            )
        )

    return ConversationListsResponse(lists=result)


@router.post(
    "",
    response_model=ConversationListResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a conversation list",
)
async def create_list(
    body: ConversationListCreate,
    current_user: CurrentUser,
    db: DBSession,
):
    """Create a new conversation list."""
    existing = (
        db.query(ConversationList)
        .filter(ConversationList.name == body.name)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"List '{body.name}' already exists",
        )

    now = datetime.now(timezone.utc)
    lst = ConversationList(name=body.name, created_at=now, updated_at=now)
    db.add(lst)

    audit = AuditLog(
        ts=now,
        actor="user",
        action_type="list.create",
        result="ok",
        entity_type="conversation_list",
        entity_id=0,
        request_json={"name": body.name},
    )
    db.add(audit)
    db.commit()
    db.refresh(lst)

    audit.entity_id = lst.id
    db.commit()

    return ConversationListResponse(
        id=lst.id,
        name=lst.name,
        conversation_count=0,
        created_at=lst.created_at,
        updated_at=lst.updated_at,
    )


@router.put(
    "/{list_id}",
    response_model=ConversationListResponse,
    summary="Rename a conversation list",
)
async def update_list(
    list_id: int,
    body: ConversationListUpdate,
    current_user: CurrentUser,
    db: DBSession,
):
    """Rename a conversation list."""
    lst = db.query(ConversationList).filter_by(id=list_id).first()
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    # Check name uniqueness
    dup = (
        db.query(ConversationList)
        .filter(ConversationList.name == body.name, ConversationList.id != list_id)
        .first()
    )
    if dup:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"List '{body.name}' already exists",
        )

    lst.name = body.name
    lst.updated_at = datetime.now(timezone.utc)

    db.add(
        AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="list.update",
            result="ok",
            entity_type="conversation_list",
            entity_id=list_id,
            request_json={"name": body.name},
        )
    )
    db.commit()

    count = (
        db.query(func.count(ConversationListMember.id))
        .filter(ConversationListMember.list_id == lst.id)
        .scalar()
    )
    return ConversationListResponse(
        id=lst.id,
        name=lst.name,
        conversation_count=count or 0,
        created_at=lst.created_at,
        updated_at=lst.updated_at,
    )


@router.delete(
    "/{list_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a conversation list",
)
async def delete_list(list_id: int, current_user: CurrentUser, db: DBSession):
    """Delete a conversation list (does not delete conversations)."""
    lst = db.query(ConversationList).filter_by(id=list_id).first()
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    db.add(
        AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="list.delete",
            result="ok",
            entity_type="conversation_list",
            entity_id=list_id,
            request_json={"name": lst.name},
        )
    )
    db.delete(lst)
    db.commit()

    return {"message": "List deleted", "id": list_id}


@router.post(
    "/{list_id}/conversations/{conversation_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Add conversation to list",
)
async def add_conversation_to_list(
    list_id: int,
    conversation_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """Add a conversation to a list."""
    lst = db.query(ConversationList).filter_by(id=list_id).first()
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    conv = (
        db.query(Conversation)
        .filter_by(id=conversation_id)
        .filter(Conversation.deleted_at.is_(None))
        .first()
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    existing = (
        db.query(ConversationListMember)
        .filter_by(list_id=list_id, conversation_id=conversation_id)
        .first()
    )
    if existing:
        return {"message": "Already in list", "list_id": list_id, "conversation_id": conversation_id}

    member = ConversationListMember(
        list_id=list_id,
        conversation_id=conversation_id,
        added_at=datetime.now(timezone.utc),
    )
    db.add(member)
    db.commit()

    return {"message": "Added to list", "list_id": list_id, "conversation_id": conversation_id}


@router.delete(
    "/{list_id}/conversations/{conversation_id}",
    summary="Remove conversation from list",
)
async def remove_conversation_from_list(
    list_id: int,
    conversation_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """Remove a conversation from a list."""
    member = (
        db.query(ConversationListMember)
        .filter_by(list_id=list_id, conversation_id=conversation_id)
        .first()
    )
    if not member:
        raise HTTPException(status_code=404, detail="Conversation not in this list")

    db.delete(member)
    db.commit()

    return {"message": "Removed from list", "list_id": list_id, "conversation_id": conversation_id}


@router.get(
    "/{list_id}/conversation-ids",
    summary="Get conversation IDs in a list",
)
async def get_list_conversation_ids(
    list_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """Get all conversation IDs belonging to a list."""
    lst = db.query(ConversationList).filter_by(id=list_id).first()
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    members = (
        db.query(ConversationListMember.conversation_id)
        .filter(ConversationListMember.list_id == list_id)
        .all()
    )
    return {"list_id": list_id, "conversation_ids": [m[0] for m in members]}
