"""Integration tests for Epic 6.3 - Search API endpoint.

Tests cover:
1. POST /search endpoint
2. Request validation
3. Response format
4. Filter parameters
5. Pagination
6. Error responses
"""

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from rediska_core.api.deps import get_current_user
from rediska_core.domain.models import LocalUser


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_user():
    """Create a mock user for authentication."""
    user = MagicMock(spec=LocalUser)
    user.id = 1
    user.username = "test_user"
    return user


@pytest.fixture
async def auth_client(test_app, db_session, mock_user):
    """Create an authenticated client with auth dependency override."""
    # Override the auth dependency
    test_app.dependency_overrides[get_current_user] = lambda: mock_user

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac

    # Clear overrides after test
    test_app.dependency_overrides.pop(get_current_user, None)


# =============================================================================
# POST /SEARCH TESTS
# =============================================================================


class TestSearchEndpoint:
    """Tests for POST /search endpoint."""

    @pytest.mark.asyncio
    async def test_search_endpoint_returns_results(self, auth_client):
        """POST /search should return search results."""
        with patch("rediska_core.api.routes.search.SearchService") as mock_service:
            mock_instance = MagicMock()
            mock_instance.hybrid_search.return_value = {
                "total": 2,
                "hits": [
                    {"id": "message:1", "score": 0.95, "source": {"content": "Hello", "doc_type": "message"}},
                    {"id": "message:2", "score": 0.85, "source": {"content": "World", "doc_type": "message"}},
                ],
                "max_score": 0.95,
            }
            mock_service.return_value = mock_instance

            response = await auth_client.post("/search", json={"query": "hello"})

            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 2
            assert len(data["hits"]) == 2

    @pytest.mark.asyncio
    async def test_search_requires_query(self, auth_client):
        """POST /search should require query parameter."""
        response = await auth_client.post("/search", json={})

        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_search_with_empty_query_returns_empty(self, auth_client):
        """POST /search with empty query should return empty results."""
        with patch("rediska_core.api.routes.search.SearchService") as mock_service:
            mock_instance = MagicMock()
            mock_instance.hybrid_search.return_value = {
                "total": 0,
                "hits": [],
                "max_score": None,
            }
            mock_service.return_value = mock_instance

            response = await auth_client.post("/search", json={"query": ""})

            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 0


class TestSearchFilters:
    """Tests for search filter parameters."""

    @pytest.mark.asyncio
    async def test_search_with_provider_filter(self, auth_client):
        """POST /search should accept provider_id filter."""
        with patch("rediska_core.api.routes.search.SearchService") as mock_service:
            mock_instance = MagicMock()
            mock_instance.hybrid_search.return_value = {"total": 0, "hits": [], "max_score": None}
            mock_service.return_value = mock_instance

            response = await auth_client.post("/search", json={
                "query": "test",
                "provider_id": "reddit",
            })

            assert response.status_code == 200
            mock_instance.hybrid_search.assert_called_once()
            call_kwargs = mock_instance.hybrid_search.call_args[1]
            assert call_kwargs.get("provider_id") == "reddit"

    @pytest.mark.asyncio
    async def test_search_with_identity_filter(self, auth_client):
        """POST /search should accept identity_id filter."""
        with patch("rediska_core.api.routes.search.SearchService") as mock_service:
            mock_instance = MagicMock()
            mock_instance.hybrid_search.return_value = {"total": 0, "hits": [], "max_score": None}
            mock_service.return_value = mock_instance

            response = await auth_client.post("/search", json={
                "query": "test",
                "identity_id": 42,
            })

            assert response.status_code == 200
            call_kwargs = mock_instance.hybrid_search.call_args[1]
            assert call_kwargs.get("identity_id") == 42

    @pytest.mark.asyncio
    async def test_search_with_doc_types_filter(self, auth_client):
        """POST /search should accept doc_types filter."""
        with patch("rediska_core.api.routes.search.SearchService") as mock_service:
            mock_instance = MagicMock()
            mock_instance.hybrid_search.return_value = {"total": 0, "hits": [], "max_score": None}
            mock_service.return_value = mock_instance

            response = await auth_client.post("/search", json={
                "query": "test",
                "doc_types": ["message", "lead_post"],
            })

            assert response.status_code == 200
            call_kwargs = mock_instance.hybrid_search.call_args[1]
            assert call_kwargs.get("doc_types") == ["message", "lead_post"]


class TestSearchPagination:
    """Tests for search pagination parameters."""

    @pytest.mark.asyncio
    async def test_search_with_pagination(self, auth_client):
        """POST /search should accept offset and limit."""
        with patch("rediska_core.api.routes.search.SearchService") as mock_service:
            mock_instance = MagicMock()
            mock_instance.hybrid_search.return_value = {"total": 100, "hits": [], "max_score": None}
            mock_service.return_value = mock_instance

            response = await auth_client.post("/search", json={
                "query": "test",
                "offset": 20,
                "limit": 10,
            })

            assert response.status_code == 200
            call_kwargs = mock_instance.hybrid_search.call_args[1]
            assert call_kwargs.get("offset") == 20
            assert call_kwargs.get("limit") == 10

    @pytest.mark.asyncio
    async def test_search_limit_is_capped(self, auth_client):
        """POST /search should cap limit to maximum."""
        with patch("rediska_core.api.routes.search.SearchService") as mock_service:
            mock_instance = MagicMock()
            mock_instance.hybrid_search.return_value = {"total": 0, "hits": [], "max_score": None}
            mock_service.return_value = mock_instance

            response = await auth_client.post("/search", json={
                "query": "test",
                "limit": 1000,  # Over max
            })

            # Should be rejected by validation (max is 100)
            assert response.status_code == 422


class TestSearchModes:
    """Tests for search mode selection."""

    @pytest.mark.asyncio
    async def test_search_mode_hybrid_is_default(self, auth_client):
        """POST /search should use hybrid search by default."""
        with patch("rediska_core.api.routes.search.SearchService") as mock_service:
            mock_instance = MagicMock()
            mock_instance.hybrid_search.return_value = {"total": 0, "hits": [], "max_score": None}
            mock_service.return_value = mock_instance

            response = await auth_client.post("/search", json={"query": "test"})

            assert response.status_code == 200
            mock_instance.hybrid_search.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_mode_text_only(self, auth_client):
        """POST /search should support text-only mode."""
        with patch("rediska_core.api.routes.search.SearchService") as mock_service:
            mock_instance = MagicMock()
            mock_instance.text_search.return_value = {"total": 0, "hits": [], "max_score": None}
            mock_service.return_value = mock_instance

            response = await auth_client.post("/search", json={
                "query": "test",
                "mode": "text",
            })

            assert response.status_code == 200
            mock_instance.text_search.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_mode_vector_only(self, auth_client):
        """POST /search should support vector-only mode."""
        with patch("rediska_core.api.routes.search.SearchService") as mock_service:
            mock_instance = MagicMock()
            mock_instance.vector_search.return_value = {"total": 0, "hits": [], "max_score": None}
            mock_service.return_value = mock_instance

            response = await auth_client.post("/search", json={
                "query": "test",
                "mode": "vector",
            })

            assert response.status_code == 200
            mock_instance.vector_search.assert_called_once()


class TestSearchResponseFormat:
    """Tests for search response format."""

    @pytest.mark.asyncio
    async def test_response_includes_total(self, auth_client):
        """Response should include total count."""
        with patch("rediska_core.api.routes.search.SearchService") as mock_service:
            mock_instance = MagicMock()
            mock_instance.hybrid_search.return_value = {
                "total": 42,
                "hits": [],
                "max_score": None,
            }
            mock_service.return_value = mock_instance

            response = await auth_client.post("/search", json={"query": "test"})

            assert response.status_code == 200
            assert response.json()["total"] == 42

    @pytest.mark.asyncio
    async def test_response_includes_hits(self, auth_client):
        """Response should include hits array."""
        with patch("rediska_core.api.routes.search.SearchService") as mock_service:
            mock_instance = MagicMock()
            mock_instance.hybrid_search.return_value = {
                "total": 1,
                "hits": [{"id": "message:1", "score": 1.0, "source": {}}],
                "max_score": 1.0,
            }
            mock_service.return_value = mock_instance

            response = await auth_client.post("/search", json={"query": "test"})

            assert response.status_code == 200
            assert "hits" in response.json()
            assert len(response.json()["hits"]) == 1

    @pytest.mark.asyncio
    async def test_response_hit_includes_required_fields(self, auth_client):
        """Each hit should include id, score, and source."""
        with patch("rediska_core.api.routes.search.SearchService") as mock_service:
            mock_instance = MagicMock()
            mock_instance.hybrid_search.return_value = {
                "total": 1,
                "hits": [{
                    "id": "message:123",
                    "score": 0.95,
                    "source": {
                        "doc_type": "message",
                        "entity_id": 123,
                        "content": "Test content",
                    },
                }],
                "max_score": 0.95,
            }
            mock_service.return_value = mock_instance

            response = await auth_client.post("/search", json={"query": "test"})

            assert response.status_code == 200
            hit = response.json()["hits"][0]
            assert "id" in hit
            assert "score" in hit
            assert "source" in hit


class TestSearchErrorHandling:
    """Tests for search error handling."""

    @pytest.mark.asyncio
    async def test_search_handles_service_error(self, auth_client):
        """POST /search should handle service errors gracefully."""
        with patch("rediska_core.api.routes.search.SearchService") as mock_service:
            mock_instance = MagicMock()
            mock_instance.hybrid_search.side_effect = Exception("ES error")
            mock_service.return_value = mock_instance

            response = await auth_client.post("/search", json={"query": "test"})

            assert response.status_code == 500
            assert "error" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_search_requires_authentication(self, client):
        """POST /search should require authentication."""
        response = await client.post("/search", json={"query": "test"})

        # Should be unauthorized without session
        assert response.status_code in [401, 403]
