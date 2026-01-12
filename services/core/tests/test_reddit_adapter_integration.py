"""Integration tests for Reddit adapter.

These tests verify the adapter works correctly with the Reddit API.
They require valid OAuth credentials and are skipped by default.

To run these tests:
    pytest tests/test_reddit_adapter_integration.py -v --run-integration

Required environment variables:
    REDDIT_CLIENT_ID: Reddit app client ID
    REDDIT_CLIENT_SECRET: Reddit app client secret
    REDDIT_ACCESS_TOKEN: Valid OAuth access token
    REDDIT_REFRESH_TOKEN: Valid OAuth refresh token
"""

import os

import pytest

from rediska_core.providers.base import (
    PaginatedResult,
    ProfileItemType,
    ProviderConversation,
    ProviderPost,
    ProviderProfile,
    ProviderProfileItem,
)
from rediska_core.providers.reddit.adapter import RedditAdapter


# Skip all integration tests unless explicitly requested
pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="Integration tests require --run-integration flag and credentials",
)


@pytest.fixture
def reddit_adapter():
    """Create a Reddit adapter with real credentials."""
    access_token = os.environ.get("REDDIT_ACCESS_TOKEN", "")
    refresh_token = os.environ.get("REDDIT_REFRESH_TOKEN", "")
    client_id = os.environ.get("REDDIT_CLIENT_ID", "")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")

    if not all([access_token, refresh_token, client_id, client_secret]):
        pytest.skip("Missing Reddit credentials")

    return RedditAdapter(
        access_token=access_token,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        user_agent="Rediska/1.0 Integration Test",
    )


class TestRedditAdapterIntegration:
    """Integration tests for Reddit adapter."""

    @pytest.mark.asyncio
    async def test_browse_location_returns_real_posts(self, reddit_adapter):
        """browse_location should return real posts from a subreddit."""
        result = await reddit_adapter.browse_location("r/programming", limit=5)

        assert isinstance(result, PaginatedResult)
        assert len(result.items) > 0
        assert all(isinstance(p, ProviderPost) for p in result.items)

        # Verify post has expected fields populated
        post = result.items[0]
        assert post.external_id
        assert post.title
        assert post.location == "r/programming"

    @pytest.mark.asyncio
    async def test_fetch_profile_returns_real_user(self, reddit_adapter):
        """fetch_profile should return real user data."""
        # Use a well-known Reddit account
        result = await reddit_adapter.fetch_profile("spez")

        assert isinstance(result, ProviderProfile)
        assert result.username == "spez"
        assert result.karma > 0

    @pytest.mark.asyncio
    async def test_fetch_profile_items_returns_user_content(self, reddit_adapter):
        """fetch_profile_items should return user's posts and comments."""
        result = await reddit_adapter.fetch_profile_items("spez", limit=10)

        assert isinstance(result, PaginatedResult)
        assert len(result.items) > 0
        assert all(isinstance(i, ProviderProfileItem) for i in result.items)

    @pytest.mark.asyncio
    async def test_fetch_profile_items_filters_by_type(self, reddit_adapter):
        """fetch_profile_items should filter by item type."""
        result = await reddit_adapter.fetch_profile_items(
            "spez", item_type=ProfileItemType.POST, limit=5
        )

        assert isinstance(result, PaginatedResult)
        # All items should be posts
        for item in result.items:
            assert item.item_type == ProfileItemType.POST

    @pytest.mark.asyncio
    async def test_fetch_post_returns_real_post(self, reddit_adapter):
        """fetch_post should return a specific post."""
        # First browse to get a post ID
        browse_result = await reddit_adapter.browse_location("r/python", limit=1)
        if not browse_result.items:
            pytest.skip("No posts found to test")

        post_id = browse_result.items[0].external_id

        # Fetch the specific post
        result = await reddit_adapter.fetch_post(post_id)

        assert isinstance(result, ProviderPost)
        assert result.external_id == post_id

    @pytest.mark.asyncio
    async def test_list_conversations_returns_inbox(self, reddit_adapter):
        """list_conversations should return user's inbox conversations."""
        result = await reddit_adapter.list_conversations(limit=10)

        assert isinstance(result, PaginatedResult)
        # May be empty if user has no messages
        assert all(isinstance(c, ProviderConversation) for c in result.items)

    @pytest.mark.asyncio
    async def test_adapter_handles_nonexistent_user(self, reddit_adapter):
        """fetch_profile should return None for nonexistent user."""
        result = await reddit_adapter.fetch_profile("this_user_definitely_does_not_exist_12345")

        assert result is None

    @pytest.mark.asyncio
    async def test_adapter_handles_nonexistent_post(self, reddit_adapter):
        """fetch_post should return None for nonexistent post."""
        result = await reddit_adapter.fetch_post("zzzzzzzzzzz")

        assert result is None
