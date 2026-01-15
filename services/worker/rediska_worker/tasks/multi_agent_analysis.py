"""Multi-agent lead analysis tasks.

Provides background processing for multi-dimensional lead analysis
using specialized LLM agents.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from rediska_worker.celery_app import app

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    """Get current UTC time."""
    return datetime.now(timezone.utc)


def _get_db_session() -> Any:
    """Get database session for task execution."""
    try:
        from rediska_core.infra.db import get_db
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        import os

        database_url = os.getenv("MYSQL_URL")
        if not database_url:
            raise RuntimeError("MYSQL_URL not configured")

        engine = create_engine(database_url)
        SessionLocal = sessionmaker(bind=engine)
        return SessionLocal()
    except Exception as e:
        logger.error(f"Failed to create database session: {e}")
        raise


def _get_job_record(db: Any, dedupe_key: str) -> Optional[Any]:
    """Get or create job record for idempotency."""
    try:
        from rediska_core.domain.models import Job
        from sqlalchemy import select

        stmt = select(Job).where(Job.dedupe_key == dedupe_key)
        job = db.execute(stmt).scalar()

        if not job:
            job = Job(
                queue_name="multi_agent_analysis",
                job_type="analyze_lead",
                payload_json={"dedupe_key": dedupe_key},
                dedupe_key=dedupe_key,
                status="queued",
            )
            db.add(job)
            db.commit()

        return job
    except Exception as e:
        logger.error(f"Failed to get/create job record: {e}")
        raise


def _update_job_status(
    db: Any, job_id: int, status: str, error_detail: Optional[str] = None
) -> None:
    """Update job status."""
    try:
        from rediska_core.domain.models import Job

        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = status
            if error_detail:
                job.last_error = error_detail
            job.attempts = (job.attempts or 0) + 1
            db.commit()
    except Exception as e:
        logger.error(f"Failed to update job status: {e}")


@app.task(
    bind=True,
    name="multi_agent_analysis.analyze_lead",
    max_retries=3,
    default_retry_delay=300,  # 5 minutes
)
def analyze_lead_task(self, lead_id: int) -> dict:
    """
    Analyze a lead using multi-agent pipeline.

    This background task:
    1. Creates a job record for idempotency
    2. Fetches lead and profile data
    3. Runs all 5 dimension agents in parallel
    4. Synthesizes results with meta-analysis coordinator
    5. Stores results to database

    Args:
        lead_id: ID of lead to analyze

    Returns:
        dict: Task result with analysis_id, recommendation, confidence
    """
    db = None
    job = None

    try:
        db = _get_db_session()
        dedupe_key = f"multi_agent_analysis:lead:{lead_id}"

        # Get or create job for idempotency
        job = _get_job_record(db, dedupe_key)

        # If already completed, return early
        if job.status == "done":
            logger.info(f"Lead {lead_id} already analyzed (job {job.id})")
            return {
                "status": "already_completed",
                "job_id": job.id,
                "lead_id": lead_id,
            }

        # Mark job as running
        _update_job_status(db, job.id, "running")

        # Import services
        from rediska_core.domain.models import LeadPost
        from rediska_core.domain.services.agent_prompt import AgentPromptService
        from rediska_core.domain.services.multi_agent_analysis import (
            MultiAgentAnalysisService,
        )
        from rediska_core.domain.services.inference import InferenceClient
        from rediska_core.config import get_settings

        # Verify lead exists
        lead = db.query(LeadPost).filter(LeadPost.id == lead_id).first()
        if not lead:
            error_msg = f"Lead not found: {lead_id}"
            _update_job_status(db, job.id, "failed", error_msg)
            logger.error(error_msg)
            return {"status": "error", "error": error_msg, "job_id": job.id}

        # Get inference client
        settings = get_settings()
        inference_client = InferenceClient(
            url=settings.inference_url,
            model_name=settings.inference_model,
            api_key=settings.inference_api_key,
        )

        # Create services
        prompt_service = AgentPromptService(db)
        analysis_service = MultiAgentAnalysisService(
            db=db,
            inference_client=inference_client,
            prompt_service=prompt_service,
        )

        # Run analysis (async operation)
        logger.info(f"Starting analysis for lead {lead_id}")
        analysis = asyncio.run(analysis_service.analyze_lead(lead_id))

        # Mark job as done
        _update_job_status(db, job.id, "done")

        logger.info(
            f"Completed analysis for lead {lead_id}: "
            f"{analysis.final_recommendation} "
            f"(confidence: {analysis.confidence_score})"
        )

        return {
            "status": "success",
            "job_id": job.id,
            "analysis_id": analysis.id,
            "lead_id": lead_id,
            "recommendation": analysis.final_recommendation,
            "confidence": float(analysis.confidence_score or 0),
        }

    except Exception as exc:
        error_msg = f"Analysis failed: {str(exc)}"
        logger.error(error_msg, exc_info=True)

        if job and db:
            _update_job_status(db, job.id, "failed", error_msg)

        # Retry with exponential backoff
        retry_count = self.request.retries
        if retry_count < self.max_retries:
            logger.info(
                f"Retrying analyze_lead for lead {lead_id} "
                f"(attempt {retry_count + 1}/{self.max_retries})"
            )
            raise self.retry(exc=exc, countdown=300 * (2 ** retry_count))
        else:
            logger.error(f"All retries exhausted for lead {lead_id}")
            return {
                "status": "failed",
                "error": error_msg,
                "lead_id": lead_id,
                "job_id": job.id if job else None,
            }

    finally:
        if db:
            db.close()


@app.task(
    bind=True,
    name="multi_agent_analysis.batch_analyze",
    max_retries=2,
)
def batch_analyze_leads(self, lead_ids: list[int]) -> dict:
    """
    Analyze multiple leads.

    Spawns individual analyze_lead_task for each lead in the list.
    This is useful for bulk analysis operations.

    Args:
        lead_ids: List of lead IDs to analyze

    Returns:
        dict: Summary with queued count and task IDs
    """
    try:
        logger.info(f"Starting batch analysis for {len(lead_ids)} leads")

        task_ids = []
        for lead_id in lead_ids:
            task = analyze_lead_task.delay(lead_id)
            task_ids.append({"lead_id": lead_id, "task_id": task.id})
            logger.debug(f"Queued analysis for lead {lead_id}: {task.id}")

        logger.info(f"Batch analysis queued: {len(task_ids)} tasks")

        return {
            "status": "queued",
            "total": len(lead_ids),
            "tasks": task_ids,
        }

    except Exception as exc:
        logger.error(f"Batch analysis failed: {str(exc)}", exc_info=True)

        if self.request.retries < self.max_retries:
            logger.info(f"Retrying batch analysis (attempt {self.request.retries + 1})")
            raise self.retry(exc=exc, countdown=60)
        else:
            return {
                "status": "failed",
                "error": str(exc),
                "total": len(lead_ids),
            }


@app.task(name="multi_agent_analysis.check_analysis_status")
def check_analysis_status(analysis_id: int) -> dict:
    """
    Check the status of a multi-agent analysis.

    Args:
        analysis_id: ID of analysis to check

    Returns:
        dict: Analysis status and results if completed
    """
    db = None

    try:
        db = _get_db_session()

        from rediska_core.domain.models import LeadAnalysis

        analysis = db.query(LeadAnalysis).filter(LeadAnalysis.id == analysis_id).first()

        if not analysis:
            return {
                "status": "not_found",
                "analysis_id": analysis_id,
            }

        result = {
            "status": analysis.status,
            "analysis_id": analysis_id,
            "lead_id": analysis.lead_id,
            "started_at": analysis.started_at.isoformat(),
            "completed_at": analysis.completed_at.isoformat()
            if analysis.completed_at
            else None,
        }

        if analysis.status == "completed":
            result.update(
                {
                    "recommendation": analysis.final_recommendation,
                    "confidence": float(analysis.confidence_score or 0),
                    "reasoning": analysis.recommendation_reasoning,
                }
            )

        return result

    except Exception as exc:
        logger.error(f"Failed to check analysis status: {str(exc)}", exc_info=True)
        return {
            "status": "error",
            "error": str(exc),
            "analysis_id": analysis_id,
        }

    finally:
        if db:
            db.close()


@app.task(name="multi_agent_analysis.cleanup_failed_analyses")
def cleanup_failed_analyses(max_age_hours: int = 72) -> dict:
    """
    Clean up failed analyses older than specified time.

    Args:
        max_age_hours: Delete failed analyses older than this many hours

    Returns:
        dict: Cleanup summary
    """
    db = None

    try:
        db = _get_db_session()

        from datetime import timedelta
        from rediska_core.domain.models import LeadAnalysis
        from sqlalchemy import select

        cutoff_time = _now_utc() - timedelta(hours=max_age_hours)

        stmt = select(LeadAnalysis).where(
            LeadAnalysis.status == "failed", LeadAnalysis.created_at < cutoff_time
        )

        failed_analyses = db.execute(stmt).scalars().all()
        count = len(failed_analyses)

        for analysis in failed_analyses:
            db.delete(analysis)

        db.commit()

        logger.info(f"Cleaned up {count} failed analyses older than {max_age_hours} hours")

        return {
            "status": "success",
            "cleaned_up": count,
            "max_age_hours": max_age_hours,
        }

    except Exception as exc:
        logger.error(f"Cleanup failed: {str(exc)}", exc_info=True)
        return {
            "status": "error",
            "error": str(exc),
        }

    finally:
        if db:
            db.close()
