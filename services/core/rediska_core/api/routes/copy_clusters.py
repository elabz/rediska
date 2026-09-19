"""Copy cluster API routes (post copy detection).

Provides endpoints for:
- GET  /copy-clusters - List clusters (kind/decision filters, keyset cursor)
- GET  /copy-clusters/{id} - Members with what we already hold per author
- POST /copy-clusters/{id}/decision - Record the human's reading of a cluster

A decision never changes a lead, an analysis or a ban; it writes ``audit_log``.
"""

from collections import defaultdict
from typing import Any, Callable, Iterable, Optional

from fastapi import APIRouter, HTTPException, Query, status

from rediska_core.api.deps import CurrentUser, DBSession
from rediska_core.api.schemas.copy_clusters import (
    CopyInfo,
    CopyClusterDecisionRequest,
    CopyClusterDetailResponse,
    CopyClusterListResponse,
    CopyClusterMemberResponse,
    CopyClusterSummary,
)
from rediska_core.domain.models import CopyCluster
from rediska_core.domain.services import post_copy

router = APIRouter(prefix="/copy-clusters", tags=["copy-clusters"])

VALID_KINDS = set(post_copy.KINDS) | set(post_copy.DECISIONS)
VALID_DECISIONS = set(post_copy.DECISIONS) | {"none"}


def attach_copy(
    db: Any,
    items: Iterable[Any],
    provider_of: Callable[[Any], str] = lambda item: "reddit",
) -> None:
    """Set ``copy_info`` on read-model items, one lookup per provider per page."""
    by_provider: dict[str, list[Any]] = defaultdict(list)
    for item in items:
        by_provider[provider_of(item) or "reddit"].append(item)
    for provider_id, group in by_provider.items():
        summaries = post_copy.copy_summaries(
            db, provider_id, [i.external_post_id for i in group]
        )
        for item in group:
            found = summaries.get(item.external_post_id)
            item.copy_info = CopyInfo(**found) if found else None


def summary(cluster: CopyCluster) -> CopyClusterSummary:
    return CopyClusterSummary(
        id=cluster.id,
        provider_id=cluster.provider_id,
        kind=cluster.effective_kind,
        computed_kind=cluster.kind,
        decision=cluster.decision,
        decision_notes=cluster.decision_notes,
        decided_at=cluster.decided_at,
        author_count=cluster.author_count,
        member_count=cluster.member_count,
        avg_char_len=cluster.avg_char_len or 0,
        handled=bool(cluster.handled),
        first_posted_at=cluster.first_posted_at,
        last_posted_at=cluster.last_posted_at,
        created_at=cluster.created_at,
    )


@router.get("", response_model=CopyClusterListResponse, summary="List copy clusters")
async def list_copy_clusters(
    current_user: CurrentUser,
    db: DBSession,
    kind: Optional[str] = Query(None, description="Effective kind"),
    decision: Optional[str] = Query(None, description="A decision, or 'none' for undecided"),
    author: Optional[str] = Query(None, description="Only clusters this username posted in"),
    handled: Optional[bool] = Query(None, description="Only handled (true) or unhandled spam rings"),
    provider_id: Optional[str] = Query(None),
    cursor: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    if kind and kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"Invalid kind: {kind}")
    if decision and decision not in VALID_DECISIONS:
        raise HTTPException(status_code=400, detail=f"Invalid decision: {decision}")
    try:
        cursor_id = int(cursor) if cursor else None
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid cursor: {cursor}")

    clusters, next_id = post_copy.list_clusters(
        db, provider_id=provider_id, kind=kind, decision=decision, author=author,
        handled=handled, cursor=cursor_id, limit=limit,
    )
    return CopyClusterListResponse(
        items=[summary(c) for c in clusters],
        next_cursor=str(next_id) if next_id else None,
    )


@router.get("/{cluster_id}", response_model=CopyClusterDetailResponse, summary="Cluster detail")
async def get_copy_cluster(cluster_id: int, current_user: CurrentUser, db: DBSession):
    try:
        detail = post_copy.cluster_detail(db, cluster_id)
    except post_copy.CopyClusterNotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return CopyClusterDetailResponse(
        cluster=summary(detail["cluster"]),
        members=[CopyClusterMemberResponse(**m) for m in detail["members"]],
    )


@router.post(
    "/{cluster_id}/decision",
    response_model=CopyClusterSummary,
    summary="Record a human decision on a cluster",
)
async def decide_copy_cluster(
    cluster_id: int,
    request: CopyClusterDecisionRequest,
    current_user: CurrentUser,
    db: DBSession,
):
    try:
        cluster = post_copy.decide(db, cluster_id, request.decision, request.notes)
    except post_copy.CopyClusterNotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except post_copy.CopyDecisionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    db.commit()
    return summary(cluster)
