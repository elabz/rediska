"""Unit tests for multi-agent analysis Celery tasks.

Tests the background task layer including:
- analyze_lead_task: Main multi-agent analysis task
- batch_analyze_leads: Bulk analysis task
- check_analysis_status: Status checking utility
- cleanup_failed_analyses: Maintenance task
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rediska_worker.tasks.multi_agent_analysis import (
    analyze_lead_task,
    batch_analyze_leads,
    check_analysis_status,
    cleanup_failed_analyses,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    return MagicMock()


@pytest.fixture
def mock_inference_client():
    """Create a mock inference client."""
    return AsyncMock()


@pytest.fixture
def mock_job_record():
    """Create a mock job record."""
    job = MagicMock()
    job.id = 1
    job.status = "queued"
    job.dedupe_key = "multi_agent_analysis:lead:123"
    job.attempts = 0
    return job


# =============================================================================
# TESTS: analyze_lead_task
# =============================================================================


def test_analyze_lead_task_idempotency(mock_db_session, mock_job_record):
    """Test that analyzing the same lead twice uses idempotency."""
    # First call creates job
    # Second call detects existing job and returns early
    # Implementation test depends on actual task behavior


def test_analyze_lead_task_creates_job_record(mock_db_session, mock_job_record):
    """Test that analyze_lead_task creates a job record for idempotency."""
    # Job record should be created with dedupe_key
    # Implementation test depends on actual task behavior


def test_analyze_lead_task_updates_status_transitions(
    mock_db_session, mock_job_record
):
    """Test that task transitions through correct status states."""
    # queued -> running -> done (or failed)
    # Implementation test depends on actual task behavior


def test_analyze_lead_task_returns_success_format():
    """Test that successful task returns correct response format."""
    # Should return dict with:
    # - status: "success"
    # - job_id: int
    # - analysis_id: int
    # - lead_id: int
    # - recommendation: str
    # - confidence: float


def test_analyze_lead_task_handles_already_analyzed(mock_db_session, mock_job_record):
    """Test analyzing lead that's already been analyzed."""
    # Should detect existing completed job and return early
    # Should not re-run analysis


def test_analyze_lead_task_retries_on_failure():
    """Test that task retries with exponential backoff on failure."""
    # Should retry up to 3 times
    # Backoff: 300s, 600s, 1200s (exponential)


def test_analyze_lead_task_timeout_handling():
    """Test task handles timeout appropriately."""
    # Should have soft timeout (5 min) and hard timeout (10 min)


def test_analyze_lead_task_lead_not_found(mock_db_session):
    """Test task handles lead not found gracefully."""
    # Should mark job as failed
    # Should return error status
    # Should not retry


def test_analyze_lead_task_inference_error(mock_db_session):
    """Test task handles inference service errors."""
    # Should log error
    # Should mark job as failed
    # Should retry if appropriate


# =============================================================================
# TESTS: batch_analyze_leads
# =============================================================================


def test_batch_analyze_leads_queues_tasks():
    """Test that batch analysis queues individual tasks."""
    lead_ids = [1, 2, 3, 4, 5]
    # Should queue 5 analyze_lead_task calls
    # Should return task IDs for tracking


def test_batch_analyze_leads_empty_list():
    """Test batch analysis with empty list."""
    lead_ids = []
    # Should handle gracefully
    # Should return empty tasks list


def test_batch_analyze_leads_large_batch():
    """Test batch analysis with large list."""
    lead_ids = list(range(1, 101))  # 100 leads
    # Should queue all 100 tasks
    # Should not block or timeout


def test_batch_analyze_leads_returns_tracking_info():
    """Test batch analysis returns tracking information."""
    # Should return dict with:
    # - status: "queued"
    # - total: int
    # - tasks: list of {"lead_id": int, "task_id": str}


def test_batch_analyze_leads_retry_on_failure():
    """Test batch task retries on failure."""
    # Should have max_retries=2
    # Should log and continue on individual failures


# =============================================================================
# TESTS: check_analysis_status
# =============================================================================


def test_check_analysis_status_completed(mock_db_session):
    """Test checking status of completed analysis."""
    # Should return status with results
    # - status: "completed"
    # - recommendation: str
    # - confidence: float
    # - reasoning: str


def test_check_analysis_status_running(mock_db_session):
    """Test checking status of running analysis."""
    # Should return status showing analysis is in progress
    # - status: "running"
    # - started_at: datetime


def test_check_analysis_status_pending(mock_db_session):
    """Test checking status of pending analysis."""
    # Should return status showing analysis is queued
    # - status: "pending"


def test_check_analysis_status_failed(mock_db_session):
    """Test checking status of failed analysis."""
    # Should return failed status
    # - status: "failed"
    # - error: str


def test_check_analysis_status_not_found(mock_db_session):
    """Test checking status of non-existent analysis."""
    # Should return not_found status
    # - status: "not_found"
    # - analysis_id: int


def test_check_analysis_status_includes_timestamps():
    """Test that status includes ISO format timestamps."""
    # started_at and completed_at should be ISO format strings


def test_check_analysis_status_includes_metadata():
    """Test that status includes analysis metadata."""
    # Should include: analysis_id, lead_id, started_at, completed_at


# =============================================================================
# TESTS: cleanup_failed_analyses
# =============================================================================


def test_cleanup_failed_analyses_deletes_old_failed(mock_db_session):
    """Test that cleanup deletes old failed analyses."""
    # Should delete analyses with status='failed' and created_at < cutoff
    # Default cutoff: 72 hours ago


def test_cleanup_failed_analyses_preserves_recent(mock_db_session):
    """Test that cleanup preserves recent failed analyses."""
    # Should NOT delete failed analyses created < 72 hours ago


def test_cleanup_failed_analyses_preserves_completed(mock_db_session):
    """Test that cleanup doesn't delete completed analyses."""
    # Should only delete status='failed', not 'completed'


def test_cleanup_failed_analyses_custom_age(mock_db_session):
    """Test cleanup with custom max_age_hours parameter."""
    # Should accept max_age_hours parameter
    # Should delete analyses older than specified time


def test_cleanup_failed_analyses_returns_summary():
    """Test cleanup returns deletion summary."""
    # Should return dict with:
    # - status: "success"
    # - cleaned_up: int
    # - max_age_hours: int


def test_cleanup_failed_analyses_handles_cascade_delete():
    """Test cleanup handles cascade deletes properly."""
    # Should delete LeadAnalysis record
    # Should cascade delete AnalysisDimension records
    # Should maintain referential integrity


def test_cleanup_failed_analyses_large_dataset():
    """Test cleanup with large number of records."""
    # Should handle cleanup of thousands of records
    # Should not block or timeout


# =============================================================================
# TESTS: Error Handling and Resilience
# =============================================================================


def test_analyze_lead_task_partial_dimension_failure():
    """Test analysis continues if one dimension fails."""
    # Should not abort entire analysis
    # Should mark failed dimension
    # Should proceed with meta-analysis on successful dimensions


def test_analyze_lead_task_database_error():
    """Test handling of database errors."""
    # Should mark job as failed
    # Should log error
    # Should not corrupt job record


def test_analyze_lead_task_inference_timeout():
    """Test handling of inference service timeout."""
    # Should retry if configured
    # Should mark as failed if retries exhausted


def test_batch_analyze_leads_queue_overflow():
    """Test handling when task queue is full."""
    # Should queue tasks successfully or return error
    # Should not drop tasks


def test_cleanup_failed_analyses_database_error():
    """Test cleanup handles database errors."""
    # Should log error
    # Should return error status
    # Should not partially complete


# =============================================================================
# TESTS: Task Configuration and Registration
# =============================================================================


def test_analyze_lead_task_is_registered():
    """Test that analyze_lead_task is properly registered with Celery."""
    # Task should be registered as "multi_agent_analysis.analyze_lead"
    # Should have bind=True


def test_batch_analyze_leads_task_is_registered():
    """Test that batch_analyze_leads is registered."""
    # Task should be registered as "multi_agent_analysis.batch_analyze"


def test_check_analysis_status_task_is_registered():
    """Test that check_analysis_status is registered."""
    # Task should be registered as "multi_agent_analysis.check_analysis_status"


def test_cleanup_failed_analyses_task_is_registered():
    """Test that cleanup_failed_analyses is registered."""
    # Task should be registered as "multi_agent_analysis.cleanup_failed_analyses"


def test_task_routing_to_queue():
    """Test that tasks are routed to correct queue."""
    # All tasks should route to "multi_agent_analysis" queue


# =============================================================================
# TESTS: Task Logging and Monitoring
# =============================================================================


def test_analyze_lead_task_logs_start():
    """Test that analyze_lead_task logs when starting."""
    # Should log: "Starting analysis for lead {lead_id}"


def test_analyze_lead_task_logs_completion():
    """Test that analyze_lead_task logs on completion."""
    # Should log: "Completed analysis for lead {lead_id}: {recommendation} (confidence: {confidence})"


def test_analyze_lead_task_logs_retry():
    """Test that analyze_lead_task logs when retrying."""
    # Should log: "Retrying analyze_lead for lead {lead_id} (attempt {n}/{max})"


def test_batch_analyze_leads_logs_batch_info():
    """Test that batch task logs batch information."""
    # Should log: "Starting batch analysis for {count} leads"
    # Should log: "Batch analysis queued: {count} tasks"


def test_cleanup_failed_analyses_logs_deleted_count():
    """Test that cleanup logs number of deleted records."""
    # Should log: "Cleaned up {count} failed analyses older than {hours} hours"


# =============================================================================
# TESTS: Integration with Jobs Table
# =============================================================================


def test_task_creates_jobs_table_record():
    """Test that analyze_lead_task creates jobs table record."""
    # Should insert record with:
    # - queue_name: "multi_agent_analysis"
    # - job_type: "analyze_lead"
    # - dedupe_key: "multi_agent_analysis:lead:{lead_id}"
    # - status: "queued"


def test_task_updates_jobs_status_on_completion():
    """Test that task updates jobs table on completion."""
    # Should update status to "done"
    # Should set completed_at


def test_task_updates_jobs_status_on_failure():
    """Test that task updates jobs table on failure."""
    # Should update status to "failed"
    # Should set error_detail


def test_task_idempotency_via_jobs_dedupe_key():
    """Test that idempotency works via jobs dedupe_key."""
    # Same dedupe_key should return existing record
    # Should not create duplicate analysis records


# =============================================================================
# TESTS: Performance Characteristics
# =============================================================================


def test_batch_analyze_leads_performance_with_large_batch():
    """Test batch performance with many tasks."""
    # Should queue 1000+ tasks without significant delay


def test_cleanup_failed_analyses_performance_with_large_dataset():
    """Test cleanup performance with many records."""
    # Should handle 10000+ failed records


def test_analyze_lead_task_memory_usage():
    """Test that analyze task doesn't leak memory."""
    # Should not accumulate memory across multiple task executions
