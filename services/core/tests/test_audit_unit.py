"""Unit tests for audit log functionality.

These tests follow TDD - written BEFORE implementation.
Tests cover:
- Audit entry creation
- Audit entry querying with filters
- Cursor-based pagination
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session as DBSession

from tests.factories import create_audit_log, create_identity, create_provider


class TestAuditEntryCreation:
    """Tests for creating audit entries."""

    def test_create_audit_entry_basic(self, db_session: DBSession):
        """Test creating a basic audit entry."""
        from rediska_core.domain.services.audit import AuditService

        service = AuditService(db_session)

        entry = service.create_entry(
            actor="user",
            action_type="test.action",
            result="ok",
        )
        db_session.flush()

        assert entry is not None
        assert entry.id is not None
        assert entry.actor == "user"
        assert entry.action_type == "test.action"
        assert entry.result == "ok"
        assert entry.ts is not None

    def test_create_audit_entry_with_identity(self, db_session: DBSession):
        """Test creating audit entry with identity reference."""
        from rediska_core.domain.services.audit import AuditService

        identity = create_identity(db_session)
        service = AuditService(db_session)

        entry = service.create_entry(
            actor="user",
            action_type="identity.update",
            result="ok",
            identity_id=identity.id,
        )
        db_session.flush()

        assert entry.identity_id == identity.id

    def test_create_audit_entry_with_provider(self, db_session: DBSession):
        """Test creating audit entry with provider reference."""
        from rediska_core.domain.services.audit import AuditService

        provider = create_provider(db_session)
        service = AuditService(db_session)

        entry = service.create_entry(
            actor="system",
            action_type="provider.sync",
            result="ok",
            provider_id=provider.provider_id,
        )
        db_session.flush()

        assert entry.provider_id == provider.provider_id

    def test_create_audit_entry_with_entity(self, db_session: DBSession):
        """Test creating audit entry with entity reference."""
        from rediska_core.domain.services.audit import AuditService

        service = AuditService(db_session)

        entry = service.create_entry(
            actor="user",
            action_type="conversation.archive",
            result="ok",
            entity_type="conversation",
            entity_id=123,
        )
        db_session.flush()

        assert entry.entity_type == "conversation"
        assert entry.entity_id == 123

    def test_create_audit_entry_with_request_response(self, db_session: DBSession):
        """Test creating audit entry with request/response JSON."""
        from rediska_core.domain.services.audit import AuditService

        service = AuditService(db_session)

        request_data = {"username": "testuser"}
        response_data = {"success": True, "user_id": 1}

        entry = service.create_entry(
            actor="user",
            action_type="auth.login",
            result="ok",
            request_json=request_data,
            response_json=response_data,
        )
        db_session.flush()

        assert entry.request_json == request_data
        assert entry.response_json == response_data

    def test_create_audit_entry_with_error(self, db_session: DBSession):
        """Test creating audit entry with error details."""
        from rediska_core.domain.services.audit import AuditService

        service = AuditService(db_session)

        entry = service.create_entry(
            actor="user",
            action_type="auth.login",
            result="error",
            error_detail="Invalid password",
        )
        db_session.flush()

        assert entry.result == "error"
        assert entry.error_detail == "Invalid password"

    def test_create_audit_entry_validates_actor(self, db_session: DBSession):
        """Test that actor must be valid."""
        from rediska_core.domain.services.audit import AuditService

        service = AuditService(db_session)

        with pytest.raises(ValueError, match="actor"):
            service.create_entry(
                actor="invalid",
                action_type="test.action",
                result="ok",
            )

    def test_create_audit_entry_validates_result(self, db_session: DBSession):
        """Test that result must be valid."""
        from rediska_core.domain.services.audit import AuditService

        service = AuditService(db_session)

        with pytest.raises(ValueError, match="result"):
            service.create_entry(
                actor="user",
                action_type="test.action",
                result="invalid",
            )


class TestAuditEntryQuery:
    """Tests for querying audit entries."""

    def test_list_audit_entries_empty(self, db_session: DBSession):
        """Test listing audit entries when none exist."""
        from rediska_core.domain.services.audit import AuditService

        service = AuditService(db_session)

        entries, cursor = service.list_entries(limit=10)

        assert entries == []
        assert cursor is None

    def test_list_audit_entries_basic(self, db_session: DBSession):
        """Test listing audit entries."""
        from rediska_core.domain.services.audit import AuditService

        create_audit_log(db_session, action_type="test.action1")
        create_audit_log(db_session, action_type="test.action2")
        create_audit_log(db_session, action_type="test.action3")
        service = AuditService(db_session)

        entries, cursor = service.list_entries(limit=10)

        assert len(entries) == 3

    def test_list_audit_entries_ordered_by_timestamp_desc(self, db_session: DBSession):
        """Test that entries are ordered by timestamp descending (newest first)."""
        from rediska_core.domain.services.audit import AuditService

        # Create entries with different timestamps
        now = datetime.now(timezone.utc)
        create_audit_log(db_session, action_type="oldest")
        db_session.flush()

        # Manually set timestamps to ensure order
        from rediska_core.domain.models import AuditLog
        entries = db_session.query(AuditLog).all()
        entries[0].ts = now - timedelta(hours=2)
        db_session.flush()

        create_audit_log(db_session, action_type="middle")
        entries = db_session.query(AuditLog).filter_by(action_type="middle").first()
        entries.ts = now - timedelta(hours=1)
        db_session.flush()

        create_audit_log(db_session, action_type="newest")
        entries = db_session.query(AuditLog).filter_by(action_type="newest").first()
        entries.ts = now
        db_session.flush()

        service = AuditService(db_session)
        result, _ = service.list_entries(limit=10)

        assert result[0].action_type == "newest"
        assert result[-1].action_type == "oldest"

    def test_list_audit_entries_with_limit(self, db_session: DBSession):
        """Test listing audit entries with limit."""
        from rediska_core.domain.services.audit import AuditService

        for i in range(5):
            create_audit_log(db_session, action_type=f"test.action{i}")
        service = AuditService(db_session)

        entries, cursor = service.list_entries(limit=3)

        assert len(entries) == 3
        assert cursor is not None

    def test_list_audit_entries_filter_by_action_type(self, db_session: DBSession):
        """Test filtering audit entries by action type."""
        from rediska_core.domain.services.audit import AuditService

        create_audit_log(db_session, action_type="auth.login")
        create_audit_log(db_session, action_type="auth.login")
        create_audit_log(db_session, action_type="auth.logout")
        service = AuditService(db_session)

        entries, _ = service.list_entries(action_type="auth.login", limit=10)

        assert len(entries) == 2
        assert all(e.action_type == "auth.login" for e in entries)

    def test_list_audit_entries_filter_by_identity(self, db_session: DBSession):
        """Test filtering audit entries by identity."""
        from rediska_core.domain.services.audit import AuditService

        identity1 = create_identity(db_session, external_username="user1")
        identity2 = create_identity(db_session, external_username="user2")
        create_audit_log(db_session, action_type="test1", identity=identity1)
        create_audit_log(db_session, action_type="test2", identity=identity1)
        create_audit_log(db_session, action_type="test3", identity=identity2)
        service = AuditService(db_session)

        entries, _ = service.list_entries(identity_id=identity1.id, limit=10)

        assert len(entries) == 2
        assert all(e.identity_id == identity1.id for e in entries)

    def test_list_audit_entries_filter_by_provider(self, db_session: DBSession):
        """Test filtering audit entries by provider."""
        from rediska_core.domain.services.audit import AuditService

        create_audit_log(db_session, action_type="test1", provider_id="reddit")
        create_audit_log(db_session, action_type="test2", provider_id="reddit")
        create_audit_log(db_session, action_type="test3", provider_id="twitter")
        service = AuditService(db_session)

        entries, _ = service.list_entries(provider_id="reddit", limit=10)

        assert len(entries) == 2
        assert all(e.provider_id == "reddit" for e in entries)

    def test_list_audit_entries_filter_by_actor(self, db_session: DBSession):
        """Test filtering audit entries by actor."""
        from rediska_core.domain.services.audit import AuditService

        create_audit_log(db_session, action_type="test1", actor="user")
        create_audit_log(db_session, action_type="test2", actor="system")
        create_audit_log(db_session, action_type="test3", actor="agent")
        service = AuditService(db_session)

        entries, _ = service.list_entries(actor="system", limit=10)

        assert len(entries) == 1
        assert entries[0].actor == "system"

    def test_list_audit_entries_filter_by_result(self, db_session: DBSession):
        """Test filtering audit entries by result."""
        from rediska_core.domain.services.audit import AuditService

        create_audit_log(db_session, action_type="test1", result="ok")
        create_audit_log(db_session, action_type="test2", result="ok")
        create_audit_log(db_session, action_type="test3", result="error")
        service = AuditService(db_session)

        entries, _ = service.list_entries(result="error", limit=10)

        assert len(entries) == 1
        assert entries[0].result == "error"

    def test_list_audit_entries_filter_by_entity(self, db_session: DBSession):
        """Test filtering audit entries by entity type."""
        from rediska_core.domain.services.audit import AuditService

        create_audit_log(db_session, action_type="test1", entity_type="identity")
        create_audit_log(db_session, action_type="test2", entity_type="conversation")
        create_audit_log(db_session, action_type="test3", entity_type="identity")
        service = AuditService(db_session)

        entries, _ = service.list_entries(entity_type="identity", limit=10)

        assert len(entries) == 2
        assert all(e.entity_type == "identity" for e in entries)

    def test_list_audit_entries_combined_filters(self, db_session: DBSession):
        """Test filtering audit entries with multiple filters."""
        from rediska_core.domain.services.audit import AuditService

        identity = create_identity(db_session)
        create_audit_log(db_session, action_type="identity.update", identity=identity, result="ok")
        create_audit_log(db_session, action_type="identity.update", identity=identity, result="error")
        create_audit_log(db_session, action_type="identity.delete", identity=identity, result="ok")
        service = AuditService(db_session)

        entries, _ = service.list_entries(
            action_type="identity.update",
            identity_id=identity.id,
            result="ok",
            limit=10,
        )

        assert len(entries) == 1
        assert entries[0].action_type == "identity.update"
        assert entries[0].result == "ok"


class TestAuditCursorPagination:
    """Tests for cursor-based pagination."""

    def test_cursor_pagination_first_page(self, db_session: DBSession):
        """Test getting first page returns cursor for next page."""
        from rediska_core.domain.services.audit import AuditService

        for i in range(5):
            create_audit_log(db_session, action_type=f"test.action{i}")
        service = AuditService(db_session)

        entries, cursor = service.list_entries(limit=2)

        assert len(entries) == 2
        assert cursor is not None

    def test_cursor_pagination_second_page(self, db_session: DBSession):
        """Test using cursor to get second page."""
        from rediska_core.domain.services.audit import AuditService

        for i in range(5):
            create_audit_log(db_session, action_type=f"test.action{i}")
        service = AuditService(db_session)

        # Get first page
        page1, cursor1 = service.list_entries(limit=2)
        assert cursor1 is not None

        # Get second page
        page2, cursor2 = service.list_entries(limit=2, cursor=cursor1)

        assert len(page2) == 2
        # Pages should not overlap
        page1_ids = {e.id for e in page1}
        page2_ids = {e.id for e in page2}
        assert page1_ids.isdisjoint(page2_ids)

    def test_cursor_pagination_last_page(self, db_session: DBSession):
        """Test that last page returns no cursor."""
        from rediska_core.domain.services.audit import AuditService

        for i in range(3):
            create_audit_log(db_session, action_type=f"test.action{i}")
        service = AuditService(db_session)

        # Get first page
        _, cursor1 = service.list_entries(limit=2)

        # Get second (last) page
        page2, cursor2 = service.list_entries(limit=2, cursor=cursor1)

        assert len(page2) == 1
        assert cursor2 is None

    def test_cursor_pagination_preserves_filters(self, db_session: DBSession):
        """Test that cursor pagination works with filters."""
        from rediska_core.domain.services.audit import AuditService

        # Create mixed entries
        for i in range(5):
            create_audit_log(db_session, action_type="auth.login")
            create_audit_log(db_session, action_type="auth.logout")
        service = AuditService(db_session)

        # Get first page of login events
        page1, cursor1 = service.list_entries(action_type="auth.login", limit=2)
        assert len(page1) == 2
        assert all(e.action_type == "auth.login" for e in page1)

        # Get second page - should still be login events
        page2, cursor2 = service.list_entries(action_type="auth.login", limit=2, cursor=cursor1)
        assert len(page2) == 2
        assert all(e.action_type == "auth.login" for e in page2)

    def test_invalid_cursor_returns_first_page(self, db_session: DBSession):
        """Test that invalid cursor returns first page."""
        from rediska_core.domain.services.audit import AuditService

        for i in range(3):
            create_audit_log(db_session, action_type=f"test.action{i}")
        service = AuditService(db_session)

        entries, _ = service.list_entries(limit=10, cursor="invalid-cursor")

        # Should return all entries (first page)
        assert len(entries) == 3


class TestAuditStatistics:
    """Tests for audit statistics."""

    def test_count_entries(self, db_session: DBSession):
        """Test counting audit entries."""
        from rediska_core.domain.services.audit import AuditService

        for i in range(5):
            create_audit_log(db_session, action_type=f"test.action{i}")
        service = AuditService(db_session)

        count = service.count_entries()

        assert count == 5

    def test_count_entries_with_filter(self, db_session: DBSession):
        """Test counting audit entries with filter."""
        from rediska_core.domain.services.audit import AuditService

        create_audit_log(db_session, action_type="auth.login")
        create_audit_log(db_session, action_type="auth.login")
        create_audit_log(db_session, action_type="auth.logout")
        service = AuditService(db_session)

        count = service.count_entries(action_type="auth.login")

        assert count == 2
