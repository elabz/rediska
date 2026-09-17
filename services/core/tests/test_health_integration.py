"""Integration tests for health check endpoint.

These tests verify that the health endpoint works correctly
with the full application stack.

NOTE: the status/body assertions that used to live here were strict subsets of
test_health_unit.py running against the same hard-coded handler, so they have
been removed. What remains is what the unit tests cannot cover: middleware
behaviour (CORS) and routing (404).
"""

import pytest


class TestHealthCheckIntegration:
    """Integration tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_cors_headers_on_health_endpoint(self, client):
        """CORS preflight must actually return the Access-Control-* headers.

        The old test only checked the status code and never inspected a single
        CORS header, despite its name -- it would have passed with CORSMiddleware
        removed entirely.
        """
        origin = "https://rediska.local"

        response = await client.options(
            "/healthz",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )

        assert response.status_code in (200, 204)
        # allow_credentials=True means the origin must be echoed back exactly,
        # never the "*" wildcard (a wildcard is invalid with credentials).
        assert response.headers.get("access-control-allow-origin") == origin
        assert response.headers.get("access-control-allow-credentials") == "true"
        assert "GET" in response.headers.get("access-control-allow-methods", "")

    @pytest.mark.asyncio
    async def test_cors_rejects_unknown_origin(self, client):
        """An origin outside the allow-list gets no allow-origin header."""
        response = await client.options(
            "/healthz",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

        assert response.headers.get("access-control-allow-origin") is None

    @pytest.mark.asyncio
    async def test_nonexistent_endpoint_returns_404(self, client):
        """Test that nonexistent endpoints return 404."""
        response = await client.get("/nonexistent")

        assert response.status_code == 404
