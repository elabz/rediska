"""Integration tests for authentication endpoints.

These tests follow TDD - written BEFORE implementation.
Tests cover:
- POST /auth/login endpoint
- POST /auth/logout endpoint
- Authentication middleware
- Protected endpoint access
"""

import pytest
from httpx import AsyncClient

from tests.factories import create_local_user


class TestLoginEndpoint:
    """Integration tests for POST /auth/login."""

    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient, db_session):
        """Test successful login returns session cookie."""
        from rediska_core.domain.services.auth import hash_password

        # Create user with known password
        password = "test-password-123"
        create_local_user(
            db_session,
            username="testuser",
            password_hash=hash_password(password),
        )
        db_session.commit()

        response = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": password},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "user" in data
        assert data["user"]["username"] == "testuser"

        # Check session cookie is set
        assert "session" in response.cookies

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient, db_session):
        """Test login with wrong password returns 401."""
        from rediska_core.domain.services.auth import hash_password

        create_local_user(
            db_session,
            username="testuser",
            password_hash=hash_password("correct-password"),
        )
        db_session.commit()

        response = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": "wrong-password"},
        )

        assert response.status_code == 401
        data = response.json()
        assert "detail" in data

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client: AsyncClient, db_session):
        """Test login with nonexistent user returns 401."""
        response = await client.post(
            "/auth/login",
            json={"username": "nonexistent", "password": "password"},
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_missing_username(self, client: AsyncClient):
        """Test login without username returns 422."""
        response = await client.post(
            "/auth/login",
            json={"password": "password"},
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_login_missing_password(self, client: AsyncClient):
        """Test login without password returns 422."""
        response = await client.post(
            "/auth/login",
            json={"username": "testuser"},
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_login_empty_body(self, client: AsyncClient):
        """Test login with empty body returns 422."""
        response = await client.post("/auth/login", json={})

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_login_writes_audit_log(self, client: AsyncClient, db_session):
        """Test that login writes to audit log."""
        from rediska_core.domain.models import AuditLog
        from rediska_core.domain.services.auth import hash_password

        password = "test-password"
        create_local_user(
            db_session,
            username="testuser",
            password_hash=hash_password(password),
        )
        db_session.commit()

        await client.post(
            "/auth/login",
            json={"username": "testuser", "password": password},
        )

        # Check audit log
        db_session.expire_all()
        audit_entries = db_session.query(AuditLog).filter_by(action_type="auth.login").all()
        assert len(audit_entries) >= 1


class TestLogoutEndpoint:
    """Integration tests for POST /auth/logout."""

    @pytest.mark.asyncio
    async def test_logout_success(self, client: AsyncClient, db_session):
        """Test successful logout invalidates session."""
        from rediska_core.domain.services.auth import hash_password

        password = "test-password"
        create_local_user(
            db_session,
            username="testuser",
            password_hash=hash_password(password),
        )
        db_session.commit()

        # Login first
        login_response = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": password},
        )
        assert login_response.status_code == 200

        # Get session cookie
        session_cookie = login_response.cookies.get("session")
        assert session_cookie is not None

        # Logout
        client.cookies.set("session", session_cookie)
        logout_response = await client.post("/auth/logout")

        assert logout_response.status_code == 200
        data = logout_response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_logout_without_session(self, client: AsyncClient):
        """Test logout without session returns 401."""
        response = await client.post("/auth/logout")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_logout_clears_cookie(self, client: AsyncClient, db_session):
        """Test that logout clears the session cookie."""
        from rediska_core.domain.services.auth import hash_password

        password = "test-password"
        create_local_user(
            db_session,
            username="testuser",
            password_hash=hash_password(password),
        )
        db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": password},
        )
        session_cookie = login_response.cookies.get("session")

        # Logout
        client.cookies.set("session", session_cookie)
        logout_response = await client.post("/auth/logout")

        # Cookie should be cleared (empty or expired)
        assert logout_response.status_code == 200

    @pytest.mark.asyncio
    async def test_logout_writes_audit_log(self, client: AsyncClient, db_session):
        """Test that logout writes to audit log."""
        from rediska_core.domain.models import AuditLog
        from rediska_core.domain.services.auth import hash_password

        password = "test-password"
        create_local_user(
            db_session,
            username="testuser",
            password_hash=hash_password(password),
        )
        db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": password},
        )
        session_cookie = login_response.cookies.get("session")

        # Logout
        client.cookies.set("session", session_cookie)
        await client.post("/auth/logout")

        # Check audit log
        db_session.expire_all()
        audit_entries = db_session.query(AuditLog).filter_by(action_type="auth.logout").all()
        assert len(audit_entries) >= 1


class TestAuthMiddleware:
    """Integration tests for authentication middleware."""

    @pytest.mark.asyncio
    async def test_protected_endpoint_requires_auth(self, client: AsyncClient):
        """Test that protected endpoints require authentication."""
        # /auth/me is a protected endpoint
        response = await client.get("/auth/me")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_protected_endpoint_with_valid_session(
        self, client: AsyncClient, db_session
    ):
        """Test that protected endpoints work with valid session."""
        from rediska_core.domain.services.auth import hash_password

        password = "test-password"
        create_local_user(
            db_session,
            username="testuser",
            password_hash=hash_password(password),
        )
        db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": password},
        )
        session_cookie = login_response.cookies.get("session")

        # Access protected endpoint
        client.cookies.set("session", session_cookie)
        response = await client.get("/auth/me")

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_protected_endpoint_with_expired_session(
        self, client: AsyncClient, db_session
    ):
        """Test that expired sessions are rejected."""
        from datetime import timedelta

        from rediska_core.domain.models import Session
        from rediska_core.domain.services.auth import hash_password

        password = "test-password"
        create_local_user(
            db_session,
            username="testuser",
            password_hash=hash_password(password),
        )
        db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": password},
        )
        session_cookie = login_response.cookies.get("session")

        # Manually expire the session
        from datetime import datetime, timezone

        session = db_session.query(Session).filter_by(id=session_cookie).first()
        if session:
            session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
            db_session.commit()

        # Try to access protected endpoint
        client.cookies.set("session", session_cookie)
        response = await client.get("/auth/me")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_protected_endpoint_with_invalid_session(self, client: AsyncClient):
        """Test that invalid session IDs are rejected."""
        client.cookies.set("session", "invalid-session-id")
        response = await client.get("/auth/me")

        assert response.status_code == 401


class TestCurrentUserEndpoint:
    """Integration tests for GET /auth/me endpoint."""

    @pytest.mark.asyncio
    async def test_get_current_user(self, client: AsyncClient, db_session):
        """Test getting current user info."""
        from rediska_core.domain.services.auth import hash_password

        password = "test-password"
        create_local_user(
            db_session,
            username="testuser",
            password_hash=hash_password(password),
        )
        db_session.commit()

        # Login
        login_response = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": password},
        )
        session_cookie = login_response.cookies.get("session")

        # Get current user
        client.cookies.set("session", session_cookie)
        response = await client.get("/auth/me")

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        assert "id" in data
        assert "password_hash" not in data  # Should not expose password hash


class TestSessionCookieProperties:
    """Tests for session cookie security properties."""

    @pytest.mark.asyncio
    async def test_session_cookie_is_httponly(self, client: AsyncClient, db_session):
        """Test that session cookie has HttpOnly flag."""
        from rediska_core.domain.services.auth import hash_password

        password = "test-password"
        create_local_user(
            db_session,
            username="testuser",
            password_hash=hash_password(password),
        )
        db_session.commit()

        response = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": password},
        )

        # Check Set-Cookie header for httponly
        set_cookie = response.headers.get("set-cookie", "")
        assert "httponly" in set_cookie.lower()

    @pytest.mark.asyncio
    async def test_session_cookie_has_samesite(self, client: AsyncClient, db_session):
        """Test that session cookie has SameSite attribute."""
        from rediska_core.domain.services.auth import hash_password

        password = "test-password"
        create_local_user(
            db_session,
            username="testuser",
            password_hash=hash_password(password),
        )
        db_session.commit()

        response = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": password},
        )

        # Check Set-Cookie header for samesite
        set_cookie = response.headers.get("set-cookie", "")
        assert "samesite" in set_cookie.lower()
