"""Data safety service for handling deletion policies.

This service implements the no-remote-delete policy:
- Remote deletions are tracked but local data is preserved
- Local soft-delete marks items as deleted but keeps data
- Purge permanently removes data and associated files
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rediska_core.config import Settings

if TYPE_CHECKING:
    pass


class EntityType(Enum):
    """Supported entity types for data safety operations."""

    MESSAGE = "message"
    ACCOUNT = "account"
    ATTACHMENT = "attachment"
    LEAD_POST = "lead_post"
    CONVERSATION = "conversation"


@dataclass
class RemoteDeleteEvent:
    """Represents a detected remote deletion event."""

    entity_type: str
    entity_id: str
    detected_at: datetime
    remote_visibility: Optional[str] = None
    remote_status: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for audit logging."""
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "detected_at": self.detected_at.isoformat(),
            "remote_visibility": self.remote_visibility,
            "remote_status": self.remote_status,
        }


@dataclass
class RemoteDeleteResult:
    """Result of marking an entity as remotely deleted."""

    success: bool
    entity_type: str
    entity_id: str
    local_data_preserved: bool = True
    remote_deleted_at: Optional[datetime] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "local_data_preserved": self.local_data_preserved,
            "remote_deleted_at": self.remote_deleted_at.isoformat() if self.remote_deleted_at else None,
            "error": self.error,
        }


@dataclass
class LocalDeleteResult:
    """Result of a local soft-delete operation."""

    success: bool
    entity_type: str
    entity_id: str
    deleted_at: Optional[datetime] = None
    audit_log_id: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "audit_log_id": self.audit_log_id,
            "error": self.error,
        }


@dataclass
class PurgeResult:
    """Result of a permanent purge operation."""

    success: bool
    entity_type: str
    entity_id: str
    purged_at: Optional[datetime] = None
    files_removed: list[str] = field(default_factory=list)
    audit_log_id: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "purged_at": self.purged_at.isoformat() if self.purged_at else None,
            "files_removed": self.files_removed,
            "audit_log_id": self.audit_log_id,
            "error": self.error,
        }


# Remote visibility states indicating deletion
DELETED_VISIBILITY_STATES = {"deleted_by_author", "removed", "hidden"}

# Remote account status states indicating deletion
DELETED_ACCOUNT_STATES = {"deleted", "suspended", "banned"}


class DataSafetyService:
    """Service for handling data safety and deletion policies.

    Implements the no-remote-delete policy where:
    1. Remote deletions are tracked but local data is preserved
    2. Local soft-delete marks items without removing data
    3. Purge permanently removes data (with audit trail)
    """

    # Map entity types to model classes
    ENTITY_MODEL_MAP = {
        "message": "Message",
        "account": "ExternalAccount",
        "attachment": "Attachment",
        "lead_post": "LeadPost",
        "conversation": "Conversation",
    }

    def __init__(self, settings: Settings):
        """Initialize data safety service."""
        self._settings = settings
        self._attachments_path = settings.attachments_path

    def _get_model_class(self, entity_type: str):
        """Get the SQLAlchemy model class for an entity type."""
        from rediska_core.domain import models

        model_name = self.ENTITY_MODEL_MAP.get(entity_type)
        if not model_name:
            return None

        return getattr(models, model_name, None)

    async def mark_remote_deleted(
        self,
        session: AsyncSession,
        entity_type: str,
        entity_id: str,
        remote_visibility: Optional[str] = None,
        remote_status: Optional[str] = None,
    ) -> RemoteDeleteResult:
        """Mark an entity as deleted remotely while preserving local data.

        This implements the no-remote-delete policy: when content is deleted
        on the remote platform, we track the deletion but keep all local data.

        Args:
            session: Database session
            entity_type: Type of entity (message, account, attachment, lead_post)
            entity_id: ID of the entity
            remote_visibility: New remote visibility state (for content)
            remote_status: New remote status (for accounts)

        Returns:
            RemoteDeleteResult with success status and details
        """
        # Validate entity type
        model_class = self._get_model_class(entity_type)
        if not model_class:
            return RemoteDeleteResult(
                success=False,
                entity_type=entity_type,
                entity_id=entity_id,
                local_data_preserved=True,
                error=f"Unknown entity type: {entity_type}",
            )

        # Fetch the entity
        stmt = select(model_class).where(model_class.id == entity_id)
        result = await session.execute(stmt)
        entity = result.scalar_one_or_none()

        if entity is None:
            return RemoteDeleteResult(
                success=False,
                entity_type=entity_type,
                entity_id=entity_id,
                local_data_preserved=True,
                error=f"Entity not found: {entity_type} {entity_id}",
            )

        now = datetime.now(timezone.utc)

        # Update remote deletion tracking based on entity type
        if entity_type == "account":
            if remote_status:
                entity.remote_status = remote_status
        else:
            # For content types (message, attachment, lead_post)
            if remote_visibility:
                entity.remote_visibility = remote_visibility
            if hasattr(entity, "remote_deleted_at"):
                entity.remote_deleted_at = now

        await session.commit()

        return RemoteDeleteResult(
            success=True,
            entity_type=entity_type,
            entity_id=entity_id,
            local_data_preserved=True,
            remote_deleted_at=now,
        )

    async def get_remotely_deleted(
        self,
        session: AsyncSession,
        entity_type: str,
        limit: int = 100,
    ) -> list[Any]:
        """Get entities that were deleted remotely but preserved locally.

        Args:
            session: Database session
            entity_type: Type of entity to query
            limit: Maximum number of results

        Returns:
            List of entities that were deleted remotely
        """
        model_class = self._get_model_class(entity_type)
        if not model_class:
            return []

        if entity_type == "account":
            # For accounts, check remote_status
            stmt = (
                select(model_class)
                .where(model_class.remote_status.in_(DELETED_ACCOUNT_STATES))
                .limit(limit)
            )
        else:
            # For content, check remote_visibility and remote_deleted_at
            stmt = (
                select(model_class)
                .where(model_class.remote_deleted_at.isnot(None))
                .limit(limit)
            )

        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def is_remotely_deleted(
        self,
        session: AsyncSession,
        entity_type: str,
        entity_id: str,
    ) -> bool:
        """Check if an entity was deleted remotely.

        Args:
            session: Database session
            entity_type: Type of entity
            entity_id: ID of the entity

        Returns:
            True if the entity was deleted remotely
        """
        model_class = self._get_model_class(entity_type)
        if not model_class:
            return False

        stmt = select(model_class).where(model_class.id == entity_id)
        result = await session.execute(stmt)
        entity = result.scalar_one_or_none()

        if entity is None:
            return False

        if entity_type == "account":
            return entity.remote_status in DELETED_ACCOUNT_STATES
        else:
            # For content types
            if hasattr(entity, "remote_visibility"):
                return entity.remote_visibility in DELETED_VISIBILITY_STATES
            if hasattr(entity, "remote_deleted_at"):
                return entity.remote_deleted_at is not None

        return False

    async def soft_delete(
        self,
        session: AsyncSession,
        entity_type: str,
        entity_id: str,
        actor_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> LocalDeleteResult:
        """Soft-delete an entity locally (mark as deleted, keep data).

        Args:
            session: Database session
            entity_type: Type of entity
            entity_id: ID of the entity
            actor_id: ID of user performing the delete
            reason: Reason for deletion

        Returns:
            LocalDeleteResult with success status
        """
        model_class = self._get_model_class(entity_type)
        if not model_class:
            return LocalDeleteResult(
                success=False,
                entity_type=entity_type,
                entity_id=entity_id,
                error=f"Unknown entity type: {entity_type}",
            )

        stmt = select(model_class).where(model_class.id == entity_id)
        result = await session.execute(stmt)
        entity = result.scalar_one_or_none()

        if entity is None:
            return LocalDeleteResult(
                success=False,
                entity_type=entity_type,
                entity_id=entity_id,
                error=f"Entity not found: {entity_type} {entity_id}",
            )

        now = datetime.now(timezone.utc)
        entity.deleted_at = now

        # Create audit log entry
        audit_log_id = await self._create_audit_log(
            session=session,
            action="soft_delete",
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id,
            reason=reason,
        )

        await session.commit()

        return LocalDeleteResult(
            success=True,
            entity_type=entity_type,
            entity_id=entity_id,
            deleted_at=now,
            audit_log_id=audit_log_id,
        )

    async def purge(
        self,
        session: AsyncSession,
        entity_type: str,
        entity_id: str,
        actor_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> PurgeResult:
        """Permanently purge an entity and its associated files.

        This is a destructive operation that:
        1. Removes associated files from disk
        2. Marks the entity as purged
        3. Creates an audit log entry

        Args:
            session: Database session
            entity_type: Type of entity
            entity_id: ID of the entity
            actor_id: ID of user performing the purge
            reason: Reason for purge

        Returns:
            PurgeResult with success status and files removed
        """
        model_class = self._get_model_class(entity_type)
        if not model_class:
            return PurgeResult(
                success=False,
                entity_type=entity_type,
                entity_id=entity_id,
                error=f"Unknown entity type: {entity_type}",
            )

        stmt = select(model_class).where(model_class.id == entity_id)
        result = await session.execute(stmt)
        entity = result.scalar_one_or_none()

        if entity is None:
            return PurgeResult(
                success=False,
                entity_type=entity_type,
                entity_id=entity_id,
                error=f"Entity not found: {entity_type} {entity_id}",
            )

        now = datetime.now(timezone.utc)
        files_removed = []

        # Handle file removal for attachments
        if entity_type == "attachment" and hasattr(entity, "file_path"):
            file_path = entity.file_path
            if file_path:
                try:
                    full_path = Path(self._attachments_path) / file_path
                    if full_path.exists():
                        full_path.unlink()
                        files_removed.append(str(file_path))
                except Exception:
                    pass  # File removal is best-effort

        # Mark as purged
        if hasattr(entity, "purged_at"):
            entity.purged_at = now

        # Also set deleted_at if not already set
        if hasattr(entity, "deleted_at") and entity.deleted_at is None:
            entity.deleted_at = now

        # Create audit log entry
        audit_log_id = await self._create_audit_log(
            session=session,
            action="purge",
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id,
            reason=reason,
            extra_data={"files_removed": files_removed},
        )

        await session.commit()

        return PurgeResult(
            success=True,
            entity_type=entity_type,
            entity_id=entity_id,
            purged_at=now,
            files_removed=files_removed,
            audit_log_id=audit_log_id,
        )

    async def _create_audit_log(
        self,
        session: AsyncSession,
        action: str,
        entity_type: str,
        entity_id: str,
        actor_id: Optional[str] = None,
        reason: Optional[str] = None,
        extra_data: Optional[dict] = None,
    ) -> Optional[str]:
        """Create an audit log entry for a data safety operation.

        Args:
            session: Database session
            action: The action performed (soft_delete, purge)
            entity_type: Type of entity
            entity_id: ID of the entity
            actor_id: ID of user performing the action
            reason: Reason for the action
            extra_data: Additional data to log

        Returns:
            ID of the created audit log entry, or None if creation failed
        """
        try:
            from rediska_core.domain import models

            import json
            import uuid

            details = {
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "reason": reason,
            }
            if extra_data:
                details.update(extra_data)

            audit_log = models.AuditLog(
                id=str(uuid.uuid4()),
                action=f"data_safety.{action}",
                actor_id=actor_id,
                entity_type=entity_type,
                entity_id=entity_id,
                details=json.dumps(details),
                created_at=datetime.now(timezone.utc),
            )

            session.add(audit_log)
            return audit_log.id

        except Exception:
            # Audit log creation is best-effort
            return None
