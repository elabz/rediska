"""Unit tests for provider interface and DTOs."""

from datetime import datetime, timezone
from typing import Optional

import pytest

from rediska_core.providers.base import (
    ProviderAdapter,
    ProviderConversation,
    ProviderMessage,
    ProviderPost,
    ProviderProfile,
    ProviderProfileItem,
    ProfileItemType,
    MessageDirection,
    RemoteVisibility,
    PaginatedResult,
    SendMessageResult,
)


class TestProviderDTOs:
    """Tests for provider DTOs."""

    def test_provider_message_creation(self):
        """ProviderMessage should be creatable with required fields."""
        msg = ProviderMessage(
            external_id="msg_123",
            conversation_id="conv_456",
            direction=MessageDirection.IN,
            body_text="Hello world",
            sent_at=datetime.now(timezone.utc),
        )

        assert msg.external_id == "msg_123"
        assert msg.conversation_id == "conv_456"
        assert msg.direction == MessageDirection.IN
        assert msg.body_text == "Hello world"

    def test_provider_message_with_optional_fields(self):
        """ProviderMessage should support optional fields."""
        msg = ProviderMessage(
            external_id="msg_123",
            conversation_id="conv_456",
            direction=MessageDirection.OUT,
            body_text="Reply",
            sent_at=datetime.now(timezone.utc),
            sender_id="user_abc",
            sender_username="testuser",
            attachments=["https://example.com/image.jpg"],
            remote_visibility=RemoteVisibility.VISIBLE,
        )

        assert msg.sender_id == "user_abc"
        assert msg.sender_username == "testuser"
        assert len(msg.attachments) == 1
        assert msg.remote_visibility == RemoteVisibility.VISIBLE

    def test_provider_conversation_creation(self):
        """ProviderConversation should be creatable with required fields."""
        conv = ProviderConversation(
            external_id="conv_123",
            counterpart_id="user_456",
            counterpart_username="otheruser",
        )

        assert conv.external_id == "conv_123"
        assert conv.counterpart_id == "user_456"
        assert conv.counterpart_username == "otheruser"

    def test_provider_conversation_with_optional_fields(self):
        """ProviderConversation should support optional fields."""
        conv = ProviderConversation(
            external_id="conv_123",
            counterpart_id="user_456",
            counterpart_username="otheruser",
            subject="Hello",
            last_message_at=datetime.now(timezone.utc),
            message_count=5,
            is_unread=True,
        )

        assert conv.subject == "Hello"
        assert conv.message_count == 5
        assert conv.is_unread is True

    def test_provider_post_creation(self):
        """ProviderPost should be creatable with required fields."""
        post = ProviderPost(
            external_id="post_123",
            author_id="user_456",
            author_username="author",
            title="Post Title",
            url="https://reddit.com/r/test/post",
            location="r/test",
        )

        assert post.external_id == "post_123"
        assert post.author_username == "author"
        assert post.title == "Post Title"
        assert post.location == "r/test"

    def test_provider_post_with_optional_fields(self):
        """ProviderPost should support optional fields."""
        post = ProviderPost(
            external_id="post_123",
            author_id="user_456",
            author_username="author",
            title="Post Title",
            url="https://reddit.com/r/test/post",
            location="r/test",
            body_text="Post content here",
            created_at=datetime.now(timezone.utc),
            score=100,
            num_comments=25,
            remote_visibility=RemoteVisibility.VISIBLE,
        )

        assert post.body_text == "Post content here"
        assert post.score == 100
        assert post.num_comments == 25

    def test_provider_profile_creation(self):
        """ProviderProfile should be creatable with required fields."""
        profile = ProviderProfile(
            external_id="user_123",
            username="testuser",
        )

        assert profile.external_id == "user_123"
        assert profile.username == "testuser"

    def test_provider_profile_with_optional_fields(self):
        """ProviderProfile should support optional fields."""
        profile = ProviderProfile(
            external_id="user_123",
            username="testuser",
            display_name="Test User",
            avatar_url="https://example.com/avatar.jpg",
            bio="I am a test user",
            created_at=datetime.now(timezone.utc),
            karma=1000,
            is_verified=True,
            is_suspended=False,
        )

        assert profile.display_name == "Test User"
        assert profile.karma == 1000
        assert profile.is_verified is True

    def test_provider_profile_item_creation(self):
        """ProviderProfileItem should be creatable with required fields."""
        item = ProviderProfileItem(
            external_id="item_123",
            item_type=ProfileItemType.POST,
            author_id="user_456",
        )

        assert item.external_id == "item_123"
        assert item.item_type == ProfileItemType.POST

    def test_provider_profile_item_types(self):
        """ProfileItemType should have post, comment, and image."""
        assert ProfileItemType.POST == "post"
        assert ProfileItemType.COMMENT == "comment"
        assert ProfileItemType.IMAGE == "image"

    def test_message_direction_enum(self):
        """MessageDirection should have in, out, and system."""
        assert MessageDirection.IN == "in"
        assert MessageDirection.OUT == "out"
        assert MessageDirection.SYSTEM == "system"

    def test_remote_visibility_enum(self):
        """RemoteVisibility should have expected values."""
        assert RemoteVisibility.VISIBLE == "visible"
        assert RemoteVisibility.DELETED_BY_AUTHOR == "deleted_by_author"
        assert RemoteVisibility.REMOVED == "removed"
        assert RemoteVisibility.UNKNOWN == "unknown"


class TestPaginatedResult:
    """Tests for PaginatedResult."""

    def test_paginated_result_creation(self):
        """PaginatedResult should wrap items with cursor."""
        items = [
            ProviderMessage(
                external_id="msg_1",
                conversation_id="conv_1",
                direction=MessageDirection.IN,
                body_text="Message 1",
                sent_at=datetime.now(timezone.utc),
            ),
            ProviderMessage(
                external_id="msg_2",
                conversation_id="conv_1",
                direction=MessageDirection.OUT,
                body_text="Message 2",
                sent_at=datetime.now(timezone.utc),
            ),
        ]

        result = PaginatedResult(
            items=items,
            next_cursor="cursor_abc",
            has_more=True,
        )

        assert len(result.items) == 2
        assert result.next_cursor == "cursor_abc"
        assert result.has_more is True

    def test_paginated_result_empty(self):
        """PaginatedResult should handle empty results."""
        result = PaginatedResult(
            items=[],
            next_cursor=None,
            has_more=False,
        )

        assert len(result.items) == 0
        assert result.next_cursor is None
        assert result.has_more is False

    def test_paginated_result_with_total(self):
        """PaginatedResult should support optional total count."""
        result = PaginatedResult(
            items=["item1", "item2"],
            next_cursor=None,
            has_more=False,
            total=100,
        )

        assert result.total == 100


class TestProviderAdapterInterface:
    """Tests for ProviderAdapter interface."""

    def test_adapter_is_abstract(self):
        """ProviderAdapter should not be instantiable directly."""
        with pytest.raises(TypeError):
            ProviderAdapter()

    def test_adapter_requires_provider_id(self):
        """Adapter implementations must define provider_id."""
        class IncompleteAdapter(ProviderAdapter):
            pass

        with pytest.raises(TypeError):
            IncompleteAdapter()

    def test_adapter_subclass_must_implement_methods(self):
        """Adapter subclasses must implement required methods."""
        class MinimalAdapter(ProviderAdapter):
            @property
            def provider_id(self) -> str:
                return "test"

        # Should still fail because abstract methods not implemented
        with pytest.raises(TypeError):
            MinimalAdapter()


class TestProviderAdapterContract:
    """Tests for ProviderAdapter method contracts using a mock implementation."""

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock adapter for testing contracts."""
        from unittest.mock import AsyncMock, MagicMock

        class MockAdapter(ProviderAdapter):
            @property
            def provider_id(self) -> str:
                return "mock"

            async def list_conversations(
                self, cursor: Optional[str] = None, limit: int = 50
            ) -> PaginatedResult[ProviderConversation]:
                return PaginatedResult(items=[], next_cursor=None, has_more=False)

            async def list_messages(
                self,
                conversation_id: str,
                cursor: Optional[str] = None,
                limit: int = 100,
            ) -> PaginatedResult[ProviderMessage]:
                return PaginatedResult(items=[], next_cursor=None, has_more=False)

            async def browse_location(
                self,
                location: str,
                cursor: Optional[str] = None,
                limit: int = 25,
            ) -> PaginatedResult[ProviderPost]:
                return PaginatedResult(items=[], next_cursor=None, has_more=False)

            async def fetch_post(self, post_id: str) -> Optional[ProviderPost]:
                return None

            async def fetch_profile(self, user_id: str) -> Optional[ProviderProfile]:
                return None

            async def fetch_profile_items(
                self,
                user_id: str,
                item_type: Optional[ProfileItemType] = None,
                cursor: Optional[str] = None,
                limit: int = 100,
            ) -> PaginatedResult[ProviderProfileItem]:
                return PaginatedResult(items=[], next_cursor=None, has_more=False)

            async def send_message(
                self,
                recipient_username: str,
                subject: str,
                body: str,
            ) -> SendMessageResult:
                return SendMessageResult(
                    external_message_id="mock_msg_123",
                    sent_at=datetime.now(timezone.utc),
                    success=True,
                )

        return MockAdapter()

    def test_mock_adapter_has_provider_id(self, mock_adapter):
        """Mock adapter should have provider_id."""
        assert mock_adapter.provider_id == "mock"

    @pytest.mark.asyncio
    async def test_list_conversations_returns_paginated_result(self, mock_adapter):
        """list_conversations should return PaginatedResult."""
        result = await mock_adapter.list_conversations()
        assert isinstance(result, PaginatedResult)
        assert isinstance(result.items, list)

    @pytest.mark.asyncio
    async def test_list_messages_returns_paginated_result(self, mock_adapter):
        """list_messages should return PaginatedResult."""
        result = await mock_adapter.list_messages("conv_123")
        assert isinstance(result, PaginatedResult)

    @pytest.mark.asyncio
    async def test_browse_location_returns_paginated_result(self, mock_adapter):
        """browse_location should return PaginatedResult."""
        result = await mock_adapter.browse_location("r/test")
        assert isinstance(result, PaginatedResult)

    @pytest.mark.asyncio
    async def test_fetch_post_returns_optional_post(self, mock_adapter):
        """fetch_post should return Optional[ProviderPost]."""
        result = await mock_adapter.fetch_post("post_123")
        assert result is None or isinstance(result, ProviderPost)

    @pytest.mark.asyncio
    async def test_fetch_profile_returns_optional_profile(self, mock_adapter):
        """fetch_profile should return Optional[ProviderProfile]."""
        result = await mock_adapter.fetch_profile("user_123")
        assert result is None or isinstance(result, ProviderProfile)

    @pytest.mark.asyncio
    async def test_fetch_profile_items_returns_paginated_result(self, mock_adapter):
        """fetch_profile_items should return PaginatedResult."""
        result = await mock_adapter.fetch_profile_items("user_123")
        assert isinstance(result, PaginatedResult)

    @pytest.mark.asyncio
    async def test_send_message_returns_result(self, mock_adapter):
        """send_message should return SendMessageResult."""
        result = await mock_adapter.send_message(
            recipient_username="testuser",
            subject="Test Subject",
            body="Test message body",
        )
        assert isinstance(result, SendMessageResult)
        assert result.success is True
