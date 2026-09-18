"""Scout Watches API routes.

Provides endpoints for:
- POST /scout-watches - Create a scout watch
- GET /scout-watches - List all watches
- GET /scout-watches/{id} - Get watch by ID
- PUT /scout-watches/{id} - Update a watch
- DELETE /scout-watches/{id} - Delete a watch
- POST /scout-watches/{id}/run - Trigger a manual run
- GET /scout-watches/{id}/runs - Get run history
- GET /scout-watches/needs-review - Cross-watch needs-review triage queue
- POST /scout-watches/posts/{post_id}/dismiss - Dismiss a needs-review post
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from celery import Celery
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from rediska_core.api.deps import CurrentUser, get_db
from rediska_core.config import get_settings
from rediska_core.api.schemas.scout_watch import (
    NeedsReviewListResponse,
    NeedsReviewPostResponse,
    ScoutWatchCreate,
    ScoutWatchListResponse,
    ScoutWatchPostAddToLeadsResponse,
    ScoutWatchPostDismissResponse,
    ScoutWatchPostReanalyzeResponse,
    ScoutWatchPostResponse,
    ScoutWatchResponse,
    ScoutWatchRunDetailResponse,
    ScoutWatchRunListResponse,
    ScoutWatchRunResponse,
    ScoutWatchRunTriggerResponse,
    ScoutWatchUpdate,
    WatchYield,
)
from rediska_core.domain.models import LeadAnalysis
from rediska_core.domain.models import AuditLog
from rediska_core.domain.services.scout_watch import (
    SKIP_DO_NOT_CONTACT,
    ScoutWatchError,
    ScoutWatchNotFoundError,
    ScoutWatchService,
)


router = APIRouter(prefix="/scout-watches", tags=["scout-watches"])
logger = logging.getLogger(__name__)


def _post_dimensions(post, db: Session) -> Optional[dict]:
    """A scout post's stored dimension outputs.

    Stored on the post for all posts since migration 011; older posts fall
    back to the linked LeadAnalysis dimension rows.
    """
    if post.dimension_results_json:
        return post.dimension_results_json
    if not post.analysis_id:
        return None

    from sqlalchemy.orm import joinedload

    analysis = (
        db.query(LeadAnalysis)
        .options(joinedload(LeadAnalysis.dimensions))
        .filter(LeadAnalysis.id == post.analysis_id)
        .first()
    )
    if not analysis or not analysis.dimensions:
        return None
    dimensions = {d.dimension: d.output_json for d in analysis.dimensions if d.output_json}
    return dimensions or None


# =============================================================================
# LIST WATCHES
# =============================================================================


@router.get("", response_model=ScoutWatchListResponse)
async def list_watches(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    provider_id: Optional[str] = Query(None, description="Filter by provider"),
) -> ScoutWatchListResponse:
    """List all scout watches.

    Args:
        is_active: Filter by active status (optional).
        provider_id: Filter by provider (optional).
        current_user: Authenticated user.
        db: Database session.

    Returns:
        List of scout watches.
    """
    from rediska_core.domain.services.source_discovery import SourceDiscoveryService

    service = ScoutWatchService(db)
    watches = service.list_watches(is_active=is_active, provider_id=provider_id)
    # Batched: a constant number of queries however many watches exist.
    yields = SourceDiscoveryService(db).watch_yields(w.id for w in watches)

    responses = []
    for w in watches:
        response = ScoutWatchResponse.model_validate(w)
        if w.id in yields:
            response.yield_30d = WatchYield(**yields[w.id])
        responses.append(response)
    return ScoutWatchListResponse(watches=responses)


# =============================================================================
# CREATE WATCH
# =============================================================================


@router.post("", response_model=ScoutWatchResponse, status_code=status.HTTP_201_CREATED)
async def create_watch(
    request: ScoutWatchCreate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> ScoutWatchResponse:
    """Create a new scout watch.

    Args:
        request: Watch creation request.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        Created watch.

    Raises:
        HTTPException: If validation fails.
    """
    service = ScoutWatchService(db)

    try:
        watch = service.create_watch(
            source_location=request.source_location,
            search_query=request.search_query,
            sort_by=request.sort_by,
            time_filter=request.time_filter,
            identity_id=request.identity_id,
            auto_analyze=request.auto_analyze,
            min_confidence=request.min_confidence,
        )

        # Audit log
        audit = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="scout_watch.create",
            entity_type="scout_watch",
            entity_id=watch.id,
            request_json={
                "source_location": request.source_location,
                "search_query": request.search_query,
            },
            result="ok",
        )
        db.add(audit)
        db.commit()

        return ScoutWatchResponse.model_validate(watch)

    except ScoutWatchError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# =============================================================================
# NEEDS-REVIEW QUEUE (declared before /{watch_id} so the path is not captured)
# =============================================================================


@router.get("/needs-review", response_model=NeedsReviewListResponse)
async def list_needs_review(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    cursor: Optional[str] = Query(default=None, description="Cursor from a previous page"),
    limit: int = Query(default=25, ge=1, le=100),
    watch_id: Optional[int] = Query(default=None, description="Restrict to one watch"),
    include_banned: bool = Query(default=False, description="Include banned authors"),
) -> NeedsReviewListResponse:
    """Scout posts analysed as needs_review that nobody has triaged, newest first."""
    service = ScoutWatchService(db)

    try:
        posts, next_cursor = service.list_needs_review(
            cursor=cursor, limit=limit, watch_id=watch_id, include_banned=include_banned
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid cursor: {cursor}"
        )

    watches = {}
    items: list[NeedsReviewPostResponse] = []
    for post in posts:
        if post.watch_id not in watches:
            watches[post.watch_id] = service.get_watch(post.watch_id)
        watch = watches[post.watch_id]
        item = NeedsReviewPostResponse.model_validate(post)
        item.analysis_dimensions = _post_dimensions(post, db)
        if watch:
            item.watch_source_location = watch.source_location
            item.watch_search_query = watch.search_query
            item.watch_min_confidence = watch.min_confidence
        items.append(item)

    from rediska_core.domain.services.analysis_evaluation import AnalysisEvaluationService

    AnalysisEvaluationService(db).attach_to_scout_posts(items)

    return NeedsReviewListResponse(
        items=items,
        total=service.count_needs_review(watch_id=watch_id, include_banned=include_banned),
        next_cursor=next_cursor,
    )


# =============================================================================
# GET WATCH
# =============================================================================


@router.get("/{watch_id}", response_model=ScoutWatchResponse)
async def get_watch(
    watch_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> ScoutWatchResponse:
    """Get a scout watch by ID.

    Args:
        watch_id: Watch ID.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        Scout watch details.

    Raises:
        HTTPException: If watch not found.
    """
    service = ScoutWatchService(db)

    try:
        watch = service.get_watch_or_raise(watch_id)
        return ScoutWatchResponse.model_validate(watch)
    except ScoutWatchNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watch not found: {watch_id}",
        )


# =============================================================================
# UPDATE WATCH
# =============================================================================


@router.put("/{watch_id}", response_model=ScoutWatchResponse)
async def update_watch(
    watch_id: int,
    request: ScoutWatchUpdate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> ScoutWatchResponse:
    """Update a scout watch.

    Args:
        watch_id: Watch ID.
        request: Update request.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        Updated watch.

    Raises:
        HTTPException: If watch not found or validation fails.
    """
    service = ScoutWatchService(db)

    try:
        watch = service.update_watch(
            watch_id=watch_id,
            search_query=request.search_query,
            sort_by=request.sort_by,
            time_filter=request.time_filter,
            identity_id=request.identity_id,
            is_active=request.is_active,
            auto_analyze=request.auto_analyze,
            min_confidence=request.min_confidence,
        )

        # Audit log
        audit = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="scout_watch.update",
            entity_type="scout_watch",
            entity_id=watch.id,
            request_json=request.model_dump(exclude_none=True),
            result="ok",
        )
        db.add(audit)
        db.commit()

        return ScoutWatchResponse.model_validate(watch)

    except ScoutWatchNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watch not found: {watch_id}",
        )
    except ScoutWatchError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# =============================================================================
# DELETE WATCH
# =============================================================================


@router.delete("/{watch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watch(
    watch_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    """Delete a scout watch.

    Args:
        watch_id: Watch ID.
        current_user: Authenticated user.
        db: Database session.

    Raises:
        HTTPException: If watch not found.
    """
    service = ScoutWatchService(db)

    try:
        service.delete_watch(watch_id)

        # Audit log
        audit = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="scout_watch.delete",
            entity_type="scout_watch",
            entity_id=watch_id,
            result="ok",
        )
        db.add(audit)
        db.commit()

    except ScoutWatchNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watch not found: {watch_id}",
        )


# =============================================================================
# TRIGGER MANUAL RUN
# =============================================================================


@router.post("/{watch_id}/run", response_model=ScoutWatchRunTriggerResponse)
async def trigger_run(
    watch_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> ScoutWatchRunTriggerResponse:
    """Trigger a manual watch run.

    This enqueues a Celery task to run the watch immediately.

    Args:
        watch_id: Watch ID.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        Run trigger response.

    Raises:
        HTTPException: If watch not found.
    """
    service = ScoutWatchService(db)

    try:
        watch = service.get_watch_or_raise(watch_id)

        # Create Celery client to send task
        settings = get_settings()
        celery_app = Celery(
            "rediska",
            broker=settings.celery_broker_url,
            backend=settings.celery_result_backend,
        )

        # Enqueue the task
        task = celery_app.send_task(
            "scout.run_single_watch",
            kwargs={"watch_id": watch_id},
            queue="scout",
        )

        # Audit log
        audit = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="scout_watch.manual_run",
            entity_type="scout_watch",
            entity_id=watch_id,
            response_json={"task_id": task.id},
            result="ok",
        )
        db.add(audit)
        db.commit()

        return ScoutWatchRunTriggerResponse(
            run_id=0,  # Will be created by the task
            status="queued",
            message=f"Watch run queued with task ID: {task.id}",
        )

    except ScoutWatchNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watch not found: {watch_id}",
        )
    except Exception as e:
        logger.exception(f"Failed to trigger watch run: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger watch run: {e}",
        )


# =============================================================================
# GET RUN HISTORY
# =============================================================================


@router.get("/{watch_id}/runs", response_model=ScoutWatchRunListResponse)
async def get_run_history(
    watch_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100, description="Maximum runs to return"),
    offset: int = Query(0, ge=0, description="Number of runs to skip"),
    has_new_posts: bool = Query(False, description="Filter to only runs with new posts"),
    has_leads: bool = Query(False, description="Filter to only runs with leads created"),
) -> ScoutWatchRunListResponse:
    """Get run history for a watch with pagination.

    Args:
        watch_id: Watch ID.
        limit: Maximum runs to return.
        offset: Number of runs to skip.
        has_new_posts: If true, only return runs where posts_new > 0.
        has_leads: If true, only return runs where leads_created > 0.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        Paginated list of watch runs.

    Raises:
        HTTPException: If watch not found.
    """
    service = ScoutWatchService(db)

    try:
        # Verify watch exists
        service.get_watch_or_raise(watch_id)

        runs = service.get_run_history(
            watch_id, limit=limit, offset=offset, has_new_posts=has_new_posts, has_leads=has_leads
        )
        total = service.count_runs(watch_id, has_new_posts=has_new_posts, has_leads=has_leads)

        return ScoutWatchRunListResponse(
            runs=[ScoutWatchRunResponse.model_validate(r) for r in runs],
            total=total,
            offset=offset,
            limit=limit,
        )

    except ScoutWatchNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watch not found: {watch_id}",
        )


# =============================================================================
# GET RUN DETAILS WITH POSTS
# =============================================================================


@router.get("/{watch_id}/runs/{run_id}", response_model=ScoutWatchRunDetailResponse)
async def get_run_detail(
    watch_id: int,
    run_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> ScoutWatchRunDetailResponse:
    """Get detailed run information including all posts.

    Args:
        watch_id: Watch ID.
        run_id: Run ID.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        Run details with all posts and their analysis results.

    Raises:
        HTTPException: If watch or run not found.
    """
    service = ScoutWatchService(db)

    try:
        # Verify watch exists
        service.get_watch_or_raise(watch_id)

        # Get run
        run = service.get_run(run_id)
        if not run or run.watch_id != watch_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run not found: {run_id}",
            )

        # Get posts for this run
        posts = service.get_posts_for_run(run_id)

        # Build post responses with analysis dimensions
        post_responses = []
        for post in posts:
            post_data = ScoutWatchPostResponse.model_validate(post)
            post_data.analysis_dimensions = _post_dimensions(post, db)
            post_responses.append(post_data)

        from rediska_core.domain.services.analysis_evaluation import AnalysisEvaluationService

        AnalysisEvaluationService(db).attach_to_scout_posts(post_responses)

        return ScoutWatchRunDetailResponse(
            run=ScoutWatchRunResponse.model_validate(run),
            posts=post_responses,
        )

    except ScoutWatchNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watch not found: {watch_id}",
        )


# =============================================================================
# DISMISS NEEDS-REVIEW POST
# =============================================================================


@router.post(
    "/posts/{post_id}/dismiss",
    response_model=ScoutWatchPostDismissResponse,
)
async def dismiss_post(
    post_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> ScoutWatchPostDismissResponse:
    """Dismiss a needs-review post: it leaves the queue and no lead is created."""
    service = ScoutWatchService(db)

    post = service.get_post(post_id)
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post not found: {post_id}",
        )

    try:
        service.dismiss_post(post)
    except ScoutWatchError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    db.add(
        AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="scout_watch.dismiss_post",
            entity_type="scout_watch_post",
            entity_id=post_id,
            request_json={"watch_id": post.watch_id},
            response_json={
                "analysis_recommendation": post.analysis_recommendation,
                "analysis_confidence": post.analysis_confidence,
            },
            result="ok",
        )
    )
    db.commit()

    assert post.dismissed_at is not None
    return ScoutWatchPostDismissResponse(post_id=post_id, dismissed_at=post.dismissed_at)


# =============================================================================
# RE-ANALYZE POST
# =============================================================================


@router.post(
    "/{watch_id}/posts/{post_id}/reanalyze",
    response_model=ScoutWatchPostReanalyzeResponse,
)
async def reanalyze_post(
    watch_id: int,
    post_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> ScoutWatchPostReanalyzeResponse:
    """Trigger re-analysis of a scout watch post.

    Args:
        watch_id: Watch ID.
        post_id: Post ID.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        Re-analyze response.

    Raises:
        HTTPException: If watch or post not found.
    """
    service = ScoutWatchService(db)

    try:
        # Verify watch exists
        service.get_watch_or_raise(watch_id)

        # Get post
        post = service.get_post(post_id)
        if not post or post.watch_id != watch_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Post not found: {post_id}",
            )

        # Reset post for re-analysis
        service.reset_post_for_reanalysis(post)

        # Enqueue analysis task
        settings = get_settings()
        celery_app = Celery(
            "rediska",
            broker=settings.celery_broker_url,
            backend=settings.celery_result_backend,
        )

        task = celery_app.send_task(
            "scout.reanalyze_post",
            kwargs={
                "watch_id": watch_id,
                "post_id": post_id,
                "external_post_id": post.external_post_id,
            },
            queue="scout",
        )

        # Audit log
        audit = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="scout_watch.reanalyze_post",
            entity_type="scout_watch_post",
            entity_id=post_id,
            request_json={"watch_id": watch_id},
            response_json={"task_id": task.id},
            result="ok",
        )
        db.add(audit)
        db.commit()

        return ScoutWatchPostReanalyzeResponse(
            post_id=post_id,
            status="queued",
            message=f"Re-analysis queued with task ID: {task.id}",
        )

    except ScoutWatchNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watch not found: {watch_id}",
        )


# =============================================================================
# ADD POST TO LEADS
# =============================================================================


@router.post(
    "/{watch_id}/posts/{post_id}/add-to-leads",
    response_model=ScoutWatchPostAddToLeadsResponse,
)
async def add_post_to_leads(
    watch_id: int,
    post_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> ScoutWatchPostAddToLeadsResponse:
    """Force-add a scout watch post to leads regardless of recommendation.

    Args:
        watch_id: Watch ID.
        post_id: Post ID.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        Response with created lead ID.

    Raises:
        HTTPException: If watch or post not found, or lead already exists.
    """
    service = ScoutWatchService(db)

    try:
        # Verify watch exists
        watch = service.get_watch_or_raise(watch_id)

        # Get post
        post = service.get_post(post_id)
        if not post or post.watch_id != watch_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Post not found: {post_id}",
            )

        # Check if already a lead
        if post.lead_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Post already added to leads: Lead #{post.lead_id}",
            )

        # Manual promotion is an explicit user action, so it overrides an
        # `ignored` verdict and the contacted/engaged skips — but never the
        # do-not-contact list, which is a hard safety boundary.
        if post.post_author:
            verdict = service.check_author_verdict(watch.provider_id, post.post_author)
            if verdict == SKIP_DO_NOT_CONTACT:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"u/{post.post_author} is on the do-not-contact list",
                )

        # Build post data for lead creation
        post_data = {
            "provider_id": watch.provider_id,
            "source_location": watch.source_location,
            "external_post_id": post.external_post_id,
            "post_url": f"https://reddit.com/comments/{post.external_post_id}",
            "title": post.post_title,
            "body_text": post.post_body,  # stored since migration 013; None on older posts
            "post_created_at": post.first_seen_at,
            "author_username": post.post_author,
        }

        # Create the lead
        lead = service.save_lead_from_watch(
            watch=watch,
            post_data=post_data,
            user_interests_summary=post.user_interests,
            user_character_summary=post.user_character,
        )

        # Update post with lead_id; a human promotion triages the post out of
        # the needs-review queue.
        post.lead_id = lead.id
        post.triaged_at = datetime.utcnow()
        if lead.priority is None:
            from rediska_core.domain.services.lead_priority import (
                priority_from_stored_results,
            )

            lead.priority, lead.compatibility_score = priority_from_stored_results(
                post.dimension_results_json
            )
        db.flush()

        # Audit log
        audit = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="scout_watch.add_post_to_leads",
            entity_type="scout_watch_post",
            entity_id=post_id,
            request_json={"watch_id": watch_id},
            response_json={"lead_id": lead.id},
            result="ok",
        )
        db.add(audit)
        db.commit()

        return ScoutWatchPostAddToLeadsResponse(
            post_id=post_id,
            lead_id=lead.id,
            message=f"Post added to leads as Lead #{lead.id}",
        )

    except ScoutWatchNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watch not found: {watch_id}",
        )
