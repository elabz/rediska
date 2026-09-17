"""Inbox clear background task.

Deletes conversations, messages, and message-linked attachment records while
preserving providers, identities, credentials, external accounts, leads, and
profile data. Attachment files are left on disk so a later import restores
working references.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

from rediska_worker.celery_app import app

logger = logging.getLogger(__name__)


def _get_db_session() -> Any:
    """Create a synchronous DB session for this task."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    mysql_url = os.getenv(
        "MYSQL_URL", "mysql+pymysql://root:password@localhost:3306/rediska"
    )
    engine = create_engine(mysql_url, pool_pre_ping=True)
    return sessionmaker(bind=engine)()


@app.task(name="inbox.clear", bind=True, max_retries=0)
def clear_inbox(self, confirm: bool = False) -> dict:
    """Delete all inbox content.

    `max_retries=0` -- this is destructive, so a transient failure must not
    silently re-run it. The service writes its own audit_log entry.

    Args:
        confirm: Must be True. The API layer requires a typed confirmation
            phrase before ever passing True here.

    Returns:
        Summary dict with per-entity deletion counts.
    """
    from rediska_core.domain.services.inbox_transfer import InboxClearService

    started_at = datetime.now(timezone.utc)
    db = _get_db_session()

    try:
        def progress(stage: str, done: int, total: int) -> None:
            self.update_state(
                state="PROGRESS",
                meta={"stage": stage, "done": done, "total": total},
            )

        service = InboxClearService(db=db)
        summary = service.clear(confirm=confirm, progress=progress)

        summary["status"] = "completed"
        summary["started_at"] = started_at.isoformat()
        summary["completed_at"] = datetime.now(timezone.utc).isoformat()
        return summary
    except ValueError as exc:
        logger.error("Inbox clear rejected: %s", exc)
        return {"status": "rejected", "error": str(exc)}
    except Exception:
        logger.exception("Inbox clear failed; changes were rolled back")
        raise
    finally:
        db.close()
