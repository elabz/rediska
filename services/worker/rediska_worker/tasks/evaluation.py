"""Prompt replay task (analysis-evaluation).

``evaluation.replay_prompt`` re-runs one dimension agent on the labelled cases
for that dimension with a candidate prompt and records agreement with the
human labels. It runs on the ``multi_agent_analysis`` queue so it shares the
inference gate with live analyses, uses the ``jobs`` ledger for idempotency
and cancellation, and never retries (a replay is cheap to restart by hand).
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from rediska_worker.celery_app import app

logger = logging.getLogger(__name__)

JOB_TYPE = "evaluation.replay_prompt"


def _get_db_session() -> Any:
    """Create a database session for task execution."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    database_url = os.getenv("MYSQL_URL")
    if not database_url:
        raise RuntimeError("MYSQL_URL not configured")
    engine = create_engine(database_url)
    return sessionmaker(bind=engine)()


def _get_or_create_job(db: Any, replay_id: int) -> Any:
    """Job ledger row for this replay (the API usually pre-creates it)."""
    from rediska_core.domain.models import Job

    dedupe_key = f"{JOB_TYPE}:{replay_id}"
    job = db.query(Job).filter(Job.dedupe_key == dedupe_key).first()
    if job is None:
        job = Job(
            queue_name="multi_agent_analysis",
            job_type=JOB_TYPE,
            payload_json={"replay_id": replay_id},
            dedupe_key=dedupe_key,
            status="queued",
            max_attempts=1,
        )
        db.add(job)
        db.commit()
    return job


def _set_job(db: Any, job: Any, status: str, error: Optional[str] = None) -> None:
    job.status = status
    job.attempts = (job.attempts or 0) + 1 if status == "running" else job.attempts
    if error:
        job.last_error = error[:2000]
    job.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()


@app.task(
    bind=True,
    name="evaluation.replay_prompt",
    max_retries=0,
    # Up to EVALUATION_REPLAY_MAX_CASES serialised inference calls.
    soft_time_limit=3600,
    time_limit=3900,
)
def replay_prompt(self, replay_id: int) -> dict:
    """Run a queued prompt replay to completion (or cancellation).

    Args:
        replay_id: ``prompt_replays.id`` created by ``POST /agent-prompts/{dim}/replay``.

    Returns:
        dict with status, replay_id, agreement, and counts.
    """
    db = None
    job = None
    try:
        db = _get_db_session()
        job = _get_or_create_job(db, replay_id)

        if job.status == "done":
            logger.info(f"Replay {replay_id} already completed (job {job.id})")
            return {"status": "already_completed", "replay_id": replay_id, "job_id": job.id}
        if job.status == "cancelled":
            logger.info(f"Replay {replay_id} was cancelled before it started")
            return {"status": "cancelled", "replay_id": replay_id, "job_id": job.id}

        _set_job(db, job, "running")

        from rediska_core.config import get_settings
        from rediska_core.domain.services.inference import get_inference_client
        from rediska_core.domain.services.prompt_replay import run_replay

        settings = get_settings()
        replay = asyncio.run(
            run_replay(
                db,
                replay_id,
                inference_client=get_inference_client(),
                chat_template=settings.inference_chat_template,
                max_cases=settings.evaluation_replay_max_cases,
                job_id=job.id,
            )
        )

        final = "cancelled" if replay.status == "cancelled" else "done"
        _set_job(db, job, final)
        logger.info(
            f"Replay {replay_id} {replay.status}: agreement={replay.agreement} "
            f"({replay.agreed_count}/{replay.completed_count - replay.skipped_no_input}, "
            f"skipped_no_input={replay.skipped_no_input})"
        )
        return {
            "status": replay.status,
            "replay_id": replay_id,
            "job_id": job.id,
            "dimension": replay.dimension,
            "case_count": replay.case_count,
            "completed_count": replay.completed_count,
            "agreed_count": replay.agreed_count,
            "skipped_no_input": replay.skipped_no_input,
            "agreement": replay.agreement,
        }

    except Exception as exc:
        error = f"Replay failed: {exc}"
        logger.error(error, exc_info=True)
        if db is not None and job is not None:
            try:
                _set_job(db, job, "failed", error)
            except Exception:  # pragma: no cover - best effort
                db.rollback()
        return {"status": "failed", "replay_id": replay_id, "error": error}

    finally:
        if db is not None:
            db.close()
