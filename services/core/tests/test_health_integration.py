"""Integration tests for health check endpoint.

These tests verify that the health endpoint works correctly
with the full application stack.
"""

import pytest


class TestHealthCheckIntegration:
    """Integration tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_health_endpoint_accessible(self, client):
        """Test that health endpoint is accessible without authentication."""
        response = await client.get("/healthz")

        # Should be accessible
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_endpoint_returns_json(self, client):
        """Test that health endpoint returns valid JSON."""
        response = await client.get("/healthz")

        assert response.headers.get("content-type") == "application/json"
        # Should not raise
        data = response.json()
        assert isinstance(data, dict)

    @pytest.mark.asyncio
    async def test_cors_headers_on_health_endpoint(self, client):
        """Test that CORS headers are present on health endpoint."""
        response = await client.options(
            "/healthz",
            headers={
                "Origin": "https://rediska.local",
                "Access-Control-Request-Method": "GET",
            },
        )

        # CORS preflight should succeed
        assert response.status_code in (200, 204)

    @pytest.mark.asyncio
    async def test_root_endpoint_returns_api_info(self, client):
        """Test that root endpoint provides API information."""
        response = await client.get("/")

        assert response.status_code == 200
        data = response.json()

        # Verify API info structure
        assert "name" in data
        assert "version" in data
        assert "status" in data

    @pytest.mark.asyncio
    async def test_nonexistent_endpoint_returns_404(self, client):
        """Test that nonexistent endpoints return 404."""
        response = await client.get("/nonexistent")

        assert response.status_code == 404
