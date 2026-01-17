"""Scout Watches API routes.

Provides endpoints for:
- POST /scout-watches - Create a scout watch
- GET /scout-watches - List all watches
- GET /scout-watches/{id} - Get watch by ID
- PUT /scout-watches/{id} - Update a watch
- DELETE /scout-watches/{id} - Delete a watch
- POST /scout-watches/{id}/run - Trigger a manual run
- GET /scout-watches/{id}/runs - Get run history
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
    ScoutWatchCreate,
    ScoutWatchListResponse,
    ScoutWatchPostResponse,
    ScoutWatchResponse,
    ScoutWatchRunDetailResponse,
    ScoutWatchRunListResponse,
    ScoutWatchRunResponse,
    ScoutWatchRunTriggerResponse,
    ScoutWatchUpdate,
)
from rediska_core.domain.models import AuditLog
from rediska_core.domain.services.scout_watch import (
    ScoutWatchError,
    ScoutWatchNotFoundError,
    ScoutWatchService,
)


router = APIRouter(prefix="/scout-watches", tags=["scout-watches"])
logger = logging.getLogger(__name__)


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
    service = ScoutWatchService(db)
    watches = service.list_watches(is_active=is_active, provider_id=provider_id)

    return ScoutWatchListResponse(
        watches=[ScoutWatchResponse.model_validate(w) for w in watches]
    )


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
    limit: int = Query(10, ge=1, le=100, description="Maximum runs to return"),
) -> ScoutWatchRunListResponse:
    """Get run history for a watch.

    Args:
        watch_id: Watch ID.
        limit: Maximum runs to return.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        List of watch runs.

    Raises:
        HTTPException: If watch not found.
    """
    service = ScoutWatchService(db)

    try:
        # Verify watch exists
        service.get_watch_or_raise(watch_id)

        runs = service.get_run_history(watch_id, limit=limit)
        return ScoutWatchRunListResponse(
            runs=[ScoutWatchRunResponse.model_validate(r) for r in runs]
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

        return ScoutWatchRunDetailResponse(
            run=ScoutWatchRunResponse.model_validate(run),
            posts=[ScoutWatchPostResponse.model_validate(p) for p in posts],
        )

    except ScoutWatchNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watch not found: {watch_id}",
        )
