"""Unit tests for data safety service - no-remote-delete policy."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rediska_core.domain.services.data_safety import (
    DataSafetyService,
    RemoteDeleteEvent,
    LocalDeleteResult,
    PurgeResult,
)


class TestRemoteDeleteEvent:
    """Tests for RemoteDeleteEvent dataclass."""

    def test_event_to_dict(self):
        """Test converting event to dictionary for audit logging."""
        event = RemoteDeleteEvent(
            entity_type="message",
            entity_id="msg-123",
            detected_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            remote_visibility="deleted_by_author",
        )

        result = event.to_dict()

        assert result["entity_type"] == "message"
        assert result["entity_id"] == "msg-123"
        assert "detected_at" in result


class TestNoRemoteDeletePolicy:
    """Tests for no-remote-delete policy."""

    @pytest.fixture
    def data_safety_service(self, test_settings):
        """Create DataSafetyService for testing."""
        return DataSafetyService(test_settings)

    @pytest.fixture
    def mock_session(self):
        """Create mock database session."""
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_mark_message_as_remotely_deleted_preserves_local_data(
        self, data_safety_service, mock_session
    ):
        """Test that marking a message as remotely deleted preserves local content."""
        # Arrange
        mock_message = MagicMock()
        mock_message.id = "msg-123"
        mock_message.body = "Original message content"
        mock_message.deleted_at = None
        mock_message.remote_visibility = "visible"
        mock_message.remote_deleted_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_message
        mock_session.execute.return_value = mock_result

        # Act
        result = await data_safety_service.mark_remote_deleted(
            session=mock_session,
            entity_type="message",
            entity_id="msg-123",
            remote_visibility="deleted_by_author",
        )

        # Assert - local data preserved
        assert result.success is True
        assert result.local_data_preserved is True
        assert mock_message.body == "Original message content"  # Body not cleared
        assert mock_message.deleted_at is None  # Not locally deleted
        assert mock_message.remote_visibility == "deleted_by_author"
        assert mock_message.remote_deleted_at is not None

    @pytest.mark.asyncio
    async def test_mark_account_as_remotely_deleted_preserves_local_data(
        self, data_safety_service, mock_session
    ):
        """Test that marking an account as remotely deleted preserves local data."""
        # Arrange
        mock_account = MagicMock()
        mock_account.id = "acc-456"
        mock_account.username = "testuser"
        mock_account.deleted_at = None
        mock_account.remote_status = "active"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_account
        mock_session.execute.return_value = mock_result

        # Act
        result = await data_safety_service.mark_remote_deleted(
            session=mock_session,
            entity_type="account",
            entity_id="acc-456",
            remote_status="deleted",
        )

        # Assert
        assert result.success is True
        assert result.local_data_preserved is True
        assert mock_account.username == "testuser"  # Username preserved
        assert mock_account.deleted_at is None  # Not locally deleted
        assert mock_account.remote_status == "deleted"

    @pytest.mark.asyncio
    async def test_mark_attachment_as_remotely_deleted_preserves_file(
        self, data_safety_service, mock_session
    ):
        """Test that marking an attachment as remotely deleted preserves the file."""
        # Arrange
        mock_attachment = MagicMock()
        mock_attachment.id = "att-789"
        mock_attachment.file_path = "/attachments/file.jpg"
        mock_attachment.deleted_at = None
        mock_attachment.remote_visibility = "visible"
        mock_attachment.remote_deleted_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_attachment
        mock_session.execute.return_value = mock_result

        # Act
        result = await data_safety_service.mark_remote_deleted(
            session=mock_session,
            entity_type="attachment",
            entity_id="att-789",
            remote_visibility="deleted_by_author",
        )

        # Assert - file path preserved
        assert result.success is True
        assert result.local_data_preserved is True
        assert mock_attachment.file_path == "/attachments/file.jpg"
        assert mock_attachment.remote_visibility == "deleted_by_author"

    @pytest.mark.asyncio
    async def test_mark_lead_post_as_remotely_deleted(
        self, data_safety_service, mock_session
    ):
        """Test that marking a lead post as remotely deleted preserves content."""
        # Arrange
        mock_lead = MagicMock()
        mock_lead.id = "lead-001"
        mock_lead.body = "Lead post content"
        mock_lead.deleted_at = None
        mock_lead.remote_visibility = "visible"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_lead
        mock_session.execute.return_value = mock_result

        # Act
        result = await data_safety_service.mark_remote_deleted(
            session=mock_session,
            entity_type="lead_post",
            entity_id="lead-001",
            remote_visibility="removed",
        )

        # Assert
        assert result.success is True
        assert mock_lead.body == "Lead post content"
        assert mock_lead.remote_visibility == "removed"

    @pytest.mark.asyncio
    async def test_mark_nonexistent_entity_returns_failure(
        self, data_safety_service, mock_session
    ):
        """Test that marking a non-existent entity returns failure."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await data_safety_service.mark_remote_deleted(
            session=mock_session,
            entity_type="message",
            entity_id="nonexistent",
            remote_visibility="deleted_by_author",
        )

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_mark_invalid_entity_type_returns_failure(
        self, data_safety_service, mock_session
    ):
        """Test that an invalid entity type returns failure."""
        result = await data_safety_service.mark_remote_deleted(
            session=mock_session,
            entity_type="invalid_type",
            entity_id="123",
            remote_visibility="deleted",
        )

        assert result.success is False
        assert "invalid" in result.error.lower() or "unknown" in result.error.lower()

    @pytest.mark.asyncio
    async def test_already_remotely_deleted_entity_updates_timestamp(
        self, data_safety_service, mock_session
    ):
        """Test that re-detecting remote deletion updates the timestamp."""
        original_time = datetime(2024, 1, 10, 12, 0, 0, tzinfo=timezone.utc)

        mock_message = MagicMock()
        mock_message.id = "msg-123"
        mock_message.remote_visibility = "deleted_by_author"
        mock_message.remote_deleted_at = original_time

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_message
        mock_session.execute.return_value = mock_result

        result = await data_safety_service.mark_remote_deleted(
            session=mock_session,
            entity_type="message",
            entity_id="msg-123",
            remote_visibility="deleted_by_author",
        )

        assert result.success is True
        # Re-detection must actually advance the recorded timestamp on the
        # entity (and report it), not leave the stale 2024-01-10 value.
        assert mock_message.remote_deleted_at > original_time
        assert result.remote_deleted_at == mock_message.remote_deleted_at
        # Local content is still not deleted by a re-detected remote delete.
        assert mock_message.remote_visibility == "deleted_by_author"
        assert result.local_data_preserved is True


class TestQueryRemotelyDeletedEntities:
    """Tests for querying entities that were deleted remotely."""

    @pytest.fixture
    def data_safety_service(self, test_settings):
        """Create DataSafetyService for testing."""
        return DataSafetyService(test_settings)

    @pytest.fixture
    def mock_session(self):
        """Create mock database session."""
        session = AsyncMock()
        session.execute = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_get_remotely_deleted_messages(
        self, data_safety_service, async_db_session
    ):
        """Only messages with remote_deleted_at set come back.

        Run against a real session with a MIX of deleted and visible rows so
        the WHERE clause -- the only logic in this method -- is exercised. A
        preloaded mock would return whatever it was handed even if the filter
        were dropped entirely.
        """
        from rediska_core.domain.models import Conversation, Message, Provider

        async_db_session.add(
            Provider(provider_id="reddit", display_name="Reddit", enabled=True)
        )
        conversation = Conversation(
            provider_id="reddit",
            identity_id=1,
            counterpart_account_id=1,
            external_conversation_id="conv_1",
        )
        async_db_session.add(conversation)
        await async_db_session.flush()

        def make_message(visibility, remote_deleted_at):
            return Message(
                provider_id="reddit",
                conversation_id=conversation.id,
                direction="in",
                sent_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                body_text="body",
                remote_visibility=visibility,
                remote_deleted_at=remote_deleted_at,
            )

        deleted_a = make_message(
            "deleted_by_author", datetime(2024, 1, 15, tzinfo=timezone.utc)
        )
        deleted_b = make_message("removed", datetime(2024, 1, 14, tzinfo=timezone.utc))
        # Decoys the filter must exclude.
        visible = make_message("visible", None)
        unknown = make_message("unknown", None)

        async_db_session.add_all([deleted_a, deleted_b, visible, unknown])
        await async_db_session.flush()

        result = await data_safety_service.get_remotely_deleted(
            session=async_db_session,
            entity_type="message",
        )

        assert {m.id for m in result} == {deleted_a.id, deleted_b.id}
        assert all(m.remote_deleted_at is not None for m in result)

    @pytest.mark.asyncio
    async def test_get_remotely_deleted_accounts(
        self, data_safety_service, async_db_session
    ):
        """Accounts are filtered on remote_status, not remote_deleted_at.

        DELETED_ACCOUNT_STATES covers deleted/suspended/banned; active and
        unknown accounts must be excluded.
        """
        from rediska_core.domain.models import ExternalAccount, Provider

        async_db_session.add(
            Provider(provider_id="reddit", display_name="Reddit", enabled=True)
        )

        def make_account(username, status):
            return ExternalAccount(
                provider_id="reddit",
                external_username=username,
                external_user_id=f"t2_{username}",
                remote_status=status,
            )

        deleted = make_account("gone_user", "deleted")
        suspended = make_account("suspended_user", "suspended")
        # Decoys.
        active = make_account("active_user", "active")
        unknown = make_account("unknown_user", "unknown")

        async_db_session.add_all([deleted, suspended, active, unknown])
        await async_db_session.flush()

        result = await data_safety_service.get_remotely_deleted(
            session=async_db_session,
            entity_type="account",
        )

        assert {a.id for a in result} == {deleted.id, suspended.id}
        assert all(a.remote_status in ("deleted", "suspended") for a in result)

    @pytest.mark.asyncio
    async def test_is_remotely_deleted_returns_true_for_deleted(
        self, data_safety_service, mock_session
    ):
        """Test checking if an entity was deleted remotely."""
        mock_message = MagicMock()
        mock_message.remote_visibility = "deleted_by_author"
        mock_message.remote_deleted_at = datetime(2024, 1, 15, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_message
        mock_session.execute.return_value = mock_result

        is_deleted = await data_safety_service.is_remotely_deleted(
            session=mock_session,
            entity_type="message",
            entity_id="msg-123",
        )

        assert is_deleted is True

    @pytest.mark.asyncio
    async def test_is_remotely_deleted_returns_false_for_visible(
        self, data_safety_service, mock_session
    ):
        """Test that visible entities are not marked as remotely deleted."""
        mock_message = MagicMock()
        mock_message.remote_visibility = "visible"
        mock_message.remote_deleted_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_message
        mock_session.execute.return_value = mock_result

        is_deleted = await data_safety_service.is_remotely_deleted(
            session=mock_session,
            entity_type="message",
            entity_id="msg-123",
        )

        assert is_deleted is False


class TestPurgeResult:
    """Tests for PurgeResult dataclass."""

    def test_to_dict(self):
        """Test converting purge result to dictionary."""
        result = PurgeResult(
            success=True,
            entity_type="attachment",
            entity_id="att-123",
            purged_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            files_removed=["file1.jpg"],
            audit_log_id="audit-002",
        )

        result_dict = result.to_dict()

        assert "success" in result_dict
        assert "purged_at" in result_dict
        assert "files_removed" in result_dict


class TestLocalSoftDelete:
    """Tests for local soft-delete functionality."""

    @pytest.fixture
    def data_safety_service(self, test_settings):
        """Create DataSafetyService for testing."""
        return DataSafetyService(test_settings)

    @pytest.fixture
    def mock_session(self):
        """Create mock database session."""
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_soft_delete_message_sets_deleted_at(
        self, data_safety_service, mock_session
    ):
        """Test that soft-deleting a message sets deleted_at timestamp."""
        mock_message = MagicMock()
        mock_message.id = "msg-123"
        mock_message.deleted_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_message
        mock_session.execute.return_value = mock_result

        result = await data_safety_service.soft_delete(
            session=mock_session,
            entity_type="message",
            entity_id="msg-123",
            actor_id="user-001",
            reason="User requested deletion",
        )

        assert result.success is True
        assert mock_message.deleted_at is not None
        assert result.deleted_at is not None

    @pytest.mark.asyncio
    async def test_soft_delete_creates_audit_log(
        self, data_safety_service, mock_session
    ):
        """Test that soft-delete creates an audit log entry."""
        mock_message = MagicMock()
        mock_message.id = "msg-123"
        mock_message.deleted_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_message
        mock_session.execute.return_value = mock_result

        result = await data_safety_service.soft_delete(
            session=mock_session,
            entity_type="message",
            entity_id="msg-123",
            actor_id="user-001",
            reason="Spam content",
        )

        assert result.success is True

        # Assert the audit row is really constructed and added. This used to be
        # left as a comment, which hid a live bug: _create_audit_log passed
        # column names the AuditLog model does not have, so it raised TypeError
        # into a bare `except` and no delete was ever audited.
        from rediska_core.domain.models import AuditLog

        added = [call.args[0] for call in mock_session.add.call_args_list]
        entries = [obj for obj in added if isinstance(obj, AuditLog)]
        assert len(entries) == 1

        entry = entries[0]
        assert entry.action_type == "data_safety.soft_delete"
        assert entry.actor == "user"
        assert entry.entity_type == "message"
        assert entry.request_json["actor_id"] == "user-001"
        assert entry.request_json["reason"] == "Spam content"

    @pytest.mark.asyncio
    async def test_soft_delete_preserves_data(
        self, data_safety_service, mock_session
    ):
        """Test that soft-delete preserves the entity data."""
        mock_message = MagicMock()
        mock_message.id = "msg-123"
        mock_message.body = "Original content"
        mock_message.deleted_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_message
        mock_session.execute.return_value = mock_result

        await data_safety_service.soft_delete(
            session=mock_session,
            entity_type="message",
            entity_id="msg-123",
        )

        # Body should still be present
        assert mock_message.body == "Original content"

    @pytest.mark.asyncio
    async def test_soft_delete_nonexistent_entity_fails(
        self, data_safety_service, mock_session
    ):
        """Test that soft-deleting a non-existent entity fails."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await data_safety_service.soft_delete(
            session=mock_session,
            entity_type="message",
            entity_id="nonexistent",
        )

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_soft_delete_invalid_entity_type_fails(
        self, data_safety_service, mock_session
    ):
        """Test that soft-deleting with invalid entity type fails."""
        result = await data_safety_service.soft_delete(
            session=mock_session,
            entity_type="invalid_type",
            entity_id="123",
        )

        assert result.success is False
        assert "unknown" in result.error.lower()

    @pytest.mark.asyncio
    async def test_soft_delete_account(
        self, data_safety_service, mock_session
    ):
        """Test soft-deleting an account."""
        mock_account = MagicMock()
        mock_account.id = "acc-456"
        mock_account.deleted_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_account
        mock_session.execute.return_value = mock_result

        result = await data_safety_service.soft_delete(
            session=mock_session,
            entity_type="account",
            entity_id="acc-456",
        )

        assert result.success is True
        assert mock_account.deleted_at is not None

    @pytest.mark.asyncio
    async def test_soft_delete_conversation(
        self, data_safety_service, mock_session
    ):
        """Test soft-deleting a conversation."""
        mock_conversation = MagicMock()
        mock_conversation.id = "conv-789"
        mock_conversation.deleted_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_conversation
        mock_session.execute.return_value = mock_result

        result = await data_safety_service.soft_delete(
            session=mock_session,
            entity_type="conversation",
            entity_id="conv-789",
        )

        assert result.success is True


class TestPurgeOperation:
    """Tests for purge (permanent deletion) functionality."""

    @pytest.fixture
    def data_safety_service(self, test_settings):
        """Create DataSafetyService for testing."""
        return DataSafetyService(test_settings)

    @pytest.fixture
    def mock_session(self):
        """Create mock database session."""
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_purge_sets_purged_at(
        self, data_safety_service, mock_session
    ):
        """Test that purging an entity sets purged_at timestamp."""
        mock_message = MagicMock()
        mock_message.id = "msg-123"
        mock_message.deleted_at = None
        mock_message.purged_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_message
        mock_session.execute.return_value = mock_result

        result = await data_safety_service.purge(
            session=mock_session,
            entity_type="message",
            entity_id="msg-123",
            actor_id="admin-001",
            reason="GDPR request",
        )

        assert result.success is True
        assert mock_message.purged_at is not None
        assert result.purged_at is not None

    @pytest.mark.asyncio
    async def test_purge_also_sets_deleted_at_if_not_set(
        self, data_safety_service, mock_session
    ):
        """Test that purge sets deleted_at if not already set."""
        mock_message = MagicMock()
        mock_message.id = "msg-123"
        mock_message.deleted_at = None
        mock_message.purged_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_message
        mock_session.execute.return_value = mock_result

        await data_safety_service.purge(
            session=mock_session,
            entity_type="message",
            entity_id="msg-123",
        )

        assert mock_message.deleted_at is not None

    @pytest.mark.asyncio
    async def test_purge_attachment_removes_file(
        self, data_safety_service, mock_session
    ):
        """Test that purging an attachment removes the file."""
        import tempfile
        import os

        # Create a temporary file to be "purged"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
            f.write(b"test image data")
            temp_file_path = f.name

        try:
            # Update service to use temp directory
            temp_dir = os.path.dirname(temp_file_path)
            data_safety_service._attachments_path = temp_dir

            mock_attachment = MagicMock()
            mock_attachment.id = "att-123"
            mock_attachment.file_path = os.path.basename(temp_file_path)
            mock_attachment.deleted_at = None
            mock_attachment.purged_at = None

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_attachment
            mock_session.execute.return_value = mock_result

            result = await data_safety_service.purge(
                session=mock_session,
                entity_type="attachment",
                entity_id="att-123",
            )

            assert result.success is True
            assert len(result.files_removed) == 1
            # File should be deleted
            assert not os.path.exists(temp_file_path)

        finally:
            # Cleanup if file still exists
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    @pytest.mark.asyncio
    async def test_purge_creates_audit_log(
        self, data_safety_service, mock_session
    ):
        """Test that purge creates an audit log entry."""
        mock_message = MagicMock()
        mock_message.id = "msg-123"
        mock_message.deleted_at = None
        mock_message.purged_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_message
        mock_session.execute.return_value = mock_result

        result = await data_safety_service.purge(
            session=mock_session,
            entity_type="message",
            entity_id="msg-123",
            actor_id="admin-001",
            reason="GDPR deletion request",
        )

        assert result.success is True

        # A purge is permanently destructive, so the audit row matters most
        # here. Previously this was only a comment and no purge was ever
        # audited -- see test_soft_delete_creates_audit_log.
        from rediska_core.domain.models import AuditLog

        added = [call.args[0] for call in mock_session.add.call_args_list]
        entries = [obj for obj in added if isinstance(obj, AuditLog)]
        assert len(entries) == 1

        entry = entries[0]
        assert entry.action_type == "data_safety.purge"
        assert entry.actor == "user"
        assert entry.request_json["actor_id"] == "admin-001"
        assert entry.request_json["reason"] == "GDPR deletion request"
        assert "files_removed" in entry.request_json

    @pytest.mark.asyncio
    async def test_purge_nonexistent_entity_fails(
        self, data_safety_service, mock_session
    ):
        """Test that purging a non-existent entity fails."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await data_safety_service.purge(
            session=mock_session,
            entity_type="message",
            entity_id="nonexistent",
        )

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_purge_invalid_entity_type_fails(
        self, data_safety_service, mock_session
    ):
        """Test that purging with invalid entity type fails."""
        result = await data_safety_service.purge(
            session=mock_session,
            entity_type="invalid_type",
            entity_id="123",
        )

        assert result.success is False
        assert "unknown" in result.error.lower()

    @pytest.mark.asyncio
    async def test_purge_result_includes_files_removed(
        self, data_safety_service, mock_session
    ):
        """Test that purge result includes list of removed files."""
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
            f.write(b"test pdf data")
            temp_file_path = f.name

        try:
            temp_dir = os.path.dirname(temp_file_path)
            data_safety_service._attachments_path = temp_dir

            mock_attachment = MagicMock()
            mock_attachment.id = "att-456"
            mock_attachment.file_path = os.path.basename(temp_file_path)
            mock_attachment.deleted_at = None
            mock_attachment.purged_at = None

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_attachment
            mock_session.execute.return_value = mock_result

            result = await data_safety_service.purge(
                session=mock_session,
                entity_type="attachment",
                entity_id="att-456",
            )

            # Name the exact file. `is not None` / isinstance(list) were both
            # guaranteed by PurgeResult's default_factory=list, so they passed
            # even when file removal silently no-opped.
            assert result.files_removed == [os.path.basename(temp_file_path)]
            # ...and the file really is gone from disk.
            assert not os.path.exists(temp_file_path)

        finally:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
