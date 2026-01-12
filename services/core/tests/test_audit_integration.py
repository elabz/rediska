"""Integration tests for audit log query endpoint.

These tests follow TDD - written BEFORE implementation.
Tests cover:
- GET /audit endpoint
- Filtering by action_type, identity_id, provider_id, etc.
- Cursor-based pagination
"""

import pytest
from httpx import AsyncClient

from tests.factories import create_audit_log, create_identity, create_local_user, create_provider


async def login_user(client: AsyncClient, db_session, username="testuser", password="test-password"):
    """Helper to login a user and return the session cookie."""
    from rediska_core.domain.services.auth import hash_password

    create_local_user(
        db_session,
        username=username,
        password_hash=hash_password(password),
    )
    db_session.commit()

    response = await client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    return response.cookies.get("session")


class TestAuditListEndpoint:
    """Integration tests for GET /audit."""

    @pytest.mark.asyncio
    async def test_list_audit_requires_auth(self, client: AsyncClient):
        """Test that listing audit entries requires authentication."""
        response = await client.get("/audit")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_list_audit_empty(self, client: AsyncClient, db_session):
        """Test listing audit entries when only login entry exists."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        # Create an identity to bypass onboarding gate
        create_identity(db_session, is_active=True)
        db_session.commit()

        response = await client.get("/audit")

        assert response.status_code == 200
        data = response.json()
        assert "entries" in data
        assert "total" in data
        # At least the login entry should exist
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_list_audit_with_entries(self, client: AsyncClient, db_session):
        """Test listing audit entries with data."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        # Create identity to bypass onboarding gate
        create_identity(db_session, is_active=True)

        # Create some audit entries
        create_audit_log(db_session, action_type="test.action1")
        create_audit_log(db_session, action_type="test.action2")
        create_audit_log(db_session, action_type="test.action3")
        db_session.commit()

        response = await client.get("/audit")

        assert response.status_code == 200
        data = response.json()
        # Should have at least the 3 test entries plus login
        assert data["total"] >= 3

    @pytest.mark.asyncio
    async def test_list_audit_with_limit(self, client: AsyncClient, db_session):
        """Test listing audit entries with limit."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_identity(db_session, is_active=True)

        for i in range(10):
            create_audit_log(db_session, action_type=f"test.action{i}")
        db_session.commit()

        response = await client.get("/audit?limit=5")

        assert response.status_code == 200
        data = response.json()
        assert len(data["entries"]) == 5
        assert data["next_cursor"] is not None

    @pytest.mark.asyncio
    async def test_list_audit_filter_by_action_type(self, client: AsyncClient, db_session):
        """Test filtering audit entries by action type."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_identity(db_session, is_active=True)

        create_audit_log(db_session, action_type="identity.create")
        create_audit_log(db_session, action_type="identity.create")
        create_audit_log(db_session, action_type="identity.update")
        db_session.commit()

        response = await client.get("/audit?action_type=identity.create")

        assert response.status_code == 200
        data = response.json()
        assert all(e["action_type"] == "identity.create" for e in data["entries"])

    @pytest.mark.asyncio
    async def test_list_audit_filter_by_identity_id(self, client: AsyncClient, db_session):
        """Test filtering audit entries by identity ID."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        identity = create_identity(db_session, is_active=True)
        create_audit_log(db_session, action_type="test1", identity=identity)
        create_audit_log(db_session, action_type="test2", identity=identity)
        create_audit_log(db_session, action_type="test3")  # No identity
        db_session.commit()

        response = await client.get(f"/audit?identity_id={identity.id}")

        assert response.status_code == 200
        data = response.json()
        assert all(e["identity_id"] == identity.id for e in data["entries"])

    @pytest.mark.asyncio
    async def test_list_audit_filter_by_provider_id(self, client: AsyncClient, db_session):
        """Test filtering audit entries by provider ID."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_identity(db_session, is_active=True)

        create_audit_log(db_session, action_type="test1", provider_id="reddit")
        create_audit_log(db_session, action_type="test2", provider_id="reddit")
        create_audit_log(db_session, action_type="test3", provider_id="twitter")
        db_session.commit()

        response = await client.get("/audit?provider_id=reddit")

        assert response.status_code == 200
        data = response.json()
        assert all(e["provider_id"] == "reddit" for e in data["entries"])

    @pytest.mark.asyncio
    async def test_list_audit_filter_by_actor(self, client: AsyncClient, db_session):
        """Test filtering audit entries by actor."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_identity(db_session, is_active=True)

        create_audit_log(db_session, action_type="test1", actor="user")
        create_audit_log(db_session, action_type="test2", actor="system")
        create_audit_log(db_session, action_type="test3", actor="agent")
        db_session.commit()

        response = await client.get("/audit?actor=system")

        assert response.status_code == 200
        data = response.json()
        assert len(data["entries"]) >= 1
        assert all(e["actor"] == "system" for e in data["entries"])

    @pytest.mark.asyncio
    async def test_list_audit_filter_by_result(self, client: AsyncClient, db_session):
        """Test filtering audit entries by result."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_identity(db_session, is_active=True)

        create_audit_log(db_session, action_type="test1", result="ok")
        create_audit_log(db_session, action_type="test2", result="error")
        db_session.commit()

        response = await client.get("/audit?result=error")

        assert response.status_code == 200
        data = response.json()
        assert all(e["result"] == "error" for e in data["entries"])

    @pytest.mark.asyncio
    async def test_list_audit_filter_by_entity_type(self, client: AsyncClient, db_session):
        """Test filtering audit entries by entity type."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_identity(db_session, is_active=True)

        create_audit_log(db_session, action_type="test1", entity_type="identity")
        create_audit_log(db_session, action_type="test2", entity_type="conversation")
        db_session.commit()

        response = await client.get("/audit?entity_type=identity")

        assert response.status_code == 200
        data = response.json()
        assert all(e["entity_type"] == "identity" for e in data["entries"])

    @pytest.mark.asyncio
    async def test_list_audit_combined_filters(self, client: AsyncClient, db_session):
        """Test filtering audit entries with multiple filters."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        identity = create_identity(db_session, is_active=True)
        create_audit_log(
            db_session,
            action_type="identity.update",
            identity=identity,
            result="ok",
        )
        create_audit_log(
            db_session,
            action_type="identity.update",
            identity=identity,
            result="error",
        )
        create_audit_log(
            db_session,
            action_type="identity.delete",
            identity=identity,
            result="ok",
        )
        db_session.commit()

        response = await client.get(
            f"/audit?action_type=identity.update&identity_id={identity.id}&result=ok"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["entries"]) == 1
        assert data["entries"][0]["action_type"] == "identity.update"
        assert data["entries"][0]["result"] == "ok"


class TestAuditCursorPagination:
    """Integration tests for cursor-based pagination."""

    @pytest.mark.asyncio
    async def test_pagination_first_page(self, client: AsyncClient, db_session):
        """Test getting first page returns cursor."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_identity(db_session, is_active=True)

        for i in range(10):
            create_audit_log(db_session, action_type=f"test.action{i}")
        db_session.commit()

        response = await client.get("/audit?limit=5")

        assert response.status_code == 200
        data = response.json()
        assert len(data["entries"]) == 5
        assert data["next_cursor"] is not None

    @pytest.mark.asyncio
    async def test_pagination_second_page(self, client: AsyncClient, db_session):
        """Test using cursor to get second page."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_identity(db_session, is_active=True)

        for i in range(10):
            create_audit_log(db_session, action_type=f"test.action{i}")
        db_session.commit()

        # Get first page
        response1 = await client.get("/audit?limit=5")
        data1 = response1.json()
        cursor = data1["next_cursor"]

        # Get second page
        response2 = await client.get(f"/audit?limit=5&cursor={cursor}")

        assert response2.status_code == 200
        data2 = response2.json()

        # Pages should not overlap
        ids1 = {e["id"] for e in data1["entries"]}
        ids2 = {e["id"] for e in data2["entries"]}
        assert ids1.isdisjoint(ids2)

    @pytest.mark.asyncio
    async def test_pagination_last_page(self, client: AsyncClient, db_session):
        """Test that last page returns no cursor."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_identity(db_session, is_active=True)

        for i in range(3):
            create_audit_log(db_session, action_type=f"test.action{i}")
        db_session.commit()

        # Get first page with limit larger than total
        response = await client.get("/audit?limit=100")

        assert response.status_code == 200
        data = response.json()
        # Should have no next cursor when all entries fit
        # (next_cursor could be None or absent)
        assert data.get("next_cursor") is None

    @pytest.mark.asyncio
    async def test_pagination_with_filters(self, client: AsyncClient, db_session):
        """Test that pagination works with filters."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_identity(db_session, is_active=True)

        # Create mixed entries
        for i in range(8):
            create_audit_log(db_session, action_type="target.action")
            create_audit_log(db_session, action_type="other.action")
        db_session.commit()

        # Get first page of target actions
        response1 = await client.get("/audit?action_type=target.action&limit=3")
        data1 = response1.json()

        assert len(data1["entries"]) == 3
        assert all(e["action_type"] == "target.action" for e in data1["entries"])

        if data1["next_cursor"]:
            # Get second page
            response2 = await client.get(
                f"/audit?action_type=target.action&limit=3&cursor={data1['next_cursor']}"
            )
            data2 = response2.json()

            # Should still be filtered
            assert all(e["action_type"] == "target.action" for e in data2["entries"])


class TestAuditEntryResponse:
    """Tests for audit entry response format."""

    @pytest.mark.asyncio
    async def test_audit_entry_contains_required_fields(self, client: AsyncClient, db_session):
        """Test that audit entries contain all required fields."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_identity(db_session, is_active=True)

        create_audit_log(
            db_session,
            action_type="test.action",
            actor="user",
            result="ok",
            entity_type="test",
            entity_id=123,
        )
        db_session.commit()

        response = await client.get("/audit?action_type=test.action")

        assert response.status_code == 200
        data = response.json()
        entry = data["entries"][0]

        # Check required fields
        assert "id" in entry
        assert "ts" in entry
        assert "actor" in entry
        assert "action_type" in entry
        assert "result" in entry

    @pytest.mark.asyncio
    async def test_audit_entry_contains_optional_fields(self, client: AsyncClient, db_session):
        """Test that audit entries contain optional fields when present."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        identity = create_identity(db_session, is_active=True)

        create_audit_log(
            db_session,
            action_type="test.action",
            identity=identity,
            provider_id="reddit",
            entity_type="conversation",
            entity_id=456,
            request_json={"key": "value"},
            response_json={"result": "data"},
        )
        db_session.commit()

        response = await client.get("/audit?action_type=test.action")

        assert response.status_code == 200
        data = response.json()
        entry = data["entries"][0]

        # Check optional fields
        assert entry["identity_id"] == identity.id
        assert entry["provider_id"] == "reddit"
        assert entry["entity_type"] == "conversation"
        assert entry["entity_id"] == 456
        assert entry["request_json"] == {"key": "value"}
        assert entry["response_json"] == {"result": "data"}

    @pytest.mark.asyncio
    async def test_audit_entry_with_error_detail(self, client: AsyncClient, db_session):
        """Test that error details are included in response."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_identity(db_session, is_active=True)

        create_audit_log(
            db_session,
            action_type="test.error",
            result="error",
            error_detail="Something went wrong",
        )
        db_session.commit()

        response = await client.get("/audit?action_type=test.error")

        assert response.status_code == 200
        data = response.json()
        entry = data["entries"][0]

        assert entry["result"] == "error"
        assert entry["error_detail"] == "Something went wrong"


class TestAuditListResponseFormat:
    """Tests for audit list response format."""

    @pytest.mark.asyncio
    async def test_response_contains_metadata(self, client: AsyncClient, db_session):
        """Test that response contains proper metadata."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_identity(db_session, is_active=True)

        for i in range(5):
            create_audit_log(db_session, action_type=f"test.action{i}")
        db_session.commit()

        response = await client.get("/audit?limit=3")

        assert response.status_code == 200
        data = response.json()

        assert "entries" in data
        assert "total" in data
        assert "limit" in data
        assert "next_cursor" in data
        assert data["limit"] == 3
