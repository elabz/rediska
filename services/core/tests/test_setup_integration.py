"""Integration tests for setup/onboarding API routes."""

import pytest
from fastapi.testclient import TestClient

from rediska_core.api.deps import get_current_user
from rediska_core.domain.models import Identity, LocalUser, Provider


@pytest.fixture
def client(test_app):
    """Create an *unauthenticated* test client."""
    return TestClient(test_app)


@pytest.fixture
def auth_client(test_app, db_session):
    """Create a test client whose requests are authenticated.

    `/setup/status` and `/identities` both depend on `CurrentUser`; without
    this override every request stops at a 401 and no setup logic runs.
    """
    user = LocalUser(username="setup_tester", password_hash="not-a-real-hash")
    db_session.add(user)
    db_session.flush()

    test_app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(test_app)
    test_app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def reddit_provider(db_session):
    """Create the reddit provider row that identity creation requires."""
    provider = Provider(provider_id="reddit", display_name="Reddit", enabled=True)
    db_session.add(provider)
    db_session.commit()
    return provider


class TestSetupStatusEndpoint:
    """Tests for GET /setup/status endpoint."""

    def test_setup_status_requires_auth(self, client):
        """Setup status should require authentication."""
        response = client.get("/setup/status")

        assert response.status_code == 401

    def test_setup_status_response_format(self, auth_client):
        """Setup status returns has_identity and is_complete."""
        response = auth_client.get("/setup/status")

        assert response.status_code == 200
        assert response.json() == {"has_identity": False, "is_complete": False}


class TestSetupOnboardingFlow:
    """Tests for onboarding setup flow."""

    def test_fresh_install_has_incomplete_setup(self, auth_client):
        """Fresh install should show incomplete setup status."""
        response = auth_client.get("/setup/status")

        assert response.status_code == 200
        data = response.json()
        assert data["is_complete"] is False
        assert data["has_identity"] is False

    def test_setup_completes_once_an_identity_exists(
        self, auth_client, reddit_provider, db_session
    ):
        """Creating an identity flips the setup status to complete."""
        db_session.add(
            Identity(
                provider_id="reddit",
                external_username="onboarded_user",
                external_user_id="t2_onboarded",
                display_name="Onboarded",
                is_default=True,
                is_active=True,
            )
        )
        db_session.commit()

        response = auth_client.get("/setup/status")

        assert response.status_code == 200
        assert response.json() == {"has_identity": True, "is_complete": True}


class TestSetupMiddleware:
    """Tests for onboarding gate middleware."""

    def test_health_endpoints_bypass_onboarding_gate(self, client):
        """Health endpoints should work without completing setup."""
        # /healthz should be accessible even without setup
        response = client.get("/healthz")
        assert response.status_code == 200

        # /api/health should also be accessible
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_api_health_bypasses_onboarding(self, client):
        """API health endpoint bypasses onboarding middleware."""
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_api_ready_bypasses_onboarding(self, client):
        """API readiness endpoint bypasses onboarding middleware."""
        response = client.get("/api/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is True


class TestSetupIdentityCreation:
    """Tests for identity creation during setup."""

    def test_identity_endpoint_requires_auth(self, client):
        """Identity listing requires authentication."""
        response = client.get("/identities")

        assert response.status_code == 401

    def test_identity_endpoint_lists_when_authenticated(self, auth_client):
        """Identity listing is empty before setup."""
        response = auth_client.get("/identities")

        assert response.status_code == 200
        assert response.json() == {"identities": [], "total": 0}

    def test_can_create_first_identity(
        self, auth_client, reddit_provider, db_session
    ):
        """Should be able to create first identity during setup."""
        response = auth_client.post(
            "/identities",
            json={
                "provider_id": "reddit",
                "external_username": "test_setup_user",
                "display_name": "Test Setup User",
                "voice_config": {
                    "system_prompt": "You are helpful",
                    "tone": "friendly",
                },
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["external_username"] == "test_setup_user"
        assert data["display_name"] == "Test Setup User"
        assert data["voice_config"] == {
            "system_prompt": "You are helpful",
            "tone": "friendly",
        }

        # The identity must actually be persisted, not just echoed back.
        stored = (
            db_session.query(Identity)
            .filter_by(external_username="test_setup_user")
            .one()
        )
        assert stored.id == data["id"]
        assert stored.provider_id == "reddit"
        assert stored.voice_config_json == {
            "system_prompt": "You are helpful",
            "tone": "friendly",
        }

    def test_create_identity_for_unknown_provider_is_rejected(self, auth_client):
        """A provider that is not registered cannot back an identity."""
        response = auth_client.post(
            "/identities",
            json={
                "provider_id": "nosuchprovider",
                "external_username": "test_setup_user",
                "display_name": "Test Setup User",
            },
        )

        # ValueError from the service maps to 400.
        assert response.status_code == 400
        assert "does not exist" in response.json()["detail"]
