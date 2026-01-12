"""Integration tests for Reddit OAuth endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from tests.factories import create_local_user, create_provider


class TestRedditOAuthStartEndpoint:
    """Integration tests for GET /providers/reddit/oauth/start."""

    @pytest.mark.asyncio
    async def test_oauth_start_returns_authorization_url(
        self, client: AsyncClient, db_session
    ):
        """OAuth start should return an authorization URL."""
        from rediska_core.domain.services.auth import hash_password

        # Create user and login
        create_local_user(db_session, username="testuser", password_hash=hash_password("pass"))
        create_provider(db_session, provider_id="reddit", display_name="Reddit")
        db_session.commit()

        login_resp = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": "pass"},
        )
        session_cookie = login_resp.cookies.get("session")
        client.cookies.set("session", session_cookie)

        response = await client.get("/providers/reddit/oauth/start")

        assert response.status_code == 200
        data = response.json()
        assert "authorization_url" in data
        assert "https://www.reddit.com/api/v1/authorize" in data["authorization_url"]
        assert "state" in data

    @pytest.mark.asyncio
    async def test_oauth_start_requires_authentication(self, client: AsyncClient):
        """OAuth start should require authentication."""
        response = await client.get("/providers/reddit/oauth/start")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_oauth_start_requires_reddit_enabled(
        self, client: AsyncClient, db_session, test_settings
    ):
        """OAuth start should fail if Reddit provider is disabled."""
        from rediska_core.domain.services.auth import hash_password

        create_local_user(db_session, username="testuser", password_hash=hash_password("pass"))
        # Create provider but disabled
        create_provider(db_session, provider_id="reddit", display_name="Reddit", enabled=False)
        db_session.commit()

        login_resp = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": "pass"},
        )
        session_cookie = login_resp.cookies.get("session")
        client.cookies.set("session", session_cookie)

        response = await client.get("/providers/reddit/oauth/start")

        assert response.status_code == 400
        assert "not enabled" in response.json()["detail"].lower()


class TestRedditOAuthCallbackEndpoint:
    """Integration tests for GET /providers/reddit/oauth/callback."""

    @pytest.mark.asyncio
    async def test_oauth_callback_success(self, client: AsyncClient, db_session):
        """OAuth callback should exchange code and create identity."""
        from rediska_core.domain.models import Identity
        from rediska_core.domain.services.auth import hash_password

        create_local_user(db_session, username="testuser", password_hash=hash_password("pass"))
        create_provider(db_session, provider_id="reddit", display_name="Reddit")
        db_session.commit()

        # Login
        login_resp = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": "pass"},
        )
        session_cookie = login_resp.cookies.get("session")
        client.cookies.set("session", session_cookie)

        # Start OAuth to get valid state
        start_resp = await client.get("/providers/reddit/oauth/start")
        state = start_resp.json()["state"]

        # Mock the token exchange and identity fetch
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "test_access",
            "refresh_token": "test_refresh",
            "token_type": "bearer",
            "expires_in": 3600,
        }

        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {
            "name": "reddit_user",
            "id": "t2_reddit",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = token_response
            mock_instance.get.return_value = user_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            response = await client.get(
                "/providers/reddit/oauth/callback",
                params={"code": "test_code", "state": state},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "identity" in data
        assert data["identity"]["external_username"] == "reddit_user"

        # Verify identity was created
        identity = db_session.query(Identity).filter_by(
            provider_id="reddit",
            external_username="reddit_user",
        ).first()
        assert identity is not None

    @pytest.mark.asyncio
    async def test_oauth_callback_invalid_state(self, client: AsyncClient, db_session):
        """OAuth callback should reject invalid state."""
        from rediska_core.domain.services.auth import hash_password

        create_local_user(db_session, username="testuser", password_hash=hash_password("pass"))
        create_provider(db_session, provider_id="reddit", display_name="Reddit")
        db_session.commit()

        login_resp = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": "pass"},
        )
        session_cookie = login_resp.cookies.get("session")
        client.cookies.set("session", session_cookie)

        response = await client.get(
            "/providers/reddit/oauth/callback",
            params={"code": "test_code", "state": "invalid_state"},
        )

        assert response.status_code == 400
        assert "Invalid state" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_oauth_callback_requires_code(self, client: AsyncClient, db_session):
        """OAuth callback should require code parameter."""
        from rediska_core.domain.services.auth import hash_password

        create_local_user(db_session, username="testuser", password_hash=hash_password("pass"))
        create_provider(db_session, provider_id="reddit", display_name="Reddit")
        db_session.commit()

        login_resp = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": "pass"},
        )
        session_cookie = login_resp.cookies.get("session")
        client.cookies.set("session", session_cookie)

        response = await client.get(
            "/providers/reddit/oauth/callback",
            params={"state": "some_state"},
        )

        # 400 because code is required when error is not present
        assert response.status_code == 400
        assert "code" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_oauth_callback_handles_error_response(
        self, client: AsyncClient, db_session
    ):
        """OAuth callback should handle error parameter from Reddit."""
        from rediska_core.domain.services.auth import hash_password

        create_local_user(db_session, username="testuser", password_hash=hash_password("pass"))
        create_provider(db_session, provider_id="reddit", display_name="Reddit")
        db_session.commit()

        login_resp = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": "pass"},
        )
        session_cookie = login_resp.cookies.get("session")
        client.cookies.set("session", session_cookie)

        # Start OAuth to get valid state
        start_resp = await client.get("/providers/reddit/oauth/start")
        state = start_resp.json()["state"]

        # Reddit sends error instead of code
        response = await client.get(
            "/providers/reddit/oauth/callback",
            params={"error": "access_denied", "state": state},
        )

        assert response.status_code == 400
        assert "access_denied" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_oauth_callback_writes_audit_log(self, client: AsyncClient, db_session):
        """OAuth callback should write audit log entry."""
        from rediska_core.domain.models import AuditLog
        from rediska_core.domain.services.auth import hash_password

        create_local_user(db_session, username="testuser", password_hash=hash_password("pass"))
        create_provider(db_session, provider_id="reddit", display_name="Reddit")
        db_session.commit()

        login_resp = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": "pass"},
        )
        session_cookie = login_resp.cookies.get("session")
        client.cookies.set("session", session_cookie)

        start_resp = await client.get("/providers/reddit/oauth/start")
        state = start_resp.json()["state"]

        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "test",
            "refresh_token": "test",
            "token_type": "bearer",
            "expires_in": 3600,
        }

        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"name": "audituser", "id": "t2_audit"}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = token_response
            mock_instance.get.return_value = user_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            await client.get(
                "/providers/reddit/oauth/callback",
                params={"code": "test_code", "state": state},
            )

        # Check audit log
        db_session.expire_all()
        audit = db_session.query(AuditLog).filter_by(
            action_type="provider.oauth.complete"
        ).first()
        assert audit is not None
        assert audit.provider_id == "reddit"
        assert audit.result == "ok"
