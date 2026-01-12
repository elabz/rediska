"""Audit log service for Rediska.

Provides audit entry creation and querying with cursor-based pagination.
Audit entries are append-only - they should never be updated or deleted.
"""

import base64
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from rediska_core.domain.models import AuditLog

# Valid values for audit fields
VALID_ACTORS = {"user", "system", "agent"}
VALID_RESULTS = {"ok", "error"}


class AuditService:
    """Service for audit log operations."""

    def __init__(self, db: DBSession):
        """Initialize the audit service.

        Args:
            db: SQLAlchemy database session.
        """
        self.db = db

    def create_entry(
        self,
        actor: str,
        action_type: str,
        result: str,
        provider_id: Optional[str] = None,
        identity_id: Optional[int] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        request_json: Optional[dict] = None,
        response_json: Optional[dict] = None,
        error_detail: Optional[str] = None,
    ) -> AuditLog:
        """Create a new audit log entry.

        Args:
            actor: Who performed the action (user, system, agent).
            action_type: The type of action (e.g., "auth.login").
            result: The result of the action (ok, error).
            provider_id: Optional provider ID.
            identity_id: Optional identity ID.
            entity_type: Optional entity type.
            entity_id: Optional entity ID.
            request_json: Optional request data.
            response_json: Optional response data.
            error_detail: Optional error details (for errors).

        Returns:
            The created AuditLog entry.

        Raises:
            ValueError: If actor or result is invalid.
        """
        # Validate actor
        if actor not in VALID_ACTORS:
            raise ValueError(
                f"actor must be one of {VALID_ACTORS}, got '{actor}'"
            )

        # Validate result
        if result not in VALID_RESULTS:
            raise ValueError(
                f"result must be one of {VALID_RESULTS}, got '{result}'"
            )

        entry = AuditLog(
            ts=datetime.now(timezone.utc),
            actor=actor,
            action_type=action_type,
            result=result,
            provider_id=provider_id,
            identity_id=identity_id,
            entity_type=entity_type,
            entity_id=entity_id,
            request_json=request_json,
            response_json=response_json,
            error_detail=error_detail,
        )

        self.db.add(entry)
        self.db.flush()

        return entry

    def list_entries(
        self,
        action_type: Optional[str] = None,
        actor: Optional[str] = None,
        result: Optional[str] = None,
        provider_id: Optional[str] = None,
        identity_id: Optional[int] = None,
        entity_type: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> tuple[list[AuditLog], Optional[str]]:
        """List audit entries with optional filtering and pagination.

        Args:
            action_type: Filter by action type.
            actor: Filter by actor.
            result: Filter by result.
            provider_id: Filter by provider ID.
            identity_id: Filter by identity ID.
            entity_type: Filter by entity type.
            limit: Maximum number of entries to return.
            cursor: Cursor for pagination.

        Returns:
            Tuple of (list of entries, next cursor or None).
        """
        query = self.db.query(AuditLog)

        # Apply filters
        if action_type:
            query = query.filter(AuditLog.action_type == action_type)
        if actor:
            query = query.filter(AuditLog.actor == actor)
        if result:
            query = query.filter(AuditLog.result == result)
        if provider_id:
            query = query.filter(AuditLog.provider_id == provider_id)
        if identity_id:
            query = query.filter(AuditLog.identity_id == identity_id)
        if entity_type:
            query = query.filter(AuditLog.entity_type == entity_type)

        # Apply cursor if provided
        if cursor:
            cursor_data = self._decode_cursor(cursor)
            if cursor_data:
                cursor_ts, cursor_id = cursor_data
                # Entries with ts < cursor_ts, OR same ts but id < cursor_id
                query = query.filter(
                    (AuditLog.ts < cursor_ts) |
                    ((AuditLog.ts == cursor_ts) & (AuditLog.id < cursor_id))
                )

        # Order by timestamp descending (newest first), then by ID descending
        query = query.order_by(AuditLog.ts.desc(), AuditLog.id.desc())

        # Fetch one extra to check if there are more
        entries = query.limit(limit + 1).all()

        # Determine if there are more entries
        has_more = len(entries) > limit
        if has_more:
            entries = entries[:limit]

        # Generate next cursor
        next_cursor = None
        if has_more and entries:
            last_entry = entries[-1]
            next_cursor = self._encode_cursor(last_entry.ts, last_entry.id)

        return entries, next_cursor

    def count_entries(
        self,
        action_type: Optional[str] = None,
        actor: Optional[str] = None,
        result: Optional[str] = None,
        provider_id: Optional[str] = None,
        identity_id: Optional[int] = None,
        entity_type: Optional[str] = None,
    ) -> int:
        """Count audit entries with optional filtering.

        Args:
            action_type: Filter by action type.
            actor: Filter by actor.
            result: Filter by result.
            provider_id: Filter by provider ID.
            identity_id: Filter by identity ID.
            entity_type: Filter by entity type.

        Returns:
            Count of matching entries.
        """
        query = self.db.query(AuditLog)

        # Apply filters
        if action_type:
            query = query.filter(AuditLog.action_type == action_type)
        if actor:
            query = query.filter(AuditLog.actor == actor)
        if result:
            query = query.filter(AuditLog.result == result)
        if provider_id:
            query = query.filter(AuditLog.provider_id == provider_id)
        if identity_id:
            query = query.filter(AuditLog.identity_id == identity_id)
        if entity_type:
            query = query.filter(AuditLog.entity_type == entity_type)

        return query.count()

    def _encode_cursor(self, ts: datetime, id: int) -> str:
        """Encode a cursor from timestamp and ID.

        Args:
            ts: The timestamp.
            id: The entry ID.

        Returns:
            Base64-encoded cursor string.
        """
        # Ensure timezone-aware
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        cursor_data = {
            "ts": ts.isoformat(),
            "id": id,
        }
        json_str = json.dumps(cursor_data)
        return base64.urlsafe_b64encode(json_str.encode()).decode()

    def _decode_cursor(self, cursor: str) -> Optional[tuple[datetime, int]]:
        """Decode a cursor string.

        Args:
            cursor: The cursor string.

        Returns:
            Tuple of (timestamp, id) or None if invalid.
        """
        try:
            json_str = base64.urlsafe_b64decode(cursor.encode()).decode()
            cursor_data = json.loads(json_str)
            ts = datetime.fromisoformat(cursor_data["ts"])
            # Ensure timezone-aware
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts, cursor_data["id"]
        except Exception:
            return None
