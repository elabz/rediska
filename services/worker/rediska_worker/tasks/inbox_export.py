"""Inbox export background task.

Export runs in the background because a large inbox would otherwise exceed the
HTTP request timeout. Progress is reported through the Celery task state so the
UI can poll it.
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rediska_worker.celery_app import app

logger = logging.getLogger(__name__)

BACKUPS_PATH = os.getenv("BACKUPS_PATH", "/var/lib/rediska/backups")
ATTACHMENTS_PATH = os.getenv("ATTACHMENTS_PATH", "/var/lib/rediska/attachments")

EXPORT_SUBDIR = "inbox-exports"


def _get_db_session() -> Any:
    """Create a synchronous DB session for this task."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    mysql_url = os.getenv(
        "MYSQL_URL", "mysql+pymysql://root:password@localhost:3306/rediska"
    )
    engine = create_engine(mysql_url, pool_pre_ping=True)
    return sessionmaker(bind=engine)()


def export_dir() -> Path:
    """Directory that holds generated inbox dumps."""
    return Path(BACKUPS_PATH) / EXPORT_SUBDIR


# Overrides the global 5/10-minute limits: a full-inbox dump can outrun them.
@app.task(
    name="inbox.export",
    bind=True,
    max_retries=2,
    soft_time_limit=3600,
    time_limit=3900,
)
def export_inbox(self, filename: str | None = None) -> dict:
    """Export all inbox content to a JSON dump file.

    Args:
        filename: Optional dump filename. Defaults to a UTC-timestamped name.

    Returns:
        Summary dict with the dump path, counts, and any missing-file warnings.
    """
    from rediska_core.domain.services.inbox_transfer import InboxExportService

    started_at = datetime.now(timezone.utc)

    if not filename:
        filename = f"inbox_{started_at.strftime('%Y-%m-%d_%H%M%S')}.json"
    # Never let a caller-supplied name escape the export directory.
    filename = Path(filename).name

    db = _get_db_session()
    try:
        def progress(stage: str, done: int, total: int) -> None:
            self.update_state(
                state="PROGRESS",
                meta={"stage": stage, "done": done, "total": total},
            )

        service = InboxExportService(db=db, attachments_path=ATTACHMENTS_PATH)
        summary = service.write_dump(export_dir() / filename, progress=progress)

        summary["started_at"] = started_at.isoformat()
        summary["completed_at"] = datetime.now(timezone.utc).isoformat()

        missing = summary["warnings"]["missing_files"]
        if missing:
            logger.warning(
                "Inbox export completed with %d missing attachment file(s)", len(missing)
            )

        return summary
    except Exception as exc:
        logger.exception("Inbox export failed")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
