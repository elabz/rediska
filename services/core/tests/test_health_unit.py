"""Unit tests for health check endpoint.

These tests verify the basic functionality of the health check endpoint
without requiring external dependencies.
"""

import pytest


class TestHealthCheckUnit:
    """Unit tests for the /healthz endpoint."""

    @pytest.mark.asyncio
    async def test_health_check_returns_ok(self, client):
        """Test that health check returns ok status."""
        response = await client.get("/healthz")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["service"] == "rediska-core"

    @pytest.mark.asyncio
    async def test_health_check_response_format(self, client):
        """Test that health check returns expected JSON structure."""
        response = await client.get("/healthz")

        assert response.status_code == 200
        data = response.json()

        # Verify required fields
        assert "ok" in data
        assert "service" in data

        # Verify types
        assert isinstance(data["ok"], bool)
        assert isinstance(data["service"], str)

    @pytest.mark.asyncio
    async def test_root_endpoint(self, client):
        """Test that root endpoint returns API info."""
        response = await client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Rediska Core API"
        assert "version" in data
        assert data["status"] == "running"
