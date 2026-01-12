"""Unit tests for jobs ledger service.

These tests follow TDD - written BEFORE implementation.
Tests cover:
- Job creation with dedupe key computation
- Idempotent job creation (dedupe)
- Job claiming/locking for execution
- Status transitions and attempt tracking
- Error serialization
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from rediska_core.domain.models import Job
from tests.factories import create_job


class TestDedupeKeyComputation:
    """Tests for dedupe key computation."""

    def test_compute_dedupe_key_basic(self, db_session: Session):
        """Test that dedupe key is computed from queue, type, and payload."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        key = service.compute_dedupe_key(
            queue_name="default",
            job_type="test.job",
            payload={"user_id": 123},
        )

        # Should be a consistent hash
        assert key is not None
        assert len(key) > 0

    def test_compute_dedupe_key_deterministic(self, db_session: Session):
        """Test that same inputs produce same dedupe key."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        key1 = service.compute_dedupe_key(
            queue_name="default",
            job_type="test.job",
            payload={"user_id": 123},
        )

        key2 = service.compute_dedupe_key(
            queue_name="default",
            job_type="test.job",
            payload={"user_id": 123},
        )

        assert key1 == key2

    def test_compute_dedupe_key_different_for_different_inputs(self, db_session: Session):
        """Test that different inputs produce different dedupe keys."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        key1 = service.compute_dedupe_key(
            queue_name="default",
            job_type="test.job",
            payload={"user_id": 123},
        )

        key2 = service.compute_dedupe_key(
            queue_name="default",
            job_type="test.job",
            payload={"user_id": 456},  # Different payload
        )

        key3 = service.compute_dedupe_key(
            queue_name="high_priority",  # Different queue
            job_type="test.job",
            payload={"user_id": 123},
        )

        key4 = service.compute_dedupe_key(
            queue_name="default",
            job_type="other.job",  # Different type
            payload={"user_id": 123},
        )

        assert key1 != key2
        assert key1 != key3
        assert key1 != key4

    def test_compute_dedupe_key_handles_nested_payload(self, db_session: Session):
        """Test that nested payload objects produce consistent keys."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        payload = {
            "user": {"id": 123, "name": "test"},
            "items": [1, 2, 3],
            "metadata": {"source": "api"},
        }

        key1 = service.compute_dedupe_key(
            queue_name="default",
            job_type="test.job",
            payload=payload,
        )

        key2 = service.compute_dedupe_key(
            queue_name="default",
            job_type="test.job",
            payload=payload,
        )

        assert key1 == key2

    def test_compute_dedupe_key_order_independent(self, db_session: Session):
        """Test that dict key order doesn't affect dedupe key."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        key1 = service.compute_dedupe_key(
            queue_name="default",
            job_type="test.job",
            payload={"a": 1, "b": 2, "c": 3},
        )

        key2 = service.compute_dedupe_key(
            queue_name="default",
            job_type="test.job",
            payload={"c": 3, "a": 1, "b": 2},
        )

        assert key1 == key2


class TestJobCreation:
    """Tests for job creation."""

    def test_create_job_basic(self, db_session: Session):
        """Test creating a basic job."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={"user_id": 123},
        )

        assert job.id is not None
        assert job.queue_name == "default"
        assert job.job_type == "test.job"
        assert job.payload_json == {"user_id": 123}
        assert job.status == "queued"
        assert job.attempts == 0
        assert job.dedupe_key is not None

    def test_create_job_with_custom_max_attempts(self, db_session: Session):
        """Test creating a job with custom max attempts."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={},
            max_attempts=5,
        )

        assert job.max_attempts == 5

    def test_create_job_with_scheduled_time(self, db_session: Session):
        """Test creating a job scheduled for later."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        run_at = datetime.now(timezone.utc) + timedelta(hours=1)

        job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={},
            run_at=run_at,
        )

        assert job.next_run_at is not None
        # Compare timestamps within a small margin
        assert abs((job.next_run_at.replace(tzinfo=timezone.utc) - run_at).total_seconds()) < 1

    def test_create_job_without_dedupe(self, db_session: Session):
        """Test creating a job without deduplication."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={"user_id": 123},
            dedupe=False,
        )

        assert job.dedupe_key is None


class TestJobDeduplication:
    """Tests for job deduplication (idempotency)."""

    def test_create_job_returns_existing_on_dedupe(self, db_session: Session):
        """Test that creating a duplicate job returns the existing one."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job1 = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={"user_id": 123},
        )

        job2 = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={"user_id": 123},
        )

        # Should return the same job
        assert job1.id == job2.id
        assert job1.dedupe_key == job2.dedupe_key

    def test_create_job_returns_existing_even_if_running(self, db_session: Session):
        """Test that dedupe returns existing job even if it's running."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job1 = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={"user_id": 123},
        )

        # Mark job as running
        job1.status = "running"
        db_session.flush()

        job2 = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={"user_id": 123},
        )

        assert job1.id == job2.id
        assert job2.status == "running"

    def test_create_job_creates_new_after_done(self, db_session: Session):
        """Test that a new job can be created after previous one is done."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job1 = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={"user_id": 123},
        )

        # Mark job as done and clear dedupe key
        service.complete_job(job1.id)

        # Now creating the same job should create a new one
        job2 = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={"user_id": 123},
        )

        assert job1.id != job2.id

    def test_create_job_or_get_existing_returns_info(self, db_session: Session):
        """Test that create_job_or_get returns whether it was created or existing."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job1, created1 = service.create_job_or_get(
            queue_name="default",
            job_type="test.job",
            payload={"user_id": 123},
        )

        job2, created2 = service.create_job_or_get(
            queue_name="default",
            job_type="test.job",
            payload={"user_id": 123},
        )

        assert created1 is True
        assert created2 is False
        assert job1.id == job2.id


class TestJobClaiming:
    """Tests for job claiming/locking."""

    def test_claim_job_success(self, db_session: Session):
        """Test successfully claiming a queued job."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={},
        )

        claimed = service.claim_job(job.id)

        assert claimed is True
        db_session.refresh(job)
        assert job.status == "running"
        assert job.attempts == 1

    def test_claim_job_fails_if_already_running(self, db_session: Session):
        """Test that claiming an already running job fails."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={},
        )

        # First claim succeeds
        claimed1 = service.claim_job(job.id)
        assert claimed1 is True

        # Second claim fails
        claimed2 = service.claim_job(job.id)
        assert claimed2 is False

    def test_claim_job_fails_if_done(self, db_session: Session):
        """Test that claiming a completed job fails."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={},
        )

        service.claim_job(job.id)
        service.complete_job(job.id)

        claimed = service.claim_job(job.id)
        assert claimed is False

    def test_claim_job_fails_if_failed(self, db_session: Session):
        """Test that claiming a failed job fails."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={},
            max_attempts=1,
        )

        service.claim_job(job.id)
        service.fail_job(job.id, "Test error")

        claimed = service.claim_job(job.id)
        assert claimed is False

    def test_claim_retrying_job(self, db_session: Session):
        """Test claiming a job that's in retrying status."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={},
            max_attempts=3,
        )

        # Simulate first attempt failure
        service.claim_job(job.id)
        service.fail_job(job.id, "Temporary error")

        db_session.refresh(job)
        assert job.status == "retrying"

        # Claiming retrying job should work
        claimed = service.claim_job(job.id)
        assert claimed is True

        # Refresh to get updated status
        db_session.refresh(job)
        assert job.status == "running"
        assert job.attempts == 2

    def test_claim_next_available_job(self, db_session: Session):
        """Test claiming the next available job from a queue."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job1 = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={"order": 1},
            dedupe=False,
        )

        job2 = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={"order": 2},
            dedupe=False,
        )

        # Claim next available
        claimed_job = service.claim_next_job(queue_name="default")

        assert claimed_job is not None
        assert claimed_job.id == job1.id  # FIFO order
        assert claimed_job.status == "running"

    def test_claim_next_available_respects_schedule(self, db_session: Session):
        """Test that claim_next_job respects scheduled time."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        # Create a job scheduled for the future
        future_job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={"scheduled": True},
            run_at=datetime.now(timezone.utc) + timedelta(hours=1),
            dedupe=False,
        )

        # Create an immediately available job
        ready_job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={"ready": True},
            dedupe=False,
        )

        # Should claim the ready job, not the future one
        claimed = service.claim_next_job(queue_name="default")

        assert claimed is not None
        assert claimed.id == ready_job.id


class TestJobCompletion:
    """Tests for job completion."""

    def test_complete_job_success(self, db_session: Session):
        """Test marking a job as completed."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={},
        )
        original_dedupe_key = job.dedupe_key

        service.claim_job(job.id)
        service.complete_job(job.id)

        db_session.refresh(job)
        assert job.status == "done"
        assert job.dedupe_key is None  # Cleared to allow re-running
        assert job.last_error is None

    def test_complete_job_with_result(self, db_session: Session):
        """Test completing a job with a result payload."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={},
        )

        service.claim_job(job.id)
        service.complete_job(job.id, result={"processed": 100})

        db_session.refresh(job)
        assert job.status == "done"
        # Result could be stored in payload_json or a separate field


class TestJobFailure:
    """Tests for job failure handling."""

    def test_fail_job_marks_retrying_if_attempts_remain(self, db_session: Session):
        """Test that failing a job with attempts remaining marks it as retrying."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={},
            max_attempts=3,
        )

        service.claim_job(job.id)
        service.fail_job(job.id, "Temporary error")

        db_session.refresh(job)
        assert job.status == "retrying"
        assert job.attempts == 1
        assert job.last_error == "Temporary error"
        assert job.next_run_at is not None  # Scheduled for retry

    def test_fail_job_marks_failed_if_no_attempts_remain(self, db_session: Session):
        """Test that failing a job with no attempts remaining marks it as failed."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={},
            max_attempts=1,
        )

        service.claim_job(job.id)
        service.fail_job(job.id, "Permanent error")

        db_session.refresh(job)
        assert job.status == "failed"
        assert job.last_error == "Permanent error"
        assert job.dedupe_key is None  # Cleared to allow re-queuing

    def test_fail_job_increments_backoff(self, db_session: Session):
        """Test that retry backoff increases with each attempt."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={},
            max_attempts=5,
        )

        # First failure
        service.claim_job(job.id)
        service.fail_job(job.id, "Error 1")
        db_session.refresh(job)
        first_retry = job.next_run_at

        # Second failure
        service.claim_job(job.id)
        service.fail_job(job.id, "Error 2")
        db_session.refresh(job)
        second_retry = job.next_run_at

        # Second retry should be further in the future (exponential backoff)
        assert second_retry > first_retry


class TestErrorSerialization:
    """Tests for error serialization."""

    def test_serialize_error_string(self, db_session: Session):
        """Test serializing a simple string error."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        error = service.serialize_error("Something went wrong")
        assert error == "Something went wrong"

    def test_serialize_error_exception(self, db_session: Session):
        """Test serializing an exception."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        try:
            raise ValueError("Invalid value")
        except ValueError as e:
            error = service.serialize_error(e)

        assert "ValueError" in error
        assert "Invalid value" in error

    def test_serialize_error_with_traceback(self, db_session: Session):
        """Test serializing an exception with traceback."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        try:
            raise RuntimeError("Deep error")
        except RuntimeError as e:
            error = service.serialize_error(e, include_traceback=True)

        assert "RuntimeError" in error
        assert "Deep error" in error
        assert "Traceback" in error or "test_jobs_unit" in error

    def test_serialize_error_truncates_long_errors(self, db_session: Session):
        """Test that very long errors are truncated."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        long_error = "x" * 10000
        error = service.serialize_error(long_error)

        assert len(error) <= 5000  # Should be truncated


class TestJobQuery:
    """Tests for querying jobs."""

    def test_get_job_by_id(self, db_session: Session):
        """Test getting a job by ID."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        created_job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={},
        )

        job = service.get_job(created_job.id)

        assert job is not None
        assert job.id == created_job.id

    def test_get_job_by_dedupe_key(self, db_session: Session):
        """Test getting a job by dedupe key."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        created_job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={"unique": "data"},
        )

        job = service.get_job_by_dedupe_key(created_job.dedupe_key)

        assert job is not None
        assert job.id == created_job.id

    def test_list_jobs_by_status(self, db_session: Session):
        """Test listing jobs by status."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        # Create jobs with different statuses
        job1 = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={"n": 1},
            dedupe=False,
        )

        job2 = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={"n": 2},
            dedupe=False,
        )
        service.claim_job(job2.id)

        job3 = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={"n": 3},
            dedupe=False,
        )
        service.claim_job(job3.id)
        service.complete_job(job3.id)

        queued_jobs = service.list_jobs(status="queued")
        running_jobs = service.list_jobs(status="running")
        done_jobs = service.list_jobs(status="done")

        assert len(queued_jobs) == 1
        assert len(running_jobs) == 1
        assert len(done_jobs) == 1

    def test_list_jobs_by_queue(self, db_session: Session):
        """Test listing jobs by queue."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={},
            dedupe=False,
        )

        service.create_job(
            queue_name="high_priority",
            job_type="test.job",
            payload={},
            dedupe=False,
        )

        default_jobs = service.list_jobs(queue_name="default")
        high_jobs = service.list_jobs(queue_name="high_priority")

        assert len(default_jobs) == 1
        assert len(high_jobs) == 1

    def test_count_jobs_by_status(self, db_session: Session):
        """Test counting jobs by status."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        for i in range(3):
            service.create_job(
                queue_name="default",
                job_type="test.job",
                payload={"n": i},
                dedupe=False,
            )

        count = service.count_jobs(status="queued")
        assert count == 3


class TestJobCleanup:
    """Tests for job cleanup operations."""

    def test_cleanup_old_completed_jobs(self, db_session: Session):
        """Test cleaning up old completed jobs."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        # Create and complete a job
        job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={},
        )
        service.claim_job(job.id)
        service.complete_job(job.id)

        # Manually set created_at to old date for testing
        job.created_at = datetime.now(timezone.utc) - timedelta(days=31)
        db_session.flush()

        # Cleanup jobs older than 30 days
        deleted_count = service.cleanup_completed_jobs(older_than_days=30)

        assert deleted_count == 1
        assert service.get_job(job.id) is None

    def test_cleanup_preserves_recent_jobs(self, db_session: Session):
        """Test that cleanup preserves recent jobs."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={},
        )
        service.claim_job(job.id)
        service.complete_job(job.id)

        # Cleanup jobs older than 30 days
        deleted_count = service.cleanup_completed_jobs(older_than_days=30)

        assert deleted_count == 0
        assert service.get_job(job.id) is not None


class TestJobRequeue:
    """Tests for requeuing failed jobs."""

    def test_requeue_failed_job(self, db_session: Session):
        """Test requeuing a failed job."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={},
            max_attempts=1,
        )
        service.claim_job(job.id)
        service.fail_job(job.id, "Error")

        db_session.refresh(job)
        assert job.status == "failed"

        # Requeue the job
        service.requeue_job(job.id, max_attempts=3)

        db_session.refresh(job)
        assert job.status == "queued"
        assert job.max_attempts == 3
        assert job.attempts == 0
        assert job.last_error is None
        assert job.dedupe_key is not None

    def test_requeue_non_failed_job_raises_error(self, db_session: Session):
        """Test that requeuing a non-failed job raises an error."""
        from rediska_core.domain.services.jobs import JobService

        service = JobService(db_session)

        job = service.create_job(
            queue_name="default",
            job_type="test.job",
            payload={},
        )

        with pytest.raises(ValueError, match="only requeue.*failed"):
            service.requeue_job(job.id)
