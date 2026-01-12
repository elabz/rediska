"""Idempotency utilities for task execution."""

import hashlib
import json
from typing import Any


def compute_dedupe_key(job_type: str, payload: dict[str, Any]) -> str:
    """Compute a deduplication key for a job."""
    payload_str = json.dumps(payload, sort_keys=True, default=str)
    content = f"{job_type}:{payload_str}"
    return hashlib.sha256(content.encode()).hexdigest()[:32]


class IdempotencyManager:
    """Manage job idempotency using the jobs table."""

    def __init__(self, db_session: Any) -> None:
        self.db = db_session

    async def acquire_lock(self, dedupe_key: str) -> bool:
        """Attempt to acquire a lock for a job."""
        # TODO: Implement with database
        return True

    async def release_lock(self, dedupe_key: str) -> None:
        """Release a job lock."""
        # TODO: Implement with database
        pass

    async def mark_complete(self, dedupe_key: str) -> None:
        """Mark a job as complete."""
        # TODO: Implement with database
        pass

    async def mark_failed(self, dedupe_key: str, error: str) -> None:
        """Mark a job as failed."""
        # TODO: Implement with database
        pass
