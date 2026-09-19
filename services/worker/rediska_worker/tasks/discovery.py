"""Source discovery tasks (source-discovery).

``discovery.mine_candidates`` recomputes candidate locations and external
hosts from stored data once a day: no provider calls, no LLM, no HTTP.

``discovery.run_trial`` runs one bounded trial: it fetches a small sample of
recent posts from a candidate location and pushes each through the normal
scout pipeline on the candidate's hidden ``is_trial`` watch, which never
auto-promotes. Trials run one at a time on the ``scout`` queue (sharing the
inference gate), are cancellable between posts through the ``jobs`` ledger,
and never retry.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from rediska_worker.celery_app import app

logger = logging.getLogger(__name__)

MINE_JOB_TYPE = "discovery.mine_candidates"
TRIAL_JOB_TYPE = "discovery.run_trial"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _naive_utc() -> datetime:
    return _now_utc().replace(tzinfo=None)


def _get_db_session() -> Any:
    """Create a database session for task execution."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    database_url = os.getenv("MYSQL_URL")
    if not database_url:
        raise RuntimeError("MYSQL_URL not configured")
    engine = create_engine(database_url)
    return sessionmaker(bind=engine)()


# =============================================================================
# MINING
# =============================================================================


@app.task(
    bind=True,
    name="discovery.mine_candidates",
    max_retries=3,
    default_retry_delay=300,
)
def mine_candidates(self, run_date: Optional[str] = None) -> dict:
    """Recompute source candidates from stored author history and links.

    Idempotent per day: the ``jobs`` ledger is keyed on the run date, so a
    duplicate or retried delivery on the same day does no second pass.

    Args:
        run_date: ISO date to key the run on; defaults to today (UTC).

    Returns:
        dict with status and the mining summary.
    """
    db = None
    job = None
    started_at = _now_utc()
    day = run_date or started_at.date().isoformat()
    dedupe_key = f"{MINE_JOB_TYPE}:{day}"

    try:
        db = _get_db_session()

        from rediska_core.domain.models import Job
        from rediska_core.domain.services.source_discovery import SourceDiscoveryService

        job = db.query(Job).filter(Job.dedupe_key == dedupe_key).first()
        if job is not None and job.status == "done":
            return {"status": "skipped", "reason": "already mined today", "run_date": day}
        if job is None:
            job = Job(
                queue_name="scout",
                job_type=MINE_JOB_TYPE,
                payload_json={"run_date": day},
                dedupe_key=dedupe_key,
                status="running",
                attempts=1,
                max_attempts=self.max_retries + 1,
            )
            db.add(job)
        else:
            job.status = "running"
            job.attempts = (job.attempts or 0) + 1
        db.commit()

        summary = SourceDiscoveryService(db).mine()

        job.status = "done"
        job.last_error = None
        db.commit()

        completed_at = _now_utc()
        logger.info(f"Source discovery mining {day}: {summary.to_dict()}")
        return {
            "status": "success",
            "run_date": day,
            **summary.to_dict(),
            "duration_seconds": int((completed_at - started_at).total_seconds()),
        }

    except Exception as exc:
        logger.error(f"Source discovery mining failed: {exc}", exc_info=True)
        if db is not None:
            db.rollback()
            if job is not None:
                try:
                    job.status = "failed"
                    job.last_error = str(exc)[:2000]
                    db.commit()
                except Exception:  # pragma: no cover - best effort
                    db.rollback()
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=300 * (self.request.retries + 1))
        return {"status": "failed", "run_date": day, "error": str(exc)}

    finally:
        if db is not None:
            db.close()


# =============================================================================
# TRIALS
# =============================================================================


def _job_cancelled(db: Any, job_id: Optional[int]) -> bool:
    """Re-read the ledger row: the API cancels by setting it to `cancelled`."""
    if job_id is None:
        return False
    from rediska_core.domain.models import Job

    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        return False
    db.refresh(job)
    return job.status == "cancelled"


def _set_job(db: Any, job_id: Optional[int], status: str, error: Optional[str] = None) -> None:
    if job_id is None:
        return
    from rediska_core.domain.models import Job

    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        return
    # A cancellation requested while running wins over a later "done".
    if job.status == "cancelled" and status == "done":
        return
    job.status = status
    if status == "running":
        job.attempts = (job.attempts or 0) + 1
    if error:
        job.last_error = error[:2000]
    db.commit()


def _post_url(url: Optional[str]) -> Optional[str]:
    if url and not url.startswith("http"):
        return f"https://reddit.com{url}"
    return url


def _fetch_sample(adapter: Any, location: str, sample_size: int) -> list[Any]:
    async def fetch() -> list[Any]:
        try:
            result = await adapter.browse_location(
                location=location, sort="new", limit=sample_size
            )
            return list(result.items)[:sample_size]
        finally:
            await adapter.aclose()

    return asyncio.run(fetch())


@app.task(
    bind=True,
    name="discovery.run_trial",
    max_retries=0,
    # Up to DISCOVERY_TRIAL_SAMPLE (cap 50) posts, each a serialised
    # multi-agent analysis behind the shared inference gate.
    soft_time_limit=6 * 3600,
    time_limit=6 * 3600 + 600,
)
def run_trial(self, trial_id: int) -> dict:
    """Run one queued source trial to completion or cancellation.

    Args:
        trial_id: ``source_trials.id`` created by ``POST /source-candidates/{id}/trial``.

    Returns:
        dict with status, trial_id, and the yield report when completed.
    """
    db = None
    trial = None
    try:
        db = _get_db_session()

        from rediska_core.domain.models import ScoutWatch, SourceCandidate, SourceTrial
        from rediska_core.domain.services.external_listing import (
            is_link_only_body,
            maybe_resolve_post_body,
        )
        from rediska_core.domain.services.scout_watch import ScoutWatchService
        from rediska_core.domain.services.source_discovery import (
            STATUS_ACCEPTED,
            STATUS_DISMISSED,
            STATUS_TRIALLED,
            SourceDiscoveryService,
            record_link_sighting,
        )
        from rediska_worker.tasks.scout import _get_reddit_adapter, analyze_and_decide

        trial = db.query(SourceTrial).filter(SourceTrial.id == trial_id).first()
        if trial is None:
            return {"status": "error", "error": f"Trial not found: {trial_id}"}
        if trial.status != "queued":
            # Completed, cancelled, or a redelivery of a trial already running.
            return {"status": "skipped", "reason": f"trial is {trial.status}", "trial_id": trial_id}
        if _job_cancelled(db, trial.job_id):
            trial.status = "cancelled"
            trial.finished_at = _naive_utc()
            db.commit()
            return {"status": "cancelled", "trial_id": trial_id}

        watch = db.query(ScoutWatch).filter(ScoutWatch.id == trial.watch_id).first()
        if watch is None or not watch.is_trial:
            raise RuntimeError(f"Trial {trial_id} has no hidden trial watch")

        trial.status = "running"
        trial.started_at = _naive_utc()
        db.commit()
        _set_job(db, trial.job_id, "running")

        service = ScoutWatchService(db)
        run = service.create_run(watch.id)
        trial.run_id = run.id
        db.commit()

        adapter = _get_reddit_adapter(db, watch.identity_id)
        posts = _fetch_sample(adapter, watch.source_location, trial.sample_size)
        trial.posts_total = len(posts)
        db.commit()
        logger.info(
            f"Trial {trial_id}: fetched {len(posts)} posts from {watch.source_location}"
        )

        skipped_empty = 0
        link_only_resolved = 0
        posts_new = 0
        ages: list[float] = []
        cancelled = False
        now = _now_utc()

        for index, post in enumerate(posts):
            if _job_cancelled(db, trial.job_id):
                cancelled = True
                break

            if post.created_at:
                ages.append((now - post.created_at).total_seconds() / 3600.0)

            if service.is_post_seen(watch.id, post.external_id):
                trial.progress = index + 1
                db.commit()
                continue

            original_body = post.body_text
            post.body_text = maybe_resolve_post_body(post.body_text, post.url)
            if post.body_text != original_body and is_link_only_body(original_body, post.url):
                link_only_resolved += 1

            if not post.body_text or not post.body_text.strip():
                skipped_empty += 1
                if is_link_only_body(original_body, post.url):
                    record_link_sighting(
                        db, watch.provider_id, post.external_id, post.url, "trial"
                    )
                trial.progress = index + 1
                db.commit()
                continue

            scout_post = service.record_post(
                watch_id=watch.id,
                run_id=run.id,
                external_post_id=post.external_id,
                post_title=post.title,
                post_body=post.body_text,
                post_author=post.author_username,
                post_url=post.url,
                posted_at=post.created_at,
            )
            posts_new += 1
            db.commit()

            post_data = {
                "provider_id": watch.provider_id,
                "source_location": watch.source_location,
                "external_post_id": post.external_id,
                "post_url": _post_url(post.url),
                "title": post.title,
                "body_text": post.body_text,
                "author_username": post.author_username,
                "author_external_id": post.author_id,
                "post_created_at": post.created_at.isoformat() if post.created_at else None,
            }
            # Same per-post pipeline as a scout run, executed in-process so the
            # trial stays serial and can stop between posts. The trial watch
            # makes analyze_and_decide skip auto-promotion.
            try:
                analyze_and_decide.apply(
                    kwargs={
                        "watch_id": watch.id,
                        "scout_post_id": scout_post.id,
                        "post_data": post_data,
                    }
                )
            except Exception as exc:
                logger.error(f"Trial {trial_id}: analysis of {post.external_id} failed: {exc}")

            db.expire_all()
            trial = db.query(SourceTrial).filter(SourceTrial.id == trial_id).first()
            trial.progress = index + 1
            db.commit()

        service.complete_run(
            run=run,
            posts_fetched=len(posts),
            posts_new=posts_new,
            posts_analyzed=0,
            leads_created=0,
        )
        discovery = SourceDiscoveryService(db)
        trial.yield_json = discovery.build_trial_yield(
            trial,
            posts_fetched=len(posts),
            skipped_empty=skipped_empty,
            link_only_resolved=link_only_resolved,
            post_ages_hours=ages,
        )
        trial.finished_at = _naive_utc()
        if cancelled:
            trial.status = "cancelled"
        else:
            trial.status = "completed"
            candidate = db.query(SourceCandidate).filter(
                SourceCandidate.id == trial.candidate_id
            ).first()
            if candidate is not None and candidate.status not in (
                STATUS_ACCEPTED, STATUS_DISMISSED
            ):
                candidate.status = STATUS_TRIALLED
                candidate.snoozed_until = None
        db.commit()
        _set_job(db, trial.job_id, "cancelled" if cancelled else "done")

        logger.info(f"Trial {trial_id} {trial.status}: {trial.yield_json}")
        return {"status": trial.status, "trial_id": trial_id, "yield": trial.yield_json}

    except Exception as exc:
        error = f"Trial failed: {exc}"
        logger.error(error, exc_info=True)
        if db is not None:
            try:
                db.rollback()
                if trial is not None:
                    trial.status = "failed"
                    trial.error = error[:2000]
                    trial.finished_at = _naive_utc()
                    db.commit()
                    _set_job(db, trial.job_id, "failed", error)
            except Exception:  # pragma: no cover - best effort
                db.rollback()
        return {"status": "failed", "trial_id": trial_id, "error": error}

    finally:
        if db is not None:
            db.close()
