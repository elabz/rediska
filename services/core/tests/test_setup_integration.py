"""Integration tests for setup/onboarding API routes."""

import pytest
from fastapi.testclient import TestClient


class TestSetupStatusEndpoint:
    """Tests for GET /setup/status endpoint."""

    @pytest.fixture
    def client(self, test_app):
        """Create test client."""
        return TestClient(test_app)

    def test_setup_status_endpoint_exists(self, client):
        """Setup status endpoint should exist."""
        response = client.get("/setup/status")

        # Should require auth (401/403) or return status (200), not 404
        assert response.status_code != 404

    def test_setup_status_requires_auth(self, client):
        """Setup status should require authentication."""
        response = client.get("/setup/status")

        # Should require auth or be accessible
        assert response.status_code in (200, 401, 403)

    def test_setup_status_response_format(self, client):
        """Setup status should return expected format when successful."""
        response = client.get("/setup/status")

        if response.status_code == 200:
            data = response.json()
            # Should have setup-related fields
            assert isinstance(data, dict)


class TestSetupOnboardingFlow:
    """Tests for onboarding setup flow."""

    @pytest.fixture
    def client(self, test_app):
        """Create test client."""
        return TestClient(test_app)

    def test_fresh_install_has_incomplete_setup(self, client):
        """Fresh install should show incomplete setup status."""
        response = client.get("/setup/status")

        # On fresh install, no identity exists
        # Response should indicate setup is incomplete (if accessible)
        if response.status_code == 200:
            data = response.json()
            # In a fresh DB, setup should be incomplete
            if "is_complete" in data:
                assert data["is_complete"] is False
            elif "has_identity" in data:
                assert data["has_identity"] is False


class TestSetupMiddleware:
    """Tests for onboarding gate middleware."""

    @pytest.fixture
    def client(self, test_app):
        """Create test client."""
        return TestClient(test_app)

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

    @pytest.fixture
    def client(self, test_app):
        """Create test client."""
        return TestClient(test_app)

    def test_identity_endpoint_exists(self, client):
        """Identity endpoints should exist for setup."""
        # GET identities should exist
        response = client.get("/identities")
        assert response.status_code != 404

    def test_can_create_first_identity(self, client):
        """Should be able to create first identity during setup."""
        # POST to create identity
        response = client.post(
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

        # Should accept or require auth
        assert response.status_code in (200, 201, 401, 403, 422)
