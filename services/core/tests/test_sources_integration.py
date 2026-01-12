"""Integration tests for Epic 7.1 - Sources API endpoints.

Tests cover:
1. GET /sources/{provider_id}/locations/{location}/posts endpoint
2. Pagination with cursors
3. Sort options
4. Error handling
"""

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from rediska_core.api.deps import get_current_user
from rediska_core.domain.models import LocalUser, Provider


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


@pytest.fixture
def sample_posts():
    """Sample posts data from provider."""
    return [
        {
            "id": "post1",
            "title": "First Post",
            "body": "This is the first post content.",
            "author": "user1",
            "author_id": "t2_user1",
            "url": "https://reddit.com/r/test/comments/post1",
            "created_utc": 1704067200,
            "score": 100,
            "num_comments": 25,
        },
        {
            "id": "post2",
            "title": "Second Post",
            "body": "This is the second post content.",
            "author": "user2",
            "author_id": "t2_user2",
            "url": "https://reddit.com/r/test/comments/post2",
            "created_utc": 1704153600,
            "score": 50,
            "num_comments": 10,
        },
    ]


# =============================================================================
# GET /SOURCES/{PROVIDER}/LOCATIONS/{LOCATION}/POSTS TESTS
# =============================================================================


class TestBrowsePostsEndpoint:
    """Tests for GET /sources/{provider_id}/locations/{location}/posts endpoint."""

    @pytest.mark.asyncio
    async def test_browse_posts_returns_posts(
        self, auth_client, setup_provider, sample_posts
    ):
        """GET /sources/.../posts should return posts."""
        with patch("rediska_core.api.routes.sources.get_provider_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.browse_location.return_value = {
                "posts": sample_posts,
                "after": "cursor_abc",
            }
            mock_get_client.return_value = mock_client

            response = await auth_client.get(
                "/sources/reddit/locations/r%2Ftest/posts"
            )

            assert response.status_code == 200
            data = response.json()
            assert len(data["posts"]) == 2
            assert data["provider_id"] == "reddit"
            assert data["source_location"] == "r/test"

    @pytest.mark.asyncio
    async def test_browse_posts_includes_cursor(
        self, auth_client, setup_provider, sample_posts
    ):
        """Response should include cursor for pagination."""
        with patch("rediska_core.api.routes.sources.get_provider_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.browse_location.return_value = {
                "posts": sample_posts,
                "after": "next_page_cursor",
            }
            mock_get_client.return_value = mock_client

            response = await auth_client.get(
                "/sources/reddit/locations/r%2Ftest/posts"
            )

            assert response.status_code == 200
            assert response.json()["cursor"] == "next_page_cursor"

    @pytest.mark.asyncio
    async def test_browse_posts_with_cursor(
        self, auth_client, setup_provider, sample_posts
    ):
        """Should pass cursor parameter for pagination."""
        with patch("rediska_core.api.routes.sources.get_provider_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.browse_location.return_value = {
                "posts": sample_posts,
                "after": None,
            }
            mock_get_client.return_value = mock_client

            response = await auth_client.get(
                "/sources/reddit/locations/r%2Ftest/posts",
                params={"cursor": "page2_cursor"},
            )

            assert response.status_code == 200
            # Verify cursor was passed to client
            mock_client.browse_location.assert_called_once()
            call_kwargs = mock_client.browse_location.call_args[1]
            assert call_kwargs.get("after") == "page2_cursor"

    @pytest.mark.asyncio
    async def test_browse_posts_with_sort(
        self, auth_client, setup_provider, sample_posts
    ):
        """Should pass sort parameter."""
        with patch("rediska_core.api.routes.sources.get_provider_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.browse_location.return_value = {
                "posts": sample_posts,
                "after": None,
            }
            mock_get_client.return_value = mock_client

            response = await auth_client.get(
                "/sources/reddit/locations/r%2Ftest/posts",
                params={"sort": "new"},
            )

            assert response.status_code == 200
            call_kwargs = mock_client.browse_location.call_args[1]
            assert call_kwargs.get("sort") == "new"

    @pytest.mark.asyncio
    async def test_browse_posts_with_limit(
        self, auth_client, setup_provider, sample_posts
    ):
        """Should pass limit parameter."""
        with patch("rediska_core.api.routes.sources.get_provider_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.browse_location.return_value = {
                "posts": sample_posts[:1],
                "after": None,
            }
            mock_get_client.return_value = mock_client

            response = await auth_client.get(
                "/sources/reddit/locations/r%2Ftest/posts",
                params={"limit": 1},
            )

            assert response.status_code == 200
            call_kwargs = mock_client.browse_location.call_args[1]
            assert call_kwargs.get("limit") == 1


class TestBrowsePostsErrorHandling:
    """Tests for error handling in browse posts endpoint."""

    @pytest.mark.asyncio
    async def test_browse_posts_invalid_provider(self, auth_client):
        """Should return 404 for unknown provider."""
        response = await auth_client.get(
            "/sources/unknown_provider/locations/test/posts"
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_browse_posts_provider_error(
        self, auth_client, setup_provider
    ):
        """Should handle provider API errors gracefully."""
        with patch("rediska_core.api.routes.sources.get_provider_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.browse_location.side_effect = Exception("API Error")
            mock_get_client.return_value = mock_client

            response = await auth_client.get(
                "/sources/reddit/locations/r%2Ftest/posts"
            )

            assert response.status_code == 500
            assert "error" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_browse_posts_requires_authentication(self, test_app):
        """Should require authentication."""
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/sources/reddit/locations/r%2Ftest/posts"
            )

            assert response.status_code in [401, 403]


class TestBrowsePostsNormalization:
    """Tests for post data normalization."""

    @pytest.mark.asyncio
    async def test_posts_include_required_fields(
        self, auth_client, setup_provider, sample_posts
    ):
        """Posts should include all required fields."""
        with patch("rediska_core.api.routes.sources.get_provider_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.browse_location.return_value = {
                "posts": sample_posts,
                "after": None,
            }
            mock_get_client.return_value = mock_client

            response = await auth_client.get(
                "/sources/reddit/locations/r%2Ftest/posts"
            )

            assert response.status_code == 200
            post = response.json()["posts"][0]

            assert "external_post_id" in post
            assert "title" in post
            assert "body_text" in post
            assert "author_username" in post
            assert "post_url" in post
            assert "source_location" in post
            assert "provider_id" in post
