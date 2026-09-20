"""Probable-rewrite suggestion routes.

Provides:
- GET  /copy-suggestions - pending (or decided) semantic near-copies
- POST /copy-suggestions/{id}/accept - join the two posts into a copy cluster
- POST /copy-suggestions/{id}/reject - record that the pair is not a copy

Accept and reject both write `audit_log`. Nothing here happens automatically:
a suggestion exists precisely so that a machine's guess waits for a person.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from rediska_core.api.deps import CurrentUser, DBSession
from rediska_core.domain.services import copy_suggestions

router = APIRouter(prefix="/copy-suggestions", tags=["copy-suggestions"])


class CopySuggestionResponse(BaseModel):
    """One probable rewrite awaiting (or carrying) a decision."""

    id: int
    provider_id: str
    source_doc_type: str
    source_entity_id: int
    source_external_post_id: str
    source_author: Optional[str] = None
    match_doc_type: str
    match_entity_id: int
    match_external_post_id: str
    match_author: Optional[str] = None
    similarity: float
    embedding_model: Optional[str] = None
    status: str
    cluster_id: Optional[int] = None
    decided_at: Optional[str] = None
    created_at: Optional[str] = None


class CopySuggestionListResponse(BaseModel):
    items: list[CopySuggestionResponse]


def to_response(row) -> CopySuggestionResponse:
    return CopySuggestionResponse(
        id=row.id,
        provider_id=row.provider_id,
        source_doc_type=row.source_doc_type,
        source_entity_id=row.source_entity_id,
        source_external_post_id=row.source_external_post_id,
        source_author=row.source_author,
        match_doc_type=row.match_doc_type,
        match_entity_id=row.match_entity_id,
        match_external_post_id=row.match_external_post_id,
        match_author=row.match_author,
        similarity=row.similarity,
        embedding_model=row.embedding_model,
        status=row.status,
        cluster_id=row.cluster_id,
        decided_at=row.decided_at.isoformat() if row.decided_at else None,
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


@router.get(
    "",
    response_model=CopySuggestionListResponse,
    summary="List probable rewrites",
    description="Posts that read like an older post by a different author, "
                "highest similarity first. Undecided ones by default.",
)
async def list_suggestions(
    current_user: CurrentUser,
    db: DBSession,
    status_filter: str = Query(default="new", alias="status"),
    provider_id: Optional[str] = Query(default=None),
    external_post_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """List probable rewrites."""
    if status_filter not in (*copy_suggestions.STATUSES, "all"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": f"Unknown status {status_filter!r}"},
        )
    rows = copy_suggestions.list_suggestions(
        db,
        status=status_filter,
        provider_id=provider_id,
        external_post_id=external_post_id,
        limit=limit,
    )
    return CopySuggestionListResponse(items=[to_response(row) for row in rows])


class DecisionResponse(BaseModel):
    suggestion: CopySuggestionResponse
    message: str = Field(..., description="What the decision did")


@router.post(
    "/{suggestion_id}/accept",
    response_model=DecisionResponse,
    summary="Accept a probable rewrite",
    description="Join the two posts into a copy cluster, as a fingerprint match "
                "would have. Audited; never automatic.",
)
async def accept_suggestion(
    suggestion_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """Accept a suggestion and cluster the two posts."""
    try:
        row = copy_suggestions.accept(db, suggestion_id, actor="user")
    except copy_suggestions.SuggestionNotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": str(e)})
    except copy_suggestions.SuggestionAlreadyDecided as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": str(e)})
    db.commit()
    return DecisionResponse(
        suggestion=to_response(row),
        message=f"Both posts are now in copy cluster #{row.cluster_id}.",
    )


@router.post(
    "/{suggestion_id}/reject",
    response_model=DecisionResponse,
    summary="Reject a probable rewrite",
    description="Record that these two posts are not the same ad. The pair is "
                "not suggested again. Audited.",
)
async def reject_suggestion(
    suggestion_id: int,
    current_user: CurrentUser,
    db: DBSession,
):
    """Reject a suggestion; the two posts stay unrelated."""
    try:
        row = copy_suggestions.reject(db, suggestion_id, actor="user")
    except copy_suggestions.SuggestionNotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": str(e)})
    except copy_suggestions.SuggestionAlreadyDecided as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": str(e)})
    db.commit()
    return DecisionResponse(
        suggestion=to_response(row),
        message="Recorded. These two posts will not be suggested again.",
    )
