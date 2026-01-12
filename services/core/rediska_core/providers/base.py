"""Base provider interface and DTOs.

This module defines the provider-agnostic interface that all provider
adapters must implement, along with normalized data transfer objects.

The DTOs ensure consistent data representation across providers:
- ProviderMessage: Normalized message data
- ProviderConversation: Normalized conversation/thread data
- ProviderPost: Normalized post/content data
- ProviderProfile: Normalized user profile data
- ProviderProfileItem: Normalized profile content (posts/comments/images)

Usage:
    class RedditAdapter(ProviderAdapter):
        @property
        def provider_id(self) -> str:
            return "reddit"

        async def list_conversations(self, ...) -> PaginatedResult[ProviderConversation]:
            # Implementation
            pass
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Generic, Optional, TypeVar


# =============================================================================
# ENUMS
# =============================================================================


class MessageDirection(str, Enum):
    """Direction of a message."""

    IN = "in"
    OUT = "out"
    SYSTEM = "system"


class RemoteVisibility(str, Enum):
    """Visibility status of remote content."""

    VISIBLE = "visible"
    DELETED_BY_AUTHOR = "deleted_by_author"
    REMOVED = "removed"
    UNKNOWN = "unknown"


class ProfileItemType(str, Enum):
    """Type of profile item."""

    POST = "post"
    COMMENT = "comment"
    IMAGE = "image"


# =============================================================================
# DATA TRANSFER OBJECTS
# =============================================================================


@dataclass
class ProviderMessage:
    """Normalized message from a provider.

    Represents a single message in a conversation, with all fields
    normalized to a consistent format across providers.
    """

    external_id: str
    conversation_id: str
    direction: MessageDirection
    body_text: str
    sent_at: datetime

    # Optional fields
    sender_id: Optional[str] = None
    sender_username: Optional[str] = None
    attachments: list[str] = field(default_factory=list)
    remote_visibility: RemoteVisibility = RemoteVisibility.UNKNOWN
    raw_data: Optional[dict] = None


@dataclass
class ProviderConversation:
    """Normalized conversation from a provider.

    Represents a conversation/thread with another user.
    """

    external_id: str
    counterpart_id: str
    counterpart_username: str

    # Optional fields
    subject: Optional[str] = None
    last_message_at: Optional[datetime] = None
    message_count: int = 0
    is_unread: bool = False
    raw_data: Optional[dict] = None


@dataclass
class ProviderPost:
    """Normalized post from a provider.

    Represents a post/submission from a location (e.g., subreddit).
    """

    external_id: str
    author_id: str
    author_username: str
    title: str
    url: str
    location: str

    # Optional fields
    body_text: Optional[str] = None
    created_at: Optional[datetime] = None
    score: int = 0
    num_comments: int = 0
    remote_visibility: RemoteVisibility = RemoteVisibility.UNKNOWN
    is_nsfw: bool = False
    thumbnail_url: Optional[str] = None
    raw_data: Optional[dict] = None


@dataclass
class ProviderProfile:
    """Normalized user profile from a provider.

    Represents a user's public profile information.
    """

    external_id: str
    username: str

    # Optional fields
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    created_at: Optional[datetime] = None
    karma: int = 0
    is_verified: bool = False
    is_suspended: bool = False
    raw_data: Optional[dict] = None


@dataclass
class ProviderProfileItem:
    """Normalized profile item from a provider.

    Represents content created by a user (post, comment, image).
    """

    external_id: str
    item_type: ProfileItemType
    author_id: str

    # Optional fields
    title: Optional[str] = None
    body_text: Optional[str] = None
    url: Optional[str] = None
    created_at: Optional[datetime] = None
    location: Optional[str] = None
    score: int = 0
    remote_visibility: RemoteVisibility = RemoteVisibility.UNKNOWN
    attachment_url: Optional[str] = None
    raw_data: Optional[dict] = None


@dataclass
class SendMessageResult:
    """Result of sending a message through a provider.

    Contains the provider's message ID and send status.
    """

    external_message_id: str
    sent_at: datetime
    success: bool = True
    error_message: Optional[str] = None
    is_ambiguous: bool = False  # True if we don't know if message was sent


# =============================================================================
# PAGINATION
# =============================================================================


T = TypeVar("T")


@dataclass
class PaginatedResult(Generic[T]):
    """Paginated result wrapper.

    Wraps a list of items with cursor-based pagination information.
    """

    items: list[T]
    next_cursor: Optional[str]
    has_more: bool
    total: Optional[int] = None


# =============================================================================
# PROVIDER ADAPTER INTERFACE
# =============================================================================


class ProviderAdapter(ABC):
    """Abstract base class for provider adapters.

    All provider adapters must implement this interface to provide
    a consistent API for the core application.

    Methods:
        list_conversations: List user's conversations
        list_messages: List messages in a conversation
        browse_location: Browse posts in a location (e.g., subreddit)
        fetch_post: Fetch a single post by ID
        fetch_profile: Fetch a user's profile
        fetch_profile_items: Fetch a user's content (posts/comments/images)
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Return the unique provider identifier (e.g., 'reddit')."""
        ...

    @abstractmethod
    async def list_conversations(
        self,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> PaginatedResult[ProviderConversation]:
        """List the user's conversations.

        Args:
            cursor: Pagination cursor from previous request.
            limit: Maximum number of conversations to return.

        Returns:
            Paginated list of conversations.
        """
        ...

    @abstractmethod
    async def list_messages(
        self,
        conversation_id: str,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> PaginatedResult[ProviderMessage]:
        """List messages in a conversation.

        Args:
            conversation_id: The external conversation ID.
            cursor: Pagination cursor from previous request.
            limit: Maximum number of messages to return.

        Returns:
            Paginated list of messages.
        """
        ...

    @abstractmethod
    async def browse_location(
        self,
        location: str,
        cursor: Optional[str] = None,
        limit: int = 25,
    ) -> PaginatedResult[ProviderPost]:
        """Browse posts in a location (e.g., subreddit).

        Args:
            location: The location identifier (e.g., "r/programming").
            cursor: Pagination cursor from previous request.
            limit: Maximum number of posts to return.

        Returns:
            Paginated list of posts.
        """
        ...

    @abstractmethod
    async def fetch_post(self, post_id: str) -> Optional[ProviderPost]:
        """Fetch a single post by ID.

        Args:
            post_id: The external post ID.

        Returns:
            The post if found, None otherwise.
        """
        ...

    @abstractmethod
    async def fetch_profile(self, user_id: str) -> Optional[ProviderProfile]:
        """Fetch a user's profile.

        Args:
            user_id: The external user ID or username.

        Returns:
            The profile if found, None otherwise.
        """
        ...

    @abstractmethod
    async def fetch_profile_items(
        self,
        user_id: str,
        item_type: Optional[ProfileItemType] = None,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> PaginatedResult[ProviderProfileItem]:
        """Fetch a user's content items (posts/comments/images).

        Args:
            user_id: The external user ID or username.
            item_type: Optional filter by item type.
            cursor: Pagination cursor from previous request.
            limit: Maximum number of items to return.

        Returns:
            Paginated list of profile items.
        """
        ...

    @abstractmethod
    async def send_message(
        self,
        recipient_username: str,
        subject: str,
        body: str,
    ) -> "SendMessageResult":
        """Send a message to a user.

        Args:
            recipient_username: The recipient's username.
            subject: The message subject (may be ignored by some providers).
            body: The message body text.

        Returns:
            SendMessageResult with the provider's message ID.

        Note:
            This method should handle at-most-once semantics:
            - On clear success, return success=True
            - On clear failure (validation, etc.), return success=False, is_ambiguous=False
            - On ambiguous failure (timeout, etc.), return success=False, is_ambiguous=True
        """
        ...
