"""Operations management API routes.

Provides endpoints for:
- GET /ops/jobs - List jobs with filtering
- GET /ops/jobs/{id} - Get job details
- POST /ops/jobs/{id}/retry - Retry a failed job
- POST /ops/backfill/conversations - Trigger conversation backfill
- GET /ops/sync/status - Get sync status per identity
"""

from datetime import datetime, timezone
from typing import Annotated, Optional

from celery import Celery
from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, func

from rediska_core.api.deps import CurrentUser, DBSession
from rediska_core.config import get_settings
from rediska_core.domain.models import (
    AuditLog,
    Conversation,
    Identity,
    Job,
    Message,
)
from rediska_core.domain.services.jobs import JobService
from rediska_core.domain.services.send_message import SendMessageService

router = APIRouter(prefix="/ops", tags=["operations"])


# =============================================================================
# Schemas
# =============================================================================


class JobPayload(BaseModel):
    """Job payload with relevant fields extracted."""

    conversation_id: Optional[int] = None
    message_id: Optional[int] = None
    identity_id: Optional[int] = None


class JobResponse(BaseModel):
    """Job response schema."""

    id: int
    queue_name: str
    job_type: str
    status: str
    attempts: int
    max_attempts: int
    last_error: Optional[str] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    payload: Optional[JobPayload] = None

    class Config:
        from_attributes = True


class JobListResponse(BaseModel):
    """Job list response schema."""

    jobs: list[JobResponse]
    total: int


class JobRetryResponse(BaseModel):
    """Job retry response schema."""

    id: int
    status: str
    message: str


class BackfillRequest(BaseModel):
    """Backfill request schema."""

    identity_id: Optional[int] = None


class BackfillResponse(BaseModel):
    """Backfill response schema."""

    job_id: str
    status: str
    message: str


class IdentitySyncStatus(BaseModel):
    """Identity sync status."""

    identity_id: int
    display_name: str
    external_username: str
    provider_id: str
    last_sync_at: Optional[datetime] = None
    conversations_count: int
    messages_count: int
    is_default: bool


class SyncStatusResponse(BaseModel):
    """Sync status response schema."""

    identities: list[IdentitySyncStatus]


class JobCountsResponse(BaseModel):
    """Job counts by status."""

    queued: int
    running: int
    retrying: int
    failed: int
    done: int
    cancelled: int
    total: int


class ConsistencyCheckResponse(BaseModel):
    """Consistency check response."""

    checked_jobs: int
    fixed_messages: int
    messages_fixed: list[int]
    message: str


# =============================================================================
# Dependencies
# =============================================================================


def get_job_service(db: DBSession) -> JobService:
    """Get the job service."""
    return JobService(db=db)


JobServiceDep = Annotated[JobService, Depends(get_job_service)]


def get_celery_app() -> Celery:
    """Get a Celery app instance."""
    settings = get_settings()
    return Celery(broker=settings.celery_broker_url, backend=settings.celery_result_backend)


def extract_job_payload(job: Job) -> Optional[JobPayload]:
    """Extract relevant payload fields from a job."""
    if not job.payload_json:
        return None

    payload = job.payload_json
    return JobPayload(
        conversation_id=payload.get("conversation_id"),
        message_id=payload.get("message_id"),
        identity_id=payload.get("identity_id"),
    )


# =============================================================================
# Routes
# =============================================================================


@router.get(
    "/jobs",
    response_model=JobListResponse,
    summary="List jobs",
    description="Get a list of jobs with optional filtering by status or type.",
)
async def list_jobs(
    current_user: CurrentUser,
    db: DBSession,
    job_service: JobServiceDep,
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by job status"),
    job_type: Optional[str] = Query(None, description="Filter by job type"),
    queue_name: Optional[str] = Query(None, description="Filter by queue name"),
    limit: int = Query(50, ge=1, le=200, description="Number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List jobs with optional filtering."""
    query = db.query(Job)

    if status_filter:
        query = query.filter(Job.status == status_filter)
    if job_type:
        query = query.filter(Job.job_type == job_type)
    if queue_name:
        query = query.filter(Job.queue_name == queue_name)

    total = query.count()
    jobs = query.order_by(desc(Job.created_at)).offset(offset).limit(limit).all()

    return JobListResponse(
        jobs=[
            JobResponse(
                id=job.id,
                queue_name=job.queue_name,
                job_type=job.job_type,
                status=job.status,
                attempts=job.attempts,
                max_attempts=job.max_attempts,
                last_error=job.last_error,
                next_run_at=job.next_run_at,
                created_at=job.created_at,
                updated_at=job.updated_at,
                payload=extract_job_payload(job),
            )
            for job in jobs
        ],
        total=total,
    )


@router.get(
    "/jobs/counts",
    response_model=JobCountsResponse,
    summary="Get job counts",
    description="Get counts of jobs by status.",
)
async def get_job_counts(
    current_user: CurrentUser,
    db: DBSession,
):
    """Get job counts by status."""
    counts = (
        db.query(Job.status, func.count(Job.id))
        .group_by(Job.status)
        .all()
    )

    count_map = {status: count for status, count in counts}

    return JobCountsResponse(
        queued=count_map.get("queued", 0),
        running=count_map.get("running", 0),
        retrying=count_map.get("retrying", 0),
        failed=count_map.get("failed", 0),
        done=count_map.get("done", 0),
        cancelled=count_map.get("cancelled", 0),
        total=sum(count_map.values()),
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
    summary="Get job details",
    description="Get details of a specific job.",
)
async def get_job(
    job_id: int,
    current_user: CurrentUser,
    job_service: JobServiceDep,
):
    """Get a job by ID."""
    job = job_service.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    return JobResponse(
        id=job.id,
        queue_name=job.queue_name,
        job_type=job.job_type,
        status=job.status,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        last_error=job.last_error,
        next_run_at=job.next_run_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
        payload=extract_job_payload(job),
    )


@router.post(
    "/jobs/{job_id}/retry",
    response_model=JobRetryResponse,
    summary="Retry a failed job",
    description="Requeue a failed job for retry.",
)
async def retry_job(
    job_id: int,
    current_user: CurrentUser,
    db: DBSession,
    job_service: JobServiceDep,
):
    """Retry a failed job."""
    job = job_service.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    if job.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Can only retry failed jobs, current status is '{job.status}'",
        )

    try:
        # For send_manual jobs, check if the message was deleted
        if job.job_type == "send_manual":
            if job.payload_json and "message_id" in job.payload_json:
                message_id = job.payload_json["message_id"]
                message = db.query(Message).filter(Message.id == message_id).first()
                if message and message.deleted_at is not None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Cannot retry job: associated message was deleted by user",
                    )

        job_service.requeue_job(job_id)
        db.commit()

        # Audit log
        audit_entry = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="job.retry",
            result="ok",
            entity_type="job",
            entity_id=job_id,
            request_json={"job_id": job_id},
            response_json={"status": "queued"},
        )
        db.add(audit_entry)
        db.commit()

        return JobRetryResponse(
            id=job_id,
            status="queued",
            message="Job requeued for retry",
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/backfill/conversations",
    response_model=BackfillResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger conversation backfill",
    description="Queue a background job to backfill all conversations from Reddit.",
)
async def trigger_backfill_conversations(
    request: BackfillRequest,
    current_user: CurrentUser,
    db: DBSession,
):
    """Trigger a full conversation backfill."""
    celery_app = get_celery_app()

    # Verify identity if specified
    if request.identity_id:
        identity = db.query(Identity).filter_by(id=request.identity_id, is_active=True).first()
        if not identity:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Identity not found or inactive",
            )

    # Send the task to the worker
    task = celery_app.send_task(
        "ingest.backfill_conversations",
        kwargs={"provider_id": "reddit", "identity_id": request.identity_id},
        queue="ingest",
    )

    # Audit log
    audit_entry = AuditLog(
        ts=datetime.now(timezone.utc),
        actor="user",
        action_type="backfill.trigger",
        result="ok",
        provider_id="reddit",
        identity_id=request.identity_id,
        request_json={"identity_id": request.identity_id},
        response_json={"job_id": task.id},
    )
    db.add(audit_entry)
    db.commit()

    return BackfillResponse(
        job_id=task.id,
        status="queued",
        message="Backfill job queued. Full conversation history will be imported in the background.",
    )


@router.post(
    "/consistency/check",
    response_model=ConsistencyCheckResponse,
    summary="Check and fix consistency between cancelled jobs and deleted messages",
    description="Audit and repair any inconsistencies where cancelled jobs have undel messages.",
)
async def check_consistency(
    current_user: CurrentUser,
    db: DBSession,
):
    """Check and fix consistency between cancelled jobs and deleted messages."""
    send_service = SendMessageService(db=db)
    results = send_service.ensure_cancelled_jobs_consistency()
    db.commit()

    # Audit log
    audit_entry = AuditLog(
        ts=datetime.now(timezone.utc),
        actor="user",
        action_type="consistency.check",
        result="ok",
        entity_type="jobs",
        request_json={},
        response_json=results,
    )
    db.add(audit_entry)
    db.commit()

    return ConsistencyCheckResponse(
        checked_jobs=results["checked_jobs"],
        fixed_messages=results["fixed_messages"],
        messages_fixed=results["messages_fixed"],
        message=f"Checked {results['checked_jobs']} cancelled jobs, fixed {results['fixed_messages']} messages",
    )


@router.get(
    "/backfill/{job_id}",
    summary="Check backfill job status",
    description="Check the status of a backfill job.",
)
async def get_backfill_status(
    job_id: str,
    current_user: CurrentUser,
):
    """Check the status of a backfill job."""
    celery_app = get_celery_app()
    result = AsyncResult(job_id, app=celery_app)

    if result.ready():
        if result.successful():
            return {
                "job_id": job_id,
                "status": "success",
                "result": result.result,
            }
        else:
            return {
                "job_id": job_id,
                "status": "failure",
                "result": {"error": str(result.result)},
            }
    else:
        return {
            "job_id": job_id,
            "status": "pending",
            "result": None,
        }


@router.get(
    "/sync/status",
    response_model=SyncStatusResponse,
    summary="Get sync status",
    description="Get sync status for all identities.",
)
async def get_sync_status(
    current_user: CurrentUser,
    db: DBSession,
):
    """Get sync status per identity."""
    identities = db.query(Identity).filter_by(is_active=True).all()

    result = []
    for identity in identities:
        # Get conversation count
        conv_count = (
            db.query(func.count(Conversation.id))
            .filter_by(identity_id=identity.id)
            .filter(Conversation.deleted_at.is_(None))
            .scalar()
        )

        # Get message count
        msg_count = (
            db.query(func.count(Message.id))
            .join(Conversation)
            .filter(Conversation.identity_id == identity.id)
            .filter(Message.deleted_at.is_(None))
            .scalar()
        )

        # Get last activity (last message time)
        last_message = (
            db.query(Message.sent_at)
            .join(Conversation)
            .filter(Conversation.identity_id == identity.id)
            .filter(Message.deleted_at.is_(None))
            .order_by(desc(Message.sent_at))
            .first()
        )

        result.append(
            IdentitySyncStatus(
                identity_id=identity.id,
                display_name=identity.display_name,
                external_username=identity.external_username,
                provider_id=identity.provider_id,
                last_sync_at=last_message[0] if last_message else None,
                conversations_count=conv_count or 0,
                messages_count=msg_count or 0,
                is_default=identity.is_default,
            )
        )

    return SyncStatusResponse(identities=result)
