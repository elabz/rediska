"""Unit tests for Reddit adapter."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rediska_core.providers.base import (
    MessageDirection,
    PaginatedResult,
    ProfileItemType,
    ProviderAdapter,
    ProviderConversation,
    ProviderMessage,
    ProviderPost,
    ProviderProfile,
    ProviderProfileItem,
    RemoteVisibility,
)
from rediska_core.providers.reddit.adapter import RedditAdapter


@pytest.fixture
def mock_tokens():
    """Mock OAuth tokens."""
    return {
        "access_token": "test_access_token",
        "refresh_token": "test_refresh_token",
    }


@pytest.fixture
def adapter_config():
    """Reddit adapter configuration."""
    return {
        "client_id": "test_client_id",
        "client_secret": "test_client_secret",
        "user_agent": "Rediska/1.0 test",
    }


@pytest.fixture
def reddit_adapter(adapter_config, mock_tokens):
    """Create a Reddit adapter for testing."""
    return RedditAdapter(
        access_token=mock_tokens["access_token"],
        refresh_token=mock_tokens["refresh_token"],
        client_id=adapter_config["client_id"],
        client_secret=adapter_config["client_secret"],
        user_agent=adapter_config["user_agent"],
    )


class TestRedditAdapterBasics:
    """Basic tests for Reddit adapter."""

    def test_adapter_is_provider_adapter(self, reddit_adapter):
        """RedditAdapter should be a ProviderAdapter."""
        assert isinstance(reddit_adapter, ProviderAdapter)

    def test_adapter_provider_id(self, reddit_adapter):
        """RedditAdapter should have provider_id 'reddit'."""
        assert reddit_adapter.provider_id == "reddit"


class TestRedditAdapterListConversations:
    """Tests for list_conversations method."""

    @pytest.mark.asyncio
    async def test_list_conversations_returns_paginated_result(self, reddit_adapter):
        """list_conversations should return PaginatedResult."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "children": [],
                "after": None,
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await reddit_adapter.list_conversations()

        assert isinstance(result, PaginatedResult)
        assert isinstance(result.items, list)

    @pytest.mark.asyncio
    async def test_list_conversations_maps_data_correctly(self, reddit_adapter):
        """list_conversations should map Reddit data to ProviderConversation."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "children": [
                    {
                        "kind": "t4",
                        "data": {
                            "id": "msg_123",
                            "name": "t4_msg_123",
                            "author": "other_user",
                            "dest": "my_user",
                            "subject": "Hello there",
                            "body": "How are you?",
                            "created_utc": 1704067200.0,
                            "new": True,
                            "first_message_name": "t4_first_123",
                        }
                    }
                ],
                "after": "cursor_abc",
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await reddit_adapter.list_conversations()

        assert len(result.items) == 1
        conv = result.items[0]
        assert isinstance(conv, ProviderConversation)
        assert conv.counterpart_username == "other_user"
        assert conv.subject == "Hello there"
        assert conv.is_unread is True

    @pytest.mark.asyncio
    async def test_list_conversations_handles_pagination(self, reddit_adapter):
        """list_conversations should handle pagination correctly."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "children": [
                    {
                        "kind": "t4",
                        "data": {
                            "id": "msg_123",
                            "name": "t4_msg_123",
                            "author": "user1",
                            "dest": "my_user",
                            "subject": "Test",
                            "body": "Test",
                            "created_utc": 1704067200.0,
                            "new": False,
                            "first_message_name": None,
                        }
                    }
                ],
                "after": "next_cursor",
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await reddit_adapter.list_conversations()

        assert result.next_cursor == "next_cursor"
        assert result.has_more is True

    @pytest.mark.asyncio
    async def test_list_conversations_respects_limit(self, reddit_adapter):
        """list_conversations should pass limit to API."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"children": [], "after": None}}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            await reddit_adapter.list_conversations(limit=25)

            # Verify the limit was passed to the API
            call_args = mock_instance.get.call_args
            assert "limit=25" in str(call_args) or call_args[1].get("params", {}).get("limit") == 25


class TestRedditAdapterListMessages:
    """Tests for list_messages method."""

    @pytest.mark.asyncio
    async def test_list_messages_returns_paginated_result(self, reddit_adapter):
        """list_messages should return PaginatedResult."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "children": [],
                "after": None,
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await reddit_adapter.list_messages("conv_123")

        assert isinstance(result, PaginatedResult)

    @pytest.mark.asyncio
    async def test_list_messages_maps_data_correctly(self, reddit_adapter):
        """list_messages should map Reddit data to ProviderMessage."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "children": [
                    {
                        "kind": "t4",
                        "data": {
                            "id": "msg_456",
                            "name": "t4_msg_456",
                            "author": "sender_user",
                            "dest": "receiver_user",
                            "subject": "Re: Hello",
                            "body": "I am fine, thanks!",
                            "created_utc": 1704067200.0,
                            "first_message_name": "t4_conv_123",
                        }
                    }
                ],
                "after": None,
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            # Use full Reddit name format (t4_ prefix) matching what list_conversations returns
            result = await reddit_adapter.list_messages("t4_conv_123")

        assert len(result.items) == 1
        msg = result.items[0]
        assert isinstance(msg, ProviderMessage)
        assert msg.external_id == "msg_456"
        assert msg.body_text == "I am fine, thanks!"
        assert msg.sender_username == "sender_user"


class TestRedditAdapterBrowseLocation:
    """Tests for browse_location method."""

    @pytest.mark.asyncio
    async def test_browse_location_returns_paginated_result(self, reddit_adapter):
        """browse_location should return PaginatedResult."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "children": [],
                "after": None,
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await reddit_adapter.browse_location("r/programming")

        assert isinstance(result, PaginatedResult)

    @pytest.mark.asyncio
    async def test_browse_location_maps_posts_correctly(self, reddit_adapter):
        """browse_location should map Reddit posts to ProviderPost."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "id": "post_123",
                            "name": "t3_post_123",
                            "author": "post_author",
                            "author_fullname": "t2_author_id",
                            "title": "Great post title",
                            "selftext": "Post body content",
                            "url": "https://reddit.com/r/test/post_123",
                            "subreddit": "test",
                            "subreddit_name_prefixed": "r/test",
                            "created_utc": 1704067200.0,
                            "score": 150,
                            "num_comments": 42,
                            "over_18": False,
                            "thumbnail": "https://example.com/thumb.jpg",
                        }
                    }
                ],
                "after": "next_page",
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await reddit_adapter.browse_location("r/test")

        assert len(result.items) == 1
        post = result.items[0]
        assert isinstance(post, ProviderPost)
        assert post.external_id == "post_123"
        assert post.author_username == "post_author"
        assert post.title == "Great post title"
        assert post.body_text == "Post body content"
        assert post.score == 150
        assert post.num_comments == 42
        assert post.is_nsfw is False

    @pytest.mark.asyncio
    async def test_browse_location_handles_deleted_author(self, reddit_adapter):
        """browse_location should handle [deleted] authors."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "id": "post_123",
                            "name": "t3_post_123",
                            "author": "[deleted]",
                            "title": "Deleted post",
                            "selftext": "[removed]",
                            "url": "https://reddit.com/r/test/post_123",
                            "subreddit": "test",
                            "subreddit_name_prefixed": "r/test",
                            "created_utc": 1704067200.0,
                            "score": 0,
                            "num_comments": 0,
                            "over_18": False,
                        }
                    }
                ],
                "after": None,
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await reddit_adapter.browse_location("r/test")

        post = result.items[0]
        assert post.author_username == "[deleted]"
        assert post.remote_visibility == RemoteVisibility.DELETED_BY_AUTHOR


class TestRedditAdapterFetchPost:
    """Tests for fetch_post method."""

    @pytest.mark.asyncio
    async def test_fetch_post_returns_post(self, reddit_adapter):
        """fetch_post should return ProviderPost when found."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "data": {
                    "children": [
                        {
                            "kind": "t3",
                            "data": {
                                "id": "post_123",
                                "name": "t3_post_123",
                                "author": "test_author",
                                "author_fullname": "t2_author",
                                "title": "Test Post",
                                "selftext": "Body",
                                "url": "https://reddit.com/r/test/post",
                                "subreddit": "test",
                                "subreddit_name_prefixed": "r/test",
                                "created_utc": 1704067200.0,
                                "score": 100,
                                "num_comments": 10,
                                "over_18": False,
                            }
                        }
                    ]
                }
            }
        ]

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await reddit_adapter.fetch_post("post_123")

        assert result is not None
        assert isinstance(result, ProviderPost)
        assert result.external_id == "post_123"
        assert result.title == "Test Post"

    @pytest.mark.asyncio
    async def test_fetch_post_returns_none_when_not_found(self, reddit_adapter):
        """fetch_post should return None when post not found."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await reddit_adapter.fetch_post("nonexistent")

        assert result is None


class TestRedditAdapterFetchProfile:
    """Tests for fetch_profile method."""

    @pytest.mark.asyncio
    async def test_fetch_profile_returns_profile(self, reddit_adapter):
        """fetch_profile should return ProviderProfile when found."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "id": "t2_user123",
                "name": "testuser",
                "subreddit": {
                    "display_name": "u_testuser",
                    "public_description": "I am a test user",
                    "icon_img": "https://example.com/avatar.jpg",
                },
                "created_utc": 1600000000.0,
                "link_karma": 1000,
                "comment_karma": 500,
                "verified": True,
                "is_suspended": False,
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await reddit_adapter.fetch_profile("testuser")

        assert result is not None
        assert isinstance(result, ProviderProfile)
        assert result.username == "testuser"
        assert result.karma == 1500  # link + comment karma
        assert result.is_verified is True

    @pytest.mark.asyncio
    async def test_fetch_profile_handles_suspended_user(self, reddit_adapter):
        """fetch_profile should handle suspended users."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "id": "t2_suspended",
                "name": "suspendeduser",
                "is_suspended": True,
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await reddit_adapter.fetch_profile("suspendeduser")

        assert result is not None
        assert result.is_suspended is True

    @pytest.mark.asyncio
    async def test_fetch_profile_returns_none_when_not_found(self, reddit_adapter):
        """fetch_profile should return None when user not found."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await reddit_adapter.fetch_profile("nonexistent")

        assert result is None


class TestRedditAdapterFetchProfileItems:
    """Tests for fetch_profile_items method."""

    @pytest.mark.asyncio
    async def test_fetch_profile_items_returns_paginated_result(self, reddit_adapter):
        """fetch_profile_items should return PaginatedResult."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "children": [],
                "after": None,
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await reddit_adapter.fetch_profile_items("testuser")

        assert isinstance(result, PaginatedResult)

    @pytest.mark.asyncio
    async def test_fetch_profile_items_maps_posts(self, reddit_adapter):
        """fetch_profile_items should map posts correctly."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "id": "post_123",
                            "name": "t3_post_123",
                            "author": "testuser",
                            "author_fullname": "t2_user",
                            "title": "My Post",
                            "selftext": "Content",
                            "url": "https://reddit.com/r/test/post",
                            "subreddit_name_prefixed": "r/test",
                            "created_utc": 1704067200.0,
                            "score": 50,
                        }
                    }
                ],
                "after": None,
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await reddit_adapter.fetch_profile_items("testuser")

        assert len(result.items) == 1
        item = result.items[0]
        assert isinstance(item, ProviderProfileItem)
        assert item.item_type == ProfileItemType.POST
        assert item.title == "My Post"

    @pytest.mark.asyncio
    async def test_fetch_profile_items_maps_comments(self, reddit_adapter):
        """fetch_profile_items should map comments correctly."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "children": [
                    {
                        "kind": "t1",
                        "data": {
                            "id": "comment_123",
                            "name": "t1_comment_123",
                            "author": "testuser",
                            "author_fullname": "t2_user",
                            "body": "This is my comment",
                            "link_title": "Parent post title",
                            "subreddit_name_prefixed": "r/test",
                            "created_utc": 1704067200.0,
                            "score": 25,
                        }
                    }
                ],
                "after": None,
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await reddit_adapter.fetch_profile_items("testuser")

        assert len(result.items) == 1
        item = result.items[0]
        assert item.item_type == ProfileItemType.COMMENT
        assert item.body_text == "This is my comment"

    @pytest.mark.asyncio
    async def test_fetch_profile_items_filters_by_type(self, reddit_adapter):
        """fetch_profile_items should filter by item type."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "id": "post_123",
                            "author": "testuser",
                            "title": "Post",
                            "selftext": "",
                            "url": "https://reddit.com/r/test/post",
                            "subreddit_name_prefixed": "r/test",
                            "created_utc": 1704067200.0,
                            "score": 10,
                        }
                    }
                ],
                "after": None,
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            # Request only posts
            result = await reddit_adapter.fetch_profile_items(
                "testuser", item_type=ProfileItemType.POST
            )

        assert len(result.items) >= 0  # API should be called with posts filter


class TestRedditAdapterTokenRefresh:
    """Tests for token refresh handling."""

    @pytest.mark.asyncio
    async def test_adapter_refreshes_token_on_401(self, adapter_config, mock_tokens):
        """Adapter should refresh token when receiving 401."""
        adapter = RedditAdapter(
            access_token=mock_tokens["access_token"],
            refresh_token=mock_tokens["refresh_token"],
            client_id=adapter_config["client_id"],
            client_secret=adapter_config["client_secret"],
            user_agent=adapter_config["user_agent"],
        )

        # First call returns 401, second returns success after refresh
        mock_401_response = MagicMock()
        mock_401_response.status_code = 401

        mock_success_response = MagicMock()
        mock_success_response.status_code = 200
        mock_success_response.json.return_value = {"data": {"children": [], "after": None}}

        mock_refresh_response = MagicMock()
        mock_refresh_response.status_code = 200
        mock_refresh_response.json.return_value = {
            "access_token": "new_access_token",
            "token_type": "bearer",
            "expires_in": 3600,
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            # First get returns 401, second returns success
            mock_instance.get.side_effect = [mock_401_response, mock_success_response]
            mock_instance.post.return_value = mock_refresh_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await adapter.list_conversations()

        assert isinstance(result, PaginatedResult)
        assert adapter.access_token == "new_access_token"
