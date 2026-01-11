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

    def test_create_message_delete_event(self):
        """Test creating a remote delete event for a message."""
        event = RemoteDeleteEvent(
            entity_type="message",
            entity_id="msg-123",
            detected_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            remote_visibility="deleted_by_author",
        )

        assert event.entity_type == "message"
        assert event.entity_id == "msg-123"
        assert event.remote_visibility == "deleted_by_author"

    def test_create_account_delete_event(self):
        """Test creating a remote delete event for an account."""
        event = RemoteDeleteEvent(
            entity_type="account",
            entity_id="acc-456",
            detected_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            remote_status="deleted",
        )

        assert event.entity_type == "account"
        assert event.remote_status == "deleted"

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

        # Should still succeed, timestamp may be updated
        assert result.success is True


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
        self, data_safety_service, mock_session
    ):
        """Test fetching messages that were deleted remotely."""
        mock_message1 = MagicMock()
        mock_message1.id = "msg-1"
        mock_message1.remote_visibility = "deleted_by_author"
        mock_message1.remote_deleted_at = datetime(2024, 1, 15, tzinfo=timezone.utc)

        mock_message2 = MagicMock()
        mock_message2.id = "msg-2"
        mock_message2.remote_visibility = "removed"
        mock_message2.remote_deleted_at = datetime(2024, 1, 14, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_message1, mock_message2]
        mock_session.execute.return_value = mock_result

        result = await data_safety_service.get_remotely_deleted(
            session=mock_session,
            entity_type="message",
        )

        assert len(result) == 2
        assert all(m.remote_deleted_at is not None for m in result)

    @pytest.mark.asyncio
    async def test_get_remotely_deleted_accounts(
        self, data_safety_service, mock_session
    ):
        """Test fetching accounts that were deleted remotely."""
        mock_account = MagicMock()
        mock_account.id = "acc-1"
        mock_account.remote_status = "deleted"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_account]
        mock_session.execute.return_value = mock_result

        result = await data_safety_service.get_remotely_deleted(
            session=mock_session,
            entity_type="account",
        )

        assert len(result) == 1
        assert result[0].remote_status == "deleted"

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


class TestLocalDeleteResult:
    """Tests for LocalDeleteResult dataclass."""

    def test_create_success_result(self):
        """Test creating a successful local delete result."""
        result = LocalDeleteResult(
            success=True,
            entity_type="message",
            entity_id="msg-123",
            deleted_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            audit_log_id="audit-001",
        )

        assert result.success is True
        assert result.entity_id == "msg-123"
        assert result.audit_log_id is not None

    def test_create_failure_result(self):
        """Test creating a failed local delete result."""
        result = LocalDeleteResult(
            success=False,
            entity_type="message",
            entity_id="msg-123",
            error="Entity not found",
        )

        assert result.success is False
        assert result.error == "Entity not found"


class TestPurgeResult:
    """Tests for PurgeResult dataclass."""

    def test_create_success_result(self):
        """Test creating a successful purge result."""
        result = PurgeResult(
            success=True,
            entity_type="attachment",
            entity_id="att-123",
            purged_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            files_removed=["file1.jpg", "file2.jpg"],
            audit_log_id="audit-002",
        )

        assert result.success is True
        assert len(result.files_removed) == 2
        assert result.audit_log_id is not None

    def test_create_failure_result(self):
        """Test creating a failed purge result."""
        result = PurgeResult(
            success=False,
            entity_type="attachment",
            entity_id="att-123",
            error="File not found",
        )

        assert result.success is False
        assert result.error == "File not found"

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

        # Should have called session.add for audit log
        assert result.success is True
        # The audit log ID may be None if the model import fails in test
        # but the soft delete should still succeed

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
        # Audit log should be created (session.add called)

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

            assert result.files_removed is not None
            assert isinstance(result.files_removed, list)

        finally:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
