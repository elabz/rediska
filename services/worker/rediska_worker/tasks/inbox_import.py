"""Inbox import background task.

Named `inbox_import` rather than `import` because `import` is a reserved Python
keyword and cannot appear in a module path.
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rediska_worker.celery_app import app

logger = logging.getLogger(__name__)

ATTACHMENTS_PATH = os.getenv("ATTACHMENTS_PATH", "/var/lib/rediska/attachments")


def _get_db_session() -> Any:
    """Create a synchronous DB session for this task."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    mysql_url = os.getenv(
        "MYSQL_URL", "mysql+pymysql://root:password@localhost:3306/rediska"
    )
    engine = create_engine(mysql_url, pool_pre_ping=True)
    return sessionmaker(bind=engine)()


# Overrides the global 5/10-minute limits: restoring a full inbox can outrun
# them, and a mid-flight kill would roll back all the work done so far.
@app.task(
    name="inbox.import",
    bind=True,
    max_retries=0,
    soft_time_limit=3600,
    time_limit=3900,
)
def import_inbox(self, dump_path: str) -> dict:
    """Restore inbox content from a JSON dump file.

    The restore is atomic: any failure rolls the whole transaction back, so a
    failed import never leaves the inbox partially populated. `max_retries=0`
    because a retry would re-run a destructive-adjacent operation without the
    user asking for it; the user re-triggers explicitly instead.

    Args:
        dump_path: Absolute path to the dump file to restore.

    Returns:
        Summary dict with per-entity created/skipped counts and warnings.
    """
    from rediska_core.domain.services.inbox_transfer import (
        InboxImportService,
        InvalidDumpError,
    )

    started_at = datetime.now(timezone.utc)
    db = _get_db_session()

    try:
        def progress(stage: str, done: int, total: int) -> None:
            self.update_state(
                state="PROGRESS",
                meta={
                    "stage": stage,
                    "done": done,
                    "total": total,
                    "percent": round(done / total * 100, 1) if total else 100.0,
                },
            )

        service = InboxImportService(db=db, attachments_path=ATTACHMENTS_PATH)

        try:
            dump = service.load(Path(dump_path))
        except InvalidDumpError as exc:
            logger.error("Inbox import rejected an invalid dump: %s", exc)
            return {
                "status": "rejected",
                "error": str(exc),
                "started_at": started_at.isoformat(),
            }

        summary = service.restore(dump, progress=progress)
        summary["status"] = "completed"
        summary["started_at"] = started_at.isoformat()
        summary["completed_at"] = datetime.now(timezone.utc).isoformat()

        missing = summary["warnings"]["missing_files"]
        if missing:
            logger.warning(
                "Inbox import completed with %d missing attachment file(s)", len(missing)
            )

        return summary
    except Exception:
        logger.exception("Inbox import failed; changes were rolled back")
        raise
    finally:
        db.close()
