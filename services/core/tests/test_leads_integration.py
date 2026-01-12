"""Integration tests for Epic 7.1 - Leads API endpoints.

Tests cover:
1. POST /leads/save endpoint
2. GET /leads endpoint
3. GET /leads/{id} endpoint
4. PATCH /leads/{id}/status endpoint
"""

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from rediska_core.api.deps import get_current_user
from rediska_core.domain.models import LeadPost, LocalUser, Provider


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


@pytest.fixture
def setup_provider(db_session):
    """Set up provider for tests."""
    provider = Provider(
        provider_id="reddit",
        display_name="Reddit",
        enabled=True,
    )
    db_session.add(provider)
    db_session.commit()
    return provider


# =============================================================================
# POST /LEADS/SAVE TESTS
# =============================================================================


class TestSaveLeadEndpoint:
    """Tests for POST /leads/save endpoint."""

    @pytest.mark.asyncio
    async def test_save_lead_creates_lead(self, auth_client, setup_provider):
        """POST /leads/save should create a new lead."""
        response = await auth_client.post(
            "/leads/save",
            json={
                "provider_id": "reddit",
                "source_location": "r/programming",
                "external_post_id": "test123",
                "post_url": "https://reddit.com/r/programming/comments/test123",
                "title": "Test Post",
                "body_text": "This is a test post",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] is not None
        assert data["status"] == "saved"
        assert data["source_location"] == "r/programming"

    @pytest.mark.asyncio
    async def test_save_lead_requires_provider_id(self, auth_client, setup_provider):
        """POST /leads/save should require provider_id."""
        response = await auth_client.post(
            "/leads/save",
            json={
                "source_location": "r/programming",
                "external_post_id": "test123",
                "post_url": "https://reddit.com/r/programming/comments/test123",
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_save_lead_requires_external_post_id(self, auth_client, setup_provider):
        """POST /leads/save should require external_post_id."""
        response = await auth_client.post(
            "/leads/save",
            json={
                "provider_id": "reddit",
                "source_location": "r/programming",
                "post_url": "https://reddit.com/r/programming/comments/test123",
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_save_lead_upserts_existing(self, auth_client, setup_provider):
        """POST /leads/save should update existing lead."""
        # First save
        response1 = await auth_client.post(
            "/leads/save",
            json={
                "provider_id": "reddit",
                "source_location": "r/programming",
                "external_post_id": "upsert_test",
                "post_url": "https://reddit.com/r/programming/comments/upsert_test",
                "title": "Original Title",
            },
        )
        assert response1.status_code == 200
        lead_id = response1.json()["id"]

        # Second save with updated title
        response2 = await auth_client.post(
            "/leads/save",
            json={
                "provider_id": "reddit",
                "source_location": "r/programming",
                "external_post_id": "upsert_test",
                "post_url": "https://reddit.com/r/programming/comments/upsert_test",
                "title": "Updated Title",
            },
        )

        assert response2.status_code == 200
        assert response2.json()["id"] == lead_id
        assert response2.json()["title"] == "Updated Title"


# =============================================================================
# GET /LEADS TESTS
# =============================================================================


class TestListLeadsEndpoint:
    """Tests for GET /leads endpoint."""

    @pytest.mark.asyncio
    async def test_list_leads_returns_all(self, auth_client, setup_provider):
        """GET /leads should return all leads."""
        # Create some leads
        for i in range(3):
            await auth_client.post(
                "/leads/save",
                json={
                    "provider_id": "reddit",
                    "source_location": "r/test",
                    "external_post_id": f"list_test_{i}",
                    "post_url": f"https://reddit.com/r/test/comments/list_test_{i}",
                },
            )

        response = await auth_client.get("/leads")

        assert response.status_code == 200
        data = response.json()
        assert len(data["leads"]) >= 3

    @pytest.mark.asyncio
    async def test_list_leads_filters_by_status(self, auth_client, setup_provider):
        """GET /leads should filter by status."""
        # Create a saved lead
        await auth_client.post(
            "/leads/save",
            json={
                "provider_id": "reddit",
                "source_location": "r/test",
                "external_post_id": "status_filter_test",
                "post_url": "https://reddit.com/r/test/comments/status_filter_test",
            },
        )

        response = await auth_client.get("/leads", params={"status": "saved"})

        assert response.status_code == 200
        data = response.json()
        for lead in data["leads"]:
            assert lead["status"] == "saved"

    @pytest.mark.asyncio
    async def test_list_leads_pagination(self, auth_client, setup_provider):
        """GET /leads should support pagination."""
        # Create leads
        for i in range(5):
            await auth_client.post(
                "/leads/save",
                json={
                    "provider_id": "reddit",
                    "source_location": "r/test",
                    "external_post_id": f"page_test_{i}",
                    "post_url": f"https://reddit.com/r/test/comments/page_test_{i}",
                },
            )

        response = await auth_client.get("/leads", params={"limit": 2, "offset": 0})

        assert response.status_code == 200
        data = response.json()
        assert len(data["leads"]) == 2


# =============================================================================
# GET /LEADS/{ID} TESTS
# =============================================================================


class TestGetLeadEndpoint:
    """Tests for GET /leads/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_lead_by_id(self, auth_client, setup_provider):
        """GET /leads/{id} should return the lead."""
        # Create a lead
        create_response = await auth_client.post(
            "/leads/save",
            json={
                "provider_id": "reddit",
                "source_location": "r/test",
                "external_post_id": "get_test",
                "post_url": "https://reddit.com/r/test/comments/get_test",
                "title": "Get Test",
            },
        )
        lead_id = create_response.json()["id"]

        response = await auth_client.get(f"/leads/{lead_id}")

        assert response.status_code == 200
        assert response.json()["id"] == lead_id
        assert response.json()["title"] == "Get Test"

    @pytest.mark.asyncio
    async def test_get_lead_not_found(self, auth_client, setup_provider):
        """GET /leads/{id} should return 404 for non-existent lead."""
        response = await auth_client.get("/leads/99999")

        assert response.status_code == 404


# =============================================================================
# PATCH /LEADS/{ID}/STATUS TESTS
# =============================================================================


class TestUpdateLeadStatusEndpoint:
    """Tests for PATCH /leads/{id}/status endpoint."""

    @pytest.mark.asyncio
    async def test_update_status(self, auth_client, setup_provider):
        """PATCH /leads/{id}/status should update the status."""
        # Create a lead
        create_response = await auth_client.post(
            "/leads/save",
            json={
                "provider_id": "reddit",
                "source_location": "r/test",
                "external_post_id": "status_test",
                "post_url": "https://reddit.com/r/test/comments/status_test",
            },
        )
        lead_id = create_response.json()["id"]

        response = await auth_client.patch(
            f"/leads/{lead_id}/status",
            json={"status": "ignored"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    @pytest.mark.asyncio
    async def test_update_status_invalid(self, auth_client, setup_provider):
        """PATCH /leads/{id}/status should reject invalid status."""
        # Create a lead
        create_response = await auth_client.post(
            "/leads/save",
            json={
                "provider_id": "reddit",
                "source_location": "r/test",
                "external_post_id": "invalid_status_test",
                "post_url": "https://reddit.com/r/test/comments/invalid_status_test",
            },
        )
        lead_id = create_response.json()["id"]

        response = await auth_client.patch(
            f"/leads/{lead_id}/status",
            json={"status": "invalid_status"},
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_update_status_not_found(self, auth_client, setup_provider):
        """PATCH /leads/{id}/status should return 404 for non-existent lead."""
        response = await auth_client.patch(
            "/leads/99999/status",
            json={"status": "ignored"},
        )

        assert response.status_code == 404


# =============================================================================
# POST /LEADS/{ID}/ANALYZE TESTS
# =============================================================================


class TestAnalyzeLeadEndpoint:
    """Tests for POST /leads/{id}/analyze endpoint."""

    @pytest.mark.asyncio
    async def test_analyze_lead_success(self, auth_client, setup_provider):
        """POST /leads/{id}/analyze should analyze a lead."""
        from datetime import datetime, timezone
        from unittest.mock import AsyncMock, MagicMock, patch

        from rediska_core.providers.base import (
            PaginatedResult,
            ProfileItemType,
            ProviderProfile,
            ProviderProfileItem,
        )

        # Create a lead with author
        create_response = await auth_client.post(
            "/leads/save",
            json={
                "provider_id": "reddit",
                "source_location": "r/test",
                "external_post_id": "analyze_test",
                "post_url": "https://reddit.com/r/test/comments/analyze_test",
                "title": "Test Post",
                "author_username": "test_author",
                "author_external_id": "t2_author123",
            },
        )
        assert create_response.status_code == 200
        lead_id = create_response.json()["id"]

        # Mock the provider adapter
        mock_adapter = AsyncMock()
        mock_adapter.provider_id = "reddit"
        mock_adapter.fetch_profile.return_value = ProviderProfile(
            external_id="t2_author123",
            username="test_author",
            display_name="Test Author",
            karma=100,
        )
        mock_adapter.fetch_profile_items.return_value = PaginatedResult(
            items=[
                ProviderProfileItem(
                    external_id="t3_post1",
                    item_type=ProfileItemType.POST,
                    author_id="t2_author123",
                    body_text="Sample post content",
                )
            ],
            next_cursor=None,
            has_more=False,
        )

        # Mock indexing and embedding services
        mock_indexing = MagicMock()
        mock_indexing.upsert_content.return_value = True
        mock_embedding = MagicMock()
        mock_embedding.generate_embedding.return_value = {"success": True}

        with patch(
            "rediska_core.api.routes.leads.get_provider_adapter"
        ) as mock_get_adapter, patch(
            "rediska_core.api.routes.leads.get_indexing_service"
        ) as mock_get_indexing, patch(
            "rediska_core.api.routes.leads.get_embedding_service"
        ) as mock_get_embedding:
            mock_get_adapter.return_value = mock_adapter
            mock_get_indexing.return_value = mock_indexing
            mock_get_embedding.return_value = mock_embedding

            response = await auth_client.post(f"/leads/{lead_id}/analyze")

            assert response.status_code == 200
            data = response.json()
            assert data["lead_id"] == lead_id
            assert data["success"] is True
            assert data["profile_items_count"] >= 1

    @pytest.mark.asyncio
    async def test_analyze_lead_not_found(self, auth_client, setup_provider):
        """POST /leads/{id}/analyze should return 404 for non-existent lead."""
        response = await auth_client.post("/leads/99999/analyze")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_analyze_lead_no_author(self, auth_client, setup_provider):
        """POST /leads/{id}/analyze should return 400 for lead without author."""
        # Create a lead without author
        create_response = await auth_client.post(
            "/leads/save",
            json={
                "provider_id": "reddit",
                "source_location": "r/test",
                "external_post_id": "no_author_test",
                "post_url": "https://reddit.com/r/test/comments/no_author_test",
            },
        )
        assert create_response.status_code == 200
        lead_id = create_response.json()["id"]

        response = await auth_client.post(f"/leads/{lead_id}/analyze")

        assert response.status_code == 400
        assert "no author" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_analyze_lead_requires_authentication(self, test_app):
        """POST /leads/{id}/analyze should require authentication."""
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
        ) as client:
            response = await client.post("/leads/1/analyze")

            assert response.status_code in [401, 403]
