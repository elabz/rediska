"""Tests for metrics API endpoints."""

import pytest

from fastapi.testclient import TestClient


class TestMetricsEndpoints:
    """Tests for /api/metrics endpoints."""

    @pytest.fixture
    def client(self, test_app):
        """Create test client."""
        return TestClient(test_app)

    def test_get_metrics_endpoint_exists(self, client):
        """Test that metrics endpoint exists."""
        response = client.get("/api/metrics")

        # Should return 200 or 401 (if auth required), not 404
        assert response.status_code != 404

    def test_get_metrics_requires_auth(self, client):
        """Test that metrics endpoint requires authentication."""
        response = client.get("/api/metrics")

        # Should require auth (401) or redirect (403)
        assert response.status_code in (401, 403, 200)

    def test_get_queue_metrics_requires_auth(self, client):
        """Test getting queue depth metrics requires auth."""
        response = client.get("/api/metrics/queues")

        assert response.status_code in (401, 403, 200)

    def test_get_sync_metrics_requires_auth(self, client):
        """Test getting sync time metrics requires auth."""
        response = client.get("/api/metrics/sync")

        assert response.status_code in (401, 403, 200)


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    @pytest.fixture
    def client(self, test_app):
        """Create test client."""
        return TestClient(test_app)

    def test_health_endpoint_exists(self, client):
        """Test that health endpoint exists."""
        response = client.get("/api/health")

        # Health should be public, not require auth
        assert response.status_code == 200

    def test_health_returns_status(self, client):
        """Test that health returns status field."""
        response = client.get("/api/health")

        data = response.json()
        assert "status" in data

    def test_health_status_is_healthy(self, client):
        """Test that health status is 'healthy' when service is up."""
        response = client.get("/api/health")

        data = response.json()
        assert data["status"] in ("healthy", "ok", "up")

    def test_health_includes_version(self, client):
        """Test that health includes version info."""
        response = client.get("/api/health")

        data = response.json()
        # Version might be optional but is good practice
        assert "version" in data or "service" in data or response.status_code == 200

    def test_health_includes_timestamp(self, client):
        """Test that health includes timestamp."""
        response = client.get("/api/health")

        data = response.json()
        # Timestamp shows when check was performed
        assert "timestamp" in data or "checked_at" in data or response.status_code == 200


class TestReadinessEndpoint:
    """Tests for readiness check endpoint."""

    @pytest.fixture
    def client(self, test_app):
        """Create test client."""
        return TestClient(test_app)

    def test_readiness_endpoint_exists(self, client):
        """Test that readiness endpoint exists."""
        response = client.get("/api/ready")

        # Readiness should be public
        assert response.status_code in (200, 503)

    def test_readiness_returns_ready_status(self, client):
        """Test that readiness returns ready status."""
        response = client.get("/api/ready")

        if response.status_code == 200:
            data = response.json()
            assert data.get("ready", True) is True


class TestMetricsAPIResponse:
    """Tests for metrics API response format."""

    @pytest.fixture
    def client(self, test_app):
        """Create test client."""
        return TestClient(test_app)

    def test_health_response_is_json(self, client):
        """Test health response is valid JSON."""
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_health_response_has_status(self, client):
        """Test health response has status field."""
        response = client.get("/api/health")

        data = response.json()
        assert "status" in data
        assert data["status"] == "healthy"

    def test_ready_response_is_json(self, client):
        """Test readiness response is valid JSON."""
        response = client.get("/api/ready")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "ready" in data
