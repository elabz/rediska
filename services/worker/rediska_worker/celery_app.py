"""Celery application configuration for Rediska Worker."""

import os

from celery import Celery
from celery.schedules import crontab

# Celery configuration from environment
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

app = Celery(
    "rediska_worker",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "rediska_worker.tasks.ingest",
        "rediska_worker.tasks.index",
        "rediska_worker.tasks.embed",
        "rediska_worker.tasks.agent",
        "rediska_worker.tasks.discovery",
        "rediska_worker.tasks.evaluation",
        "rediska_worker.tasks.inbox_clear",
        "rediska_worker.tasks.inbox_export",
        "rediska_worker.tasks.inbox_import",
        "rediska_worker.tasks.maintenance",
        "rediska_worker.tasks.message",
        "rediska_worker.tasks.multi_agent_analysis",
        "rediska_worker.tasks.post_copy",
        "rediska_worker.tasks.scout",
    ],
)

# Celery configuration
app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Task execution
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Time limits (seconds)
    task_soft_time_limit=300,  # 5 minutes
    task_time_limit=600,  # 10 minutes
    # Retry settings
    task_default_retry_delay=60,  # 1 minute
    task_max_retries=10,
    # Queue routing.
    #
    # Patterns match REGISTERED TASK NAMES, not module paths. Tasks register
    # under short names (`ingest.sync_delta`, `message.send_manual`), so the
    # `rediska_worker.tasks.<module>.*` globs that used to live here matched
    # nothing and every task fell through to the default `celery` queue. Task
    # names are a public contract -- they appear in `send_task` calls from the
    # core API, in the beat schedule, and in the `jobs` ledger -- so the
    # patterns were rewritten rather than the tasks renamed.
    task_routes={
        "ingest.*": {"queue": "ingest"},
        "index.*": {"queue": "index"},
        "embed.*": {"queue": "embed"},
        "agent.*": {"queue": "agent"},
        "maintenance.*": {"queue": "maintenance"},
        # Post copy detection backfill: a one-off batch beside the backups.
        "copy.*": {"queue": "maintenance"},
        "message.*": {"queue": "messages"},
        "multi_agent_analysis.*": {"queue": "multi_agent_analysis"},
        # Prompt replay shares the analysis queue so it sits behind the inference gate
        "evaluation.*": {"queue": "multi_agent_analysis"},
        "scout.*": {"queue": "scout"},
        # Source discovery mining and trials run beside the scout pipeline
        # they reuse (trials share the inference gate with scout analysis).
        "discovery.*": {"queue": "scout"},
        # Inbox export/import/clear share a dedicated queue so a long export
        # cannot sit behind the nightly maintenance backups.
        "inbox.*": {"queue": "transfer"},
    },
    # Worker settings
    worker_prefetch_multiplier=1,
    worker_concurrency=4,
)

# Beat schedule for periodic tasks
app.conf.beat_schedule = {
    # Documents whose vector is missing or came from another model. Bounded
    # per run; the chained embed after indexing does the routine work, this is
    # the safety net for an endpoint that was down (semantic-similarity-search).
    "embed-sweep-missing": {
        "task": "embed.sweep_missing",
        "schedule": 600.0,  # 10 minutes
        "args": (),
    },
    # Inbox check every 60 seconds - catches new incoming messages quickly.
    # Page-capped, and skipped while another message sync holds the lock.
    "sync-inbox-fast-periodic": {
        "task": "ingest.sync_inbox_fast",
        "schedule": 60.0,  # 1 minute
        "args": (),
    },
    # Sent folder every 5 minutes - it only changes when a message is sent from
    # another Reddit client. (ingest.sync_delta, inbox + sent, is on-demand only:
    # scheduling it re-read the inbox the fast sync already covers.)
    "sync-sent-periodic": {
        "task": "ingest.sync_sent",
        "schedule": 300.0,  # 5 minutes
        "args": (),
    },
    # Scout watches every 5 minutes
    "scout-watches-periodic": {
        "task": "scout.run_all_watches",
        "schedule": 300.0,  # 5 minutes
        "args": (),
    },
    # Daily database backup at 3 AM UTC
    "daily-database-backup": {
        "task": "maintenance.mysql_dump_local",
        "schedule": crontab(hour=3, minute=0),
        "args": (),
    },
    # Daily attachments backup at 4 AM UTC
    "daily-attachments-backup": {
        "task": "maintenance.attachments_snapshot_local",
        "schedule": crontab(hour=4, minute=0),
        "args": (),
    },
    # Weekly restore test on Sunday at 5 AM UTC
    "weekly-restore-test": {
        "task": "maintenance.restore_test_local",
        "schedule": crontab(hour=5, minute=0, day_of_week=0),
        "args": (),
    },
    # Daily scout watch history cleanup at 2 AM UTC
    "daily-scout-history-cleanup": {
        "task": "maintenance.cleanup_scout_watch_history",
        "schedule": crontab(hour=2, minute=0),
        "args": (3,),  # 3 days retention
    },
    # Daily lead expiry at 2:30 AM UTC (scout leads untouched for LEAD_EXPIRY_DAYS).
    # Refuses to run live until a manual dry run has been reviewed.
    "daily-expire-stale-leads": {
        "task": "maintenance.expire_stale_leads",
        "schedule": crontab(hour=2, minute=30),
        "kwargs": {"dry_run": False},
    },
    # Daily source-discovery mining at 2:45 AM UTC (after history cleanup).
    # Reads stored data only: no provider calls, no LLM, no HTTP.
    "daily-source-discovery-mining": {
        "task": "discovery.mine_candidates",
        "schedule": crontab(hour=2, minute=45),
        "args": (),
    },
    # Weekly calibration report on Monday at 6 AM UTC (after the Sunday restore test)
    "weekly-calibration-report": {
        "task": "maintenance.generate_calibration_report",
        "schedule": crontab(hour=6, minute=0, day_of_week=1),
        "args": (),
    },
}


if __name__ == "__main__":
    app.start()
