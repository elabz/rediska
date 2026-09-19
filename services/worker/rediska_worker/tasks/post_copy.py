"""Post copy detection tasks (queue: maintenance).

- copy.backfill_fingerprints: fingerprint every stored post body and build
  copy clusters. Dry run by default; one live run at a time.
"""

import logging
import os
from datetime import datetime, timezone

from rediska_worker.celery_app import app

logger = logging.getLogger(__name__)

MYSQL_URL = os.getenv("MYSQL_URL", "mysql+pymysql://root:password@localhost:3306/rediska")

BACKFILL_DRY_RUN_KEY = "copy.backfill_fingerprints:dry_run"
BACKFILL_LIVE_KEY = "copy.backfill_fingerprints:live"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _get_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    return Session(create_engine(MYSQL_URL))


@app.task(
    name="copy.backfill_fingerprints",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
    # ~25k posts: pass 2 issues a handful of queries per post.
    soft_time_limit=3600,
    time_limit=3900,
)
def backfill_fingerprints(self, dry_run: bool = True) -> dict:
    """Fingerprint all stored posts (scout, lead, profile item) and cluster copies.

    Idempotent: posts already fingerprinted are skipped, so a rerun only
    handles what is new. The `jobs` ledger row (one per mode) records each run
    and refuses a second live run while one is still running.

    Args:
        dry_run: When True (the default), report counts and write nothing.
    """
    from sqlalchemy import select

    from rediska_core.domain.models import Job
    from rediska_core.domain.services.post_copy import backfill

    started_at = _now_utc()
    key = BACKFILL_DRY_RUN_KEY if dry_run else BACKFILL_LIVE_KEY
    session = _get_session()
    try:
        job = session.execute(select(Job).where(Job.dedupe_key == key)).scalar()
        if job is not None and job.status == "running" and not dry_run:
            return {"status": "already_running", "dry_run": dry_run}
        if job is None:
            job = Job(
                queue_name="maintenance",
                job_type="copy_backfill",
                payload_json={"dry_run": dry_run},
                dedupe_key=key,
                status="running",
                attempts=1,
            )
            session.add(job)
        else:
            job.status = "running"
            job.attempts = (job.attempts or 0) + 1
        session.commit()

        try:
            report = backfill(session, dry_run=dry_run)
        except Exception as exc:
            session.rollback()
            job.status = "failed"
            job.last_error = str(exc)[:2000]
            session.commit()
            raise

        job.status = "done"
        job.last_error = None
        job.payload_json = {"dry_run": dry_run, "report": report}
        session.commit()

        logger.info(f"copy.backfill_fingerprints (dry_run={dry_run}): {report}")
        completed_at = _now_utc()
        return {
            "status": "success",
            **report,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_seconds": int((completed_at - started_at).total_seconds()),
        }
    except Exception as exc:
        logger.error(f"copy.backfill_fingerprints failed: {exc}", exc_info=True)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        return {"status": "failed", "error": str(exc), "dry_run": dry_run}
    finally:
        session.close()
