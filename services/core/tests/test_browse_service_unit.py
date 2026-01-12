"""Unit tests for Epic 7.1 - Browse service.

Tests cover:
1. Browsing posts from provider locations
2. Pagination with cursors
3. Post data normalization
4. Error handling
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from rediska_core.domain.models import Provider


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def setup_provider(db_session):
    """Set up provider for tests."""
    provider = Provider(
        provider_id="reddit",
        display_name="Reddit",
        enabled=True,
    )
    db_session.add(provider)
    db_session.flush()
    return provider


@pytest.fixture
def mock_provider_client():
    """Create a mock provider client."""
    client = MagicMock()
    return client


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
            "created_utc": 1704067200,  # 2024-01-01 00:00:00 UTC
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
            "created_utc": 1704153600,  # 2024-01-02 00:00:00 UTC
            "score": 50,
            "num_comments": 10,
        },
    ]


# =============================================================================
# BROWSE LOCATION TESTS
# =============================================================================


class TestBrowseLocation:
    """Tests for browsing posts from a location."""

    def test_browse_location_returns_posts(
        self, db_session, setup_provider, mock_provider_client, sample_posts
    ):
        """Should return posts from the location."""
        from rediska_core.domain.services.browse import BrowseService

        mock_provider_client.browse_location.return_value = {
            "posts": sample_posts,
            "after": "cursor_abc",
        }

        service = BrowseService(
            db=db_session,
            provider_client=mock_provider_client,
        )

        result = service.browse_location("reddit", "r/test")

        assert len(result["posts"]) == 2
        assert result["posts"][0]["external_post_id"] == "post1"
        assert result["posts"][1]["external_post_id"] == "post2"

    def test_browse_location_includes_cursor(
        self, db_session, setup_provider, mock_provider_client, sample_posts
    ):
        """Should include cursor for pagination."""
        from rediska_core.domain.services.browse import BrowseService

        mock_provider_client.browse_location.return_value = {
            "posts": sample_posts,
            "after": "next_page_cursor",
        }

        service = BrowseService(
            db=db_session,
            provider_client=mock_provider_client,
        )

        result = service.browse_location("reddit", "r/test")

        assert result["cursor"] == "next_page_cursor"

    def test_browse_location_with_cursor(
        self, db_session, setup_provider, mock_provider_client, sample_posts
    ):
        """Should pass cursor to provider for pagination."""
        from rediska_core.domain.services.browse import BrowseService

        mock_provider_client.browse_location.return_value = {
            "posts": sample_posts,
            "after": None,
        }

        service = BrowseService(
            db=db_session,
            provider_client=mock_provider_client,
        )

        service.browse_location("reddit", "r/test", cursor="page2_cursor")

        mock_provider_client.browse_location.assert_called_once()
        call_kwargs = mock_provider_client.browse_location.call_args[1]
        assert call_kwargs.get("after") == "page2_cursor"

    def test_browse_location_with_limit(
        self, db_session, setup_provider, mock_provider_client, sample_posts
    ):
        """Should pass limit to provider."""
        from rediska_core.domain.services.browse import BrowseService

        mock_provider_client.browse_location.return_value = {
            "posts": sample_posts[:1],
            "after": None,
        }

        service = BrowseService(
            db=db_session,
            provider_client=mock_provider_client,
        )

        service.browse_location("reddit", "r/test", limit=1)

        call_kwargs = mock_provider_client.browse_location.call_args[1]
        assert call_kwargs.get("limit") == 1


class TestPostNormalization:
    """Tests for normalizing post data from providers."""

    def test_normalizes_post_fields(
        self, db_session, setup_provider, mock_provider_client, sample_posts
    ):
        """Should normalize provider post format to common schema."""
        from rediska_core.domain.services.browse import BrowseService

        mock_provider_client.browse_location.return_value = {
            "posts": sample_posts,
            "after": None,
        }

        service = BrowseService(
            db=db_session,
            provider_client=mock_provider_client,
        )

        result = service.browse_location("reddit", "r/test")

        post = result["posts"][0]
        # Check normalized fields
        assert "external_post_id" in post
        assert "title" in post
        assert "body_text" in post
        assert "author_username" in post
        assert "post_url" in post
        assert "source_location" in post

    def test_includes_provider_id(
        self, db_session, setup_provider, mock_provider_client, sample_posts
    ):
        """Should include provider_id in each post."""
        from rediska_core.domain.services.browse import BrowseService

        mock_provider_client.browse_location.return_value = {
            "posts": sample_posts,
            "after": None,
        }

        service = BrowseService(
            db=db_session,
            provider_client=mock_provider_client,
        )

        result = service.browse_location("reddit", "r/test")

        for post in result["posts"]:
            assert post["provider_id"] == "reddit"

    def test_includes_source_location(
        self, db_session, setup_provider, mock_provider_client, sample_posts
    ):
        """Should include source_location in each post."""
        from rediska_core.domain.services.browse import BrowseService

        mock_provider_client.browse_location.return_value = {
            "posts": sample_posts,
            "after": None,
        }

        service = BrowseService(
            db=db_session,
            provider_client=mock_provider_client,
        )

        result = service.browse_location("reddit", "r/programming")

        for post in result["posts"]:
            assert post["source_location"] == "r/programming"

    def test_converts_timestamp(
        self, db_session, setup_provider, mock_provider_client, sample_posts
    ):
        """Should convert Unix timestamp to datetime."""
        from rediska_core.domain.services.browse import BrowseService

        mock_provider_client.browse_location.return_value = {
            "posts": sample_posts,
            "after": None,
        }

        service = BrowseService(
            db=db_session,
            provider_client=mock_provider_client,
        )

        result = service.browse_location("reddit", "r/test")

        post = result["posts"][0]
        assert "post_created_at" in post
        # Should be ISO format string or datetime
        assert post["post_created_at"] is not None


class TestBrowseErrorHandling:
    """Tests for error handling in browse operations."""

    def test_handles_provider_error(
        self, db_session, setup_provider, mock_provider_client
    ):
        """Should handle provider API errors gracefully."""
        from rediska_core.domain.services.browse import BrowseService, BrowseError

        mock_provider_client.browse_location.side_effect = Exception("API Error")

        service = BrowseService(
            db=db_session,
            provider_client=mock_provider_client,
        )

        with pytest.raises(BrowseError) as exc_info:
            service.browse_location("reddit", "r/test")

        assert "Failed to browse" in str(exc_info.value)

    def test_handles_empty_response(
        self, db_session, setup_provider, mock_provider_client
    ):
        """Should handle empty posts list."""
        from rediska_core.domain.services.browse import BrowseService

        mock_provider_client.browse_location.return_value = {
            "posts": [],
            "after": None,
        }

        service = BrowseService(
            db=db_session,
            provider_client=mock_provider_client,
        )

        result = service.browse_location("reddit", "r/empty")

        assert result["posts"] == []
        assert result["cursor"] is None

    def test_handles_invalid_provider(self, db_session, mock_provider_client):
        """Should handle unknown provider ID."""
        from rediska_core.domain.services.browse import BrowseService, BrowseError

        service = BrowseService(
            db=db_session,
            provider_client=mock_provider_client,
        )

        with pytest.raises(BrowseError) as exc_info:
            service.browse_location("unknown_provider", "location")

        assert "Unknown provider" in str(exc_info.value)


class TestSortOptions:
    """Tests for sorting options when browsing."""

    def test_browse_with_sort_hot(
        self, db_session, setup_provider, mock_provider_client, sample_posts
    ):
        """Should support 'hot' sort option."""
        from rediska_core.domain.services.browse import BrowseService

        mock_provider_client.browse_location.return_value = {
            "posts": sample_posts,
            "after": None,
        }

        service = BrowseService(
            db=db_session,
            provider_client=mock_provider_client,
        )

        service.browse_location("reddit", "r/test", sort="hot")

        call_kwargs = mock_provider_client.browse_location.call_args[1]
        assert call_kwargs.get("sort") == "hot"

    def test_browse_with_sort_new(
        self, db_session, setup_provider, mock_provider_client, sample_posts
    ):
        """Should support 'new' sort option."""
        from rediska_core.domain.services.browse import BrowseService

        mock_provider_client.browse_location.return_value = {
            "posts": sample_posts,
            "after": None,
        }

        service = BrowseService(
            db=db_session,
            provider_client=mock_provider_client,
        )

        service.browse_location("reddit", "r/test", sort="new")

        call_kwargs = mock_provider_client.browse_location.call_args[1]
        assert call_kwargs.get("sort") == "new"

    def test_browse_with_sort_top(
        self, db_session, setup_provider, mock_provider_client, sample_posts
    ):
        """Should support 'top' sort option."""
        from rediska_core.domain.services.browse import BrowseService

        mock_provider_client.browse_location.return_value = {
            "posts": sample_posts,
            "after": None,
        }

        service = BrowseService(
            db=db_session,
            provider_client=mock_provider_client,
        )

        service.browse_location("reddit", "r/test", sort="top")

        call_kwargs = mock_provider_client.browse_location.call_args[1]
        assert call_kwargs.get("sort") == "top"
