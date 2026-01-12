"""Integration tests for identity management endpoints.

These tests follow TDD - written BEFORE implementation.
Tests cover:
- Identity CRUD endpoints
- Onboarding gate middleware
- Setup status endpoint
"""

import pytest
from httpx import AsyncClient

from tests.factories import create_identity, create_local_user, create_provider


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


class TestIdentityListEndpoint:
    """Integration tests for GET /identities."""

    @pytest.mark.asyncio
    async def test_list_identities_requires_auth(self, client: AsyncClient):
        """Test that listing identities requires authentication."""
        response = await client.get("/identities")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_list_identities_empty(self, client: AsyncClient, db_session):
        """Test listing identities when none exist."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        response = await client.get("/identities")

        assert response.status_code == 200
        data = response.json()
        assert data["identities"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_identities_with_data(self, client: AsyncClient, db_session):
        """Test listing identities with data."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        provider = create_provider(db_session)
        create_identity(db_session, provider=provider, external_username="user1")
        create_identity(db_session, provider=provider, external_username="user2")
        db_session.commit()

        response = await client.get("/identities")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["identities"]) == 2

    @pytest.mark.asyncio
    async def test_list_identities_filter_by_provider(self, client: AsyncClient, db_session):
        """Test filtering identities by provider."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        provider1 = create_provider(db_session, provider_id="reddit")
        provider2 = create_provider(db_session, provider_id="twitter")
        create_identity(db_session, provider=provider1, external_username="reddit_user")
        create_identity(db_session, provider=provider2, external_username="twitter_user")
        db_session.commit()

        response = await client.get("/identities?provider_id=reddit")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["identities"][0]["provider_id"] == "reddit"

    @pytest.mark.asyncio
    async def test_list_identities_grouped(self, client: AsyncClient, db_session):
        """Test listing identities grouped by provider."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        provider1 = create_provider(db_session, provider_id="reddit")
        provider2 = create_provider(db_session, provider_id="twitter")
        create_identity(db_session, provider=provider1, external_username="reddit_user")
        create_identity(db_session, provider=provider2, external_username="twitter_user")
        db_session.commit()

        response = await client.get("/identities?grouped=true")

        assert response.status_code == 200
        data = response.json()
        assert "reddit" in data["by_provider"]
        assert "twitter" in data["by_provider"]


class TestIdentityCreateEndpoint:
    """Integration tests for POST /identities."""

    @pytest.mark.asyncio
    async def test_create_identity_requires_auth(self, client: AsyncClient):
        """Test that creating identity requires authentication."""
        response = await client.post(
            "/identities",
            json={
                "provider_id": "reddit",
                "external_username": "my_account",
                "display_name": "My Account",
            },
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_create_identity_success(self, client: AsyncClient, db_session):
        """Test creating an identity successfully."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_provider(db_session, provider_id="reddit")
        db_session.commit()

        response = await client.post(
            "/identities",
            json={
                "provider_id": "reddit",
                "external_username": "my_account",
                "display_name": "My Account",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] is not None
        assert data["provider_id"] == "reddit"
        assert data["external_username"] == "my_account"
        assert data["display_name"] == "My Account"
        assert data["is_active"] is True

    @pytest.mark.asyncio
    async def test_create_identity_with_voice_config(self, client: AsyncClient, db_session):
        """Test creating identity with voice configuration."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_provider(db_session, provider_id="reddit")
        db_session.commit()

        voice_config = {
            "system_prompt": "You are friendly.",
            "tone": "casual",
        }

        response = await client.post(
            "/identities",
            json={
                "provider_id": "reddit",
                "external_username": "my_account",
                "display_name": "My Account",
                "voice_config": voice_config,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["voice_config"] == voice_config

    @pytest.mark.asyncio
    async def test_create_identity_first_becomes_default(self, client: AsyncClient, db_session):
        """Test that first identity becomes default."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_provider(db_session, provider_id="reddit")
        db_session.commit()

        response = await client.post(
            "/identities",
            json={
                "provider_id": "reddit",
                "external_username": "first_account",
                "display_name": "First Account",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["is_default"] is True

    @pytest.mark.asyncio
    async def test_create_identity_invalid_provider(self, client: AsyncClient, db_session):
        """Test creating identity with invalid provider."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        response = await client.post(
            "/identities",
            json={
                "provider_id": "nonexistent",
                "external_username": "my_account",
                "display_name": "My Account",
            },
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_create_identity_duplicate_username(self, client: AsyncClient, db_session):
        """Test creating identity with duplicate username."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        provider = create_provider(db_session, provider_id="reddit")
        create_identity(db_session, provider=provider, external_username="existing")
        db_session.commit()

        response = await client.post(
            "/identities",
            json={
                "provider_id": "reddit",
                "external_username": "existing",
                "display_name": "New Account",
            },
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_create_identity_writes_audit_log(self, client: AsyncClient, db_session):
        """Test that creating identity writes audit log."""
        from rediska_core.domain.models import AuditLog

        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_provider(db_session, provider_id="reddit")
        db_session.commit()

        await client.post(
            "/identities",
            json={
                "provider_id": "reddit",
                "external_username": "my_account",
                "display_name": "My Account",
            },
        )

        db_session.expire_all()
        audit_entries = db_session.query(AuditLog).filter_by(action_type="identity.create").all()
        assert len(audit_entries) >= 1


class TestIdentityGetEndpoint:
    """Integration tests for GET /identities/{id}."""

    @pytest.mark.asyncio
    async def test_get_identity_requires_auth(self, client: AsyncClient):
        """Test that getting identity requires authentication."""
        response = await client.get("/identities/1")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_identity_success(self, client: AsyncClient, db_session):
        """Test getting an identity by ID."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        identity = create_identity(db_session, display_name="Test Identity")
        db_session.commit()

        response = await client.get(f"/identities/{identity.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == identity.id
        assert data["display_name"] == "Test Identity"

    @pytest.mark.asyncio
    async def test_get_identity_not_found(self, client: AsyncClient, db_session):
        """Test getting nonexistent identity."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        response = await client.get("/identities/99999")

        assert response.status_code == 404


class TestIdentityUpdateEndpoint:
    """Integration tests for PATCH /identities/{id}."""

    @pytest.mark.asyncio
    async def test_update_identity_requires_auth(self, client: AsyncClient):
        """Test that updating identity requires authentication."""
        response = await client.patch(
            "/identities/1",
            json={"display_name": "Updated"},
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_update_identity_display_name(self, client: AsyncClient, db_session):
        """Test updating identity display name."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        identity = create_identity(db_session, display_name="Original")
        db_session.commit()

        response = await client.patch(
            f"/identities/{identity.id}",
            json={"display_name": "Updated"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["display_name"] == "Updated"

    @pytest.mark.asyncio
    async def test_update_identity_voice_config(self, client: AsyncClient, db_session):
        """Test updating identity voice configuration."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        identity = create_identity(db_session)
        db_session.commit()

        new_voice_config = {"tone": "professional"}

        response = await client.patch(
            f"/identities/{identity.id}",
            json={"voice_config": new_voice_config},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["voice_config"] == new_voice_config

    @pytest.mark.asyncio
    async def test_update_identity_not_found(self, client: AsyncClient, db_session):
        """Test updating nonexistent identity."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        response = await client.patch(
            "/identities/99999",
            json={"display_name": "Updated"},
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_identity_writes_audit_log(self, client: AsyncClient, db_session):
        """Test that updating identity writes audit log."""
        from rediska_core.domain.models import AuditLog

        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        identity = create_identity(db_session)
        db_session.commit()

        await client.patch(
            f"/identities/{identity.id}",
            json={"display_name": "Updated"},
        )

        db_session.expire_all()
        audit_entries = db_session.query(AuditLog).filter_by(action_type="identity.update").all()
        assert len(audit_entries) >= 1


class TestIdentityDeleteEndpoint:
    """Integration tests for DELETE /identities/{id}."""

    @pytest.mark.asyncio
    async def test_delete_identity_requires_auth(self, client: AsyncClient):
        """Test that deleting identity requires authentication."""
        response = await client.delete("/identities/1")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_delete_identity_success(self, client: AsyncClient, db_session):
        """Test deleting (deactivating) an identity."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        provider = create_provider(db_session)
        # Create two identities so we can delete the non-default one
        create_identity(db_session, provider=provider, external_username="default", is_default=True)
        identity = create_identity(db_session, provider=provider, external_username="to_delete", is_default=False)
        db_session.commit()

        response = await client.delete(f"/identities/{identity.id}")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_identity_not_found(self, client: AsyncClient, db_session):
        """Test deleting nonexistent identity."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        response = await client.delete("/identities/99999")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_only_default_fails(self, client: AsyncClient, db_session):
        """Test that deleting the only default identity fails."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        identity = create_identity(db_session, is_default=True)
        db_session.commit()

        response = await client.delete(f"/identities/{identity.id}")

        assert response.status_code == 400


class TestIdentitySetDefaultEndpoint:
    """Integration tests for POST /identities/{id}/set-default."""

    @pytest.mark.asyncio
    async def test_set_default_requires_auth(self, client: AsyncClient):
        """Test that setting default requires authentication."""
        response = await client.post("/identities/1/set-default")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_set_default_success(self, client: AsyncClient, db_session):
        """Test setting identity as default."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        provider = create_provider(db_session)
        first = create_identity(db_session, provider=provider, external_username="first", is_default=True)
        second = create_identity(db_session, provider=provider, external_username="second", is_default=False)
        db_session.commit()

        response = await client.post(f"/identities/{second.id}/set-default")

        assert response.status_code == 200
        data = response.json()
        assert data["is_default"] is True

    @pytest.mark.asyncio
    async def test_set_default_not_found(self, client: AsyncClient, db_session):
        """Test setting default for nonexistent identity."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        response = await client.post("/identities/99999/set-default")

        assert response.status_code == 404


class TestSetupStatusEndpoint:
    """Integration tests for GET /setup/status."""

    @pytest.mark.asyncio
    async def test_setup_status_requires_auth(self, client: AsyncClient):
        """Test that setup status requires authentication."""
        response = await client.get("/setup/status")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_setup_status_not_complete(self, client: AsyncClient, db_session):
        """Test setup status when not complete."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        response = await client.get("/setup/status")

        assert response.status_code == 200
        data = response.json()
        assert data["has_identity"] is False
        assert data["is_complete"] is False

    @pytest.mark.asyncio
    async def test_setup_status_complete(self, client: AsyncClient, db_session):
        """Test setup status when complete."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_identity(db_session, is_active=True)
        db_session.commit()

        response = await client.get("/setup/status")

        assert response.status_code == 200
        data = response.json()
        assert data["has_identity"] is True
        assert data["is_complete"] is True


class TestOnboardingGate:
    """Integration tests for onboarding gate middleware."""

    @pytest.mark.asyncio
    async def test_protected_endpoint_without_identity(self, client: AsyncClient, db_session):
        """Test that protected endpoints require identity setup."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        # Try to access conversations without identity
        response = await client.get("/conversations")

        # Should return 403 with onboarding required message
        assert response.status_code == 403
        data = response.json()
        assert "identity" in data["detail"].lower() or "setup" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_protected_endpoint_with_identity(self, client: AsyncClient, db_session):
        """Test that protected endpoints work with identity setup."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        create_identity(db_session, is_active=True)
        db_session.commit()

        # Try to access conversations with identity
        response = await client.get("/conversations")

        # Should not be blocked by onboarding gate
        # (might be 200 or 404 depending on if endpoint exists)
        assert response.status_code != 403

    @pytest.mark.asyncio
    async def test_setup_endpoints_bypass_gate(self, client: AsyncClient, db_session):
        """Test that setup endpoints bypass the onboarding gate."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        # Setup status should work without identity
        response = await client.get("/setup/status")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_identity_endpoints_bypass_gate(self, client: AsyncClient, db_session):
        """Test that identity endpoints bypass the onboarding gate."""
        session = await login_user(client, db_session)
        client.cookies.set("session", session)

        # Identity list should work without identity
        response = await client.get("/identities")

        assert response.status_code == 200
