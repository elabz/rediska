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
        "rediska_worker.tasks.maintenance",
        "rediska_worker.tasks.message",
        "rediska_worker.tasks.multi_agent_analysis",
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
    # Queue routing
    task_routes={
        "rediska_worker.tasks.ingest.*": {"queue": "ingest"},
        "rediska_worker.tasks.index.*": {"queue": "index"},
        "rediska_worker.tasks.embed.*": {"queue": "embed"},
        "rediska_worker.tasks.agent.*": {"queue": "agent"},
        "rediska_worker.tasks.maintenance.*": {"queue": "maintenance"},
        "rediska_worker.tasks.message.*": {"queue": "messages"},
        "rediska_worker.tasks.multi_agent_analysis.*": {"queue": "multi_agent_analysis"},
        "rediska_worker.tasks.scout.*": {"queue": "scout"},
        "scout.*": {"queue": "scout"},
    },
    # Worker settings
    worker_prefetch_multiplier=1,
    worker_concurrency=4,
)

# Beat schedule for periodic tasks
app.conf.beat_schedule = {
    # Fast inbox check every 60 seconds - catches new incoming messages quickly
    "sync-inbox-fast-periodic": {
        "task": "ingest.sync_inbox_fast",
        "schedule": 60.0,  # 1 minute
        "args": (),
    },
    # Full sync (inbox + sent) every 2 minutes with early-exit optimization
    "sync-delta-periodic": {
        "task": "ingest.sync_delta",
        "schedule": 120.0,  # 2 minutes (reduced from 10 minutes)
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
}


if __name__ == "__main__":
    app.start()
