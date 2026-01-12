"""Integration tests for Epic 7.3 - Directory API endpoints.

Tests cover:
1. GET /directories/analyzed - List analyzed accounts
2. GET /directories/contacted - List contacted accounts
3. GET /directories/engaged - List engaged accounts
4. GET /directories/counts - Get counts for all directories
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from rediska_core.api.deps import get_current_user
from rediska_core.domain.models import ExternalAccount, LocalUser, Provider


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
    test_app.dependency_overrides[get_current_user] = lambda: mock_user

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac

    test_app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def setup_provider(db_session):
    """Set up provider for tests."""
    provider = Provider(provider_id="reddit", display_name="Reddit")
    db_session.add(provider)
    db_session.flush()
    return provider


@pytest.fixture
def setup_accounts(db_session, setup_provider):
    """Set up external accounts with various states."""
    accounts = []

    # Account 1: analyzed only
    account1 = ExternalAccount(
        provider_id="reddit",
        external_username="user_analyzed",
        external_user_id="t2_analyzed",
        analysis_state="analyzed",
        contact_state="not_contacted",
        engagement_state="not_engaged",
        first_analyzed_at=datetime(2024, 1, 15),
    )
    db_session.add(account1)
    accounts.append(account1)

    # Account 2: analyzed and contacted
    account2 = ExternalAccount(
        provider_id="reddit",
        external_username="user_contacted",
        external_user_id="t2_contacted",
        analysis_state="analyzed",
        contact_state="contacted",
        engagement_state="not_engaged",
        first_analyzed_at=datetime(2024, 1, 10),
        first_contacted_at=datetime(2024, 1, 20),
    )
    db_session.add(account2)
    accounts.append(account2)

    # Account 3: analyzed, contacted, and engaged
    account3 = ExternalAccount(
        provider_id="reddit",
        external_username="user_engaged",
        external_user_id="t2_engaged",
        analysis_state="analyzed",
        contact_state="contacted",
        engagement_state="engaged",
        first_analyzed_at=datetime(2024, 1, 5),
        first_contacted_at=datetime(2024, 1, 12),
        first_inbound_after_contact_at=datetime(2024, 1, 25),
    )
    db_session.add(account3)
    accounts.append(account3)

    # Account 4: not analyzed
    account4 = ExternalAccount(
        provider_id="reddit",
        external_username="user_not_analyzed",
        external_user_id="t2_not_analyzed",
        analysis_state="not_analyzed",
        contact_state="not_contacted",
        engagement_state="not_engaged",
    )
    db_session.add(account4)
    accounts.append(account4)

    db_session.commit()
    return accounts


# =============================================================================
# GET /DIRECTORIES/ANALYZED TESTS
# =============================================================================


class TestAnalyzedDirectoryEndpoint:
    """Tests for GET /directories/analyzed endpoint."""

    @pytest.mark.asyncio
    async def test_list_analyzed_returns_analyzed_accounts(
        self, auth_client, setup_accounts
    ):
        """GET /directories/analyzed should return analyzed accounts."""
        response = await auth_client.get("/directories/analyzed")

        assert response.status_code == 200
        data = response.json()
        assert data["directory_type"] == "analyzed"
        assert len(data["entries"]) == 3
        assert data["total"] == 3

    @pytest.mark.asyncio
    async def test_list_analyzed_with_pagination(
        self, auth_client, setup_accounts
    ):
        """GET /directories/analyzed should support pagination."""
        response = await auth_client.get(
            "/directories/analyzed", params={"limit": 2, "offset": 0}
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["entries"]) == 2
        assert data["total"] == 3

    @pytest.mark.asyncio
    async def test_list_analyzed_with_provider_filter(
        self, auth_client, setup_accounts
    ):
        """GET /directories/analyzed should filter by provider."""
        response = await auth_client.get(
            "/directories/analyzed", params={"provider_id": "reddit"}
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["entries"]) == 3

        response2 = await auth_client.get(
            "/directories/analyzed", params={"provider_id": "twitter"}
        )
        assert response2.status_code == 200
        assert len(response2.json()["entries"]) == 0

    @pytest.mark.asyncio
    async def test_list_analyzed_requires_authentication(self, test_app):
        """GET /directories/analyzed should require authentication."""
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
        ) as client:
            response = await client.get("/directories/analyzed")

            assert response.status_code in [401, 403]


# =============================================================================
# GET /DIRECTORIES/CONTACTED TESTS
# =============================================================================


class TestContactedDirectoryEndpoint:
    """Tests for GET /directories/contacted endpoint."""

    @pytest.mark.asyncio
    async def test_list_contacted_returns_contacted_accounts(
        self, auth_client, setup_accounts
    ):
        """GET /directories/contacted should return contacted accounts."""
        response = await auth_client.get("/directories/contacted")

        assert response.status_code == 200
        data = response.json()
        assert data["directory_type"] == "contacted"
        assert len(data["entries"]) == 2
        assert data["total"] == 2

    @pytest.mark.asyncio
    async def test_list_contacted_excludes_not_contacted(
        self, auth_client, setup_accounts
    ):
        """GET /directories/contacted should exclude not contacted accounts."""
        response = await auth_client.get("/directories/contacted")

        assert response.status_code == 200
        data = response.json()
        usernames = [e["external_username"] for e in data["entries"]]
        assert "user_analyzed" not in usernames
        assert "user_not_analyzed" not in usernames


# =============================================================================
# GET /DIRECTORIES/ENGAGED TESTS
# =============================================================================


class TestEngagedDirectoryEndpoint:
    """Tests for GET /directories/engaged endpoint."""

    @pytest.mark.asyncio
    async def test_list_engaged_returns_engaged_accounts(
        self, auth_client, setup_accounts
    ):
        """GET /directories/engaged should return engaged accounts."""
        response = await auth_client.get("/directories/engaged")

        assert response.status_code == 200
        data = response.json()
        assert data["directory_type"] == "engaged"
        assert len(data["entries"]) == 1
        assert data["entries"][0]["external_username"] == "user_engaged"

    @pytest.mark.asyncio
    async def test_list_engaged_empty_when_none(
        self, auth_client, setup_provider
    ):
        """GET /directories/engaged should return empty when no engaged accounts."""
        # No accounts created, so no engaged
        response = await auth_client.get("/directories/engaged")

        assert response.status_code == 200
        data = response.json()
        assert len(data["entries"]) == 0


# =============================================================================
# GET /DIRECTORIES/COUNTS TESTS
# =============================================================================


class TestDirectoryCountsEndpoint:
    """Tests for GET /directories/counts endpoint."""

    @pytest.mark.asyncio
    async def test_counts_returns_all_counts(
        self, auth_client, setup_accounts
    ):
        """GET /directories/counts should return counts for all directories."""
        response = await auth_client.get("/directories/counts")

        assert response.status_code == 200
        data = response.json()
        assert data["analyzed"] == 3
        assert data["contacted"] == 2
        assert data["engaged"] == 1

    @pytest.mark.asyncio
    async def test_counts_with_provider_filter(
        self, auth_client, setup_accounts
    ):
        """GET /directories/counts should filter by provider."""
        response = await auth_client.get(
            "/directories/counts", params={"provider_id": "reddit"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["analyzed"] == 3

        response2 = await auth_client.get(
            "/directories/counts", params={"provider_id": "twitter"}
        )
        assert response2.json()["analyzed"] == 0

    @pytest.mark.asyncio
    async def test_counts_requires_authentication(self, test_app):
        """GET /directories/counts should require authentication."""
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
        ) as client:
            response = await client.get("/directories/counts")

            assert response.status_code in [401, 403]


# =============================================================================
# RESPONSE FORMAT TESTS
# =============================================================================


class TestDirectoryResponseFormat:
    """Tests for directory response format."""

    @pytest.mark.asyncio
    async def test_entry_includes_required_fields(
        self, auth_client, setup_accounts
    ):
        """Directory entries should include all required fields."""
        response = await auth_client.get("/directories/analyzed")

        assert response.status_code == 200
        entry = response.json()["entries"][0]

        assert "id" in entry
        assert "provider_id" in entry
        assert "external_username" in entry
        assert "analysis_state" in entry
        assert "contact_state" in entry
        assert "engagement_state" in entry
        assert "created_at" in entry

    @pytest.mark.asyncio
    async def test_entry_includes_timestamps(
        self, auth_client, setup_accounts
    ):
        """Directory entries should include workflow timestamps."""
        response = await auth_client.get("/directories/engaged")

        assert response.status_code == 200
        entry = response.json()["entries"][0]

        assert entry["first_analyzed_at"] is not None
        assert entry["first_contacted_at"] is not None
        assert entry["first_inbound_after_contact_at"] is not None
