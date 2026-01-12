"""Jobs ledger service for Rediska.

Provides job creation, deduplication, claiming, and status management.
Jobs are used to track background work with idempotency guarantees.
"""

import hashlib
import json
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session as DBSession

from rediska_core.domain.models import Job

# Valid job statuses
VALID_STATUSES = {"queued", "running", "retrying", "failed", "done"}

# Statuses that can be claimed for execution
CLAIMABLE_STATUSES = {"queued", "retrying"}

# Maximum length for error messages
MAX_ERROR_LENGTH = 5000

# Default backoff settings (exponential)
BASE_BACKOFF_SECONDS = 60  # 1 minute
MAX_BACKOFF_SECONDS = 3600  # 1 hour
BACKOFF_MULTIPLIER = 2


class JobService:
    """Service for job ledger operations."""

    def __init__(self, db: DBSession):
        """Initialize the job service.

        Args:
            db: SQLAlchemy database session.
        """
        self.db = db

    def compute_dedupe_key(
        self,
        queue_name: str,
        job_type: str,
        payload: dict[str, Any],
    ) -> str:
        """Compute a dedupe key from job parameters.

        The dedupe key is a hash of queue_name, job_type, and payload.
        This ensures that identical jobs produce the same key.

        Args:
            queue_name: The queue name.
            job_type: The job type.
            payload: The job payload.

        Returns:
            A hex string hash that uniquely identifies this job combination.
        """
        # Sort keys to ensure consistent ordering
        canonical = json.dumps(
            {
                "queue": queue_name,
                "type": job_type,
                "payload": payload,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha256(canonical.encode()).hexdigest()[:64]

    def create_job(
        self,
        queue_name: str,
        job_type: str,
        payload: dict[str, Any],
        max_attempts: int = 10,
        run_at: Optional[datetime] = None,
        dedupe: bool = True,
    ) -> Job:
        """Create a new job or return existing one if dedupe key matches.

        Args:
            queue_name: The queue to place the job in.
            job_type: The type of job.
            payload: The job payload data.
            max_attempts: Maximum retry attempts (default 10).
            run_at: Optional scheduled execution time.
            dedupe: Whether to use deduplication (default True).

        Returns:
            The created or existing Job.
        """
        job, _ = self.create_job_or_get(
            queue_name=queue_name,
            job_type=job_type,
            payload=payload,
            max_attempts=max_attempts,
            run_at=run_at,
            dedupe=dedupe,
        )
        return job

    def create_job_or_get(
        self,
        queue_name: str,
        job_type: str,
        payload: dict[str, Any],
        max_attempts: int = 10,
        run_at: Optional[datetime] = None,
        dedupe: bool = True,
    ) -> tuple[Job, bool]:
        """Create a new job or return existing one, with creation flag.

        Args:
            queue_name: The queue to place the job in.
            job_type: The type of job.
            payload: The job payload data.
            max_attempts: Maximum retry attempts (default 10).
            run_at: Optional scheduled execution time.
            dedupe: Whether to use deduplication (default True).

        Returns:
            Tuple of (Job, created) where created is True if new job was created.
        """
        dedupe_key = None
        if dedupe:
            dedupe_key = self.compute_dedupe_key(queue_name, job_type, payload)

            # Check for existing job with same dedupe key
            existing = self.get_job_by_dedupe_key(dedupe_key)
            if existing is not None:
                return existing, False

        # Create new job
        job = Job(
            queue_name=queue_name,
            job_type=job_type,
            payload_json=payload,
            status="queued",
            attempts=0,
            max_attempts=max_attempts,
            next_run_at=run_at,
            dedupe_key=dedupe_key,
        )

        self.db.add(job)
        self.db.flush()

        return job, True

    def get_job(self, job_id: int) -> Optional[Job]:
        """Get a job by ID.

        Args:
            job_id: The job ID.

        Returns:
            The Job or None if not found.
        """
        return self.db.query(Job).filter(Job.id == job_id).first()

    def get_job_by_dedupe_key(self, dedupe_key: str) -> Optional[Job]:
        """Get a job by dedupe key.

        Args:
            dedupe_key: The dedupe key.

        Returns:
            The Job or None if not found.
        """
        return self.db.query(Job).filter(Job.dedupe_key == dedupe_key).first()

    def claim_job(self, job_id: int) -> bool:
        """Attempt to claim a job for execution.

        This atomically transitions the job from queued/retrying to running.
        Only one worker can successfully claim a job.

        Args:
            job_id: The job ID to claim.

        Returns:
            True if successfully claimed, False otherwise.
        """
        # Atomic update: only update if status is claimable
        result = (
            self.db.query(Job)
            .filter(
                Job.id == job_id,
                Job.status.in_(CLAIMABLE_STATUSES),
            )
            .update(
                {
                    Job.status: "running",
                    Job.attempts: Job.attempts + 1,
                    Job.updated_at: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
        )

        self.db.flush()
        return result > 0

    def claim_next_job(
        self,
        queue_name: str,
        job_types: Optional[list[str]] = None,
    ) -> Optional[Job]:
        """Claim the next available job from a queue.

        Jobs are selected in FIFO order, respecting scheduled times.
        Only jobs with next_run_at <= now (or null) are considered.

        Args:
            queue_name: The queue to claim from.
            job_types: Optional list of job types to filter by.

        Returns:
            The claimed Job or None if no jobs available.
        """
        now = datetime.now(timezone.utc)

        # Build query for claimable jobs
        query = self.db.query(Job).filter(
            Job.queue_name == queue_name,
            Job.status.in_(CLAIMABLE_STATUSES),
            or_(Job.next_run_at.is_(None), Job.next_run_at <= now),
        )

        if job_types:
            query = query.filter(Job.job_type.in_(job_types))

        # Order by created_at (FIFO) and get first
        query = query.order_by(Job.created_at.asc())

        # Try to claim jobs until one succeeds
        for job in query.limit(10).all():
            if self.claim_job(job.id):
                self.db.refresh(job)
                return job

        return None

    def complete_job(
        self,
        job_id: int,
        result: Optional[dict[str, Any]] = None,
    ) -> None:
        """Mark a job as completed.

        Clears the dedupe key to allow re-queuing the same job later.

        Args:
            job_id: The job ID.
            result: Optional result data (currently not stored).
        """
        self.db.query(Job).filter(Job.id == job_id).update(
            {
                Job.status: "done",
                Job.dedupe_key: None,  # Allow re-queuing
                Job.last_error: None,
                Job.updated_at: datetime.now(timezone.utc),
            },
            synchronize_session=False,
        )
        self.db.flush()

    def fail_job(
        self,
        job_id: int,
        error: Union[str, Exception],
        include_traceback: bool = False,
    ) -> None:
        """Mark a job as failed or retrying.

        If attempts remain, marks as retrying with exponential backoff.
        If no attempts remain, marks as failed and clears dedupe key.

        Args:
            job_id: The job ID.
            error: The error message or exception.
            include_traceback: Whether to include traceback in error.
        """
        job = self.get_job(job_id)
        if job is None:
            return

        # Ensure we have fresh data from DB
        self.db.refresh(job)

        error_str = self.serialize_error(error, include_traceback)

        if job.attempts < job.max_attempts:
            # Calculate backoff
            backoff = self._calculate_backoff(job.attempts)
            next_run = datetime.now(timezone.utc) + timedelta(seconds=backoff)

            self.db.query(Job).filter(Job.id == job_id).update(
                {
                    Job.status: "retrying",
                    Job.last_error: error_str,
                    Job.next_run_at: next_run,
                    Job.updated_at: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
        else:
            # No more attempts, mark as failed
            self.db.query(Job).filter(Job.id == job_id).update(
                {
                    Job.status: "failed",
                    Job.last_error: error_str,
                    Job.dedupe_key: None,  # Allow re-queuing
                    Job.updated_at: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )

        self.db.flush()

    def _calculate_backoff(self, attempts: int) -> int:
        """Calculate exponential backoff in seconds.

        Args:
            attempts: Number of attempts made.

        Returns:
            Backoff duration in seconds.
        """
        backoff = BASE_BACKOFF_SECONDS * (BACKOFF_MULTIPLIER ** (attempts - 1))
        return min(int(backoff), MAX_BACKOFF_SECONDS)

    def serialize_error(
        self,
        error: Union[str, Exception],
        include_traceback: bool = False,
    ) -> str:
        """Serialize an error to a string suitable for storage.

        Args:
            error: The error message or exception.
            include_traceback: Whether to include traceback.

        Returns:
            Serialized error string (truncated if too long).
        """
        if isinstance(error, str):
            error_str = error
        elif isinstance(error, Exception):
            if include_traceback:
                error_str = traceback.format_exc()
            else:
                error_str = f"{type(error).__name__}: {error}"
        else:
            error_str = str(error)

        # Truncate if too long
        if len(error_str) > MAX_ERROR_LENGTH:
            error_str = error_str[: MAX_ERROR_LENGTH - 3] + "..."

        return error_str

    def list_jobs(
        self,
        queue_name: Optional[str] = None,
        job_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[Job]:
        """List jobs with optional filtering.

        Args:
            queue_name: Filter by queue name.
            job_type: Filter by job type.
            status: Filter by status.
            limit: Maximum number of jobs to return.

        Returns:
            List of matching jobs.
        """
        query = self.db.query(Job)

        if queue_name:
            query = query.filter(Job.queue_name == queue_name)
        if job_type:
            query = query.filter(Job.job_type == job_type)
        if status:
            query = query.filter(Job.status == status)

        query = query.order_by(Job.created_at.desc())

        return query.limit(limit).all()

    def count_jobs(
        self,
        queue_name: Optional[str] = None,
        job_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        """Count jobs with optional filtering.

        Args:
            queue_name: Filter by queue name.
            job_type: Filter by job type.
            status: Filter by status.

        Returns:
            Count of matching jobs.
        """
        query = self.db.query(Job)

        if queue_name:
            query = query.filter(Job.queue_name == queue_name)
        if job_type:
            query = query.filter(Job.job_type == job_type)
        if status:
            query = query.filter(Job.status == status)

        return query.count()

    def cleanup_completed_jobs(
        self,
        older_than_days: int = 30,
        statuses: Optional[list[str]] = None,
    ) -> int:
        """Delete old completed jobs.

        Args:
            older_than_days: Delete jobs older than this many days.
            statuses: Statuses to clean up (default: done, failed).

        Returns:
            Number of jobs deleted.
        """
        if statuses is None:
            statuses = ["done", "failed"]

        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)

        result = (
            self.db.query(Job)
            .filter(
                Job.status.in_(statuses),
                Job.created_at < cutoff,
            )
            .delete(synchronize_session=False)
        )

        self.db.flush()
        return result

    def requeue_job(
        self,
        job_id: int,
        max_attempts: Optional[int] = None,
    ) -> None:
        """Requeue a failed job for retry.

        Args:
            job_id: The job ID.
            max_attempts: New max attempts (default: keep existing).

        Raises:
            ValueError: If job is not in failed status.
        """
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")

        if job.status != "failed":
            raise ValueError(f"Can only requeue failed jobs, got status '{job.status}'")

        # Recompute dedupe key
        dedupe_key = self.compute_dedupe_key(
            job.queue_name,
            job.job_type,
            job.payload_json,
        )

        updates = {
            Job.status: "queued",
            Job.attempts: 0,
            Job.last_error: None,
            Job.dedupe_key: dedupe_key,
            Job.next_run_at: None,
            Job.updated_at: datetime.now(timezone.utc),
        }

        if max_attempts is not None:
            updates[Job.max_attempts] = max_attempts

        self.db.query(Job).filter(Job.id == job_id).update(
            updates,
            synchronize_session=False,
        )
        self.db.flush()
        self.db.refresh(job)
