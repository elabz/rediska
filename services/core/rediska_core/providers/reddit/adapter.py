"""Reddit API adapter.

Implements the ProviderAdapter interface for Reddit, mapping Reddit's
API responses to normalized DTOs.

Usage:
    adapter = RedditAdapter(
        access_token="...",
        refresh_token="...",
        client_id="...",
        client_secret="...",
        user_agent="Rediska/1.0",
    )

    conversations = await adapter.list_conversations()
    messages = await adapter.list_messages(conversation_id)
    posts = await adapter.browse_location("r/programming")
"""

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx

logger = logging.getLogger(__name__)

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
    SendMessageResult,
)


class RedditAPIError(Exception):
    """Raised when Reddit API call fails."""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class RedditAdapter(ProviderAdapter):
    """Reddit provider adapter.

    Implements the ProviderAdapter interface for Reddit, providing
    normalized access to Reddit's messaging, posts, and user data.
    """

    # Reddit API endpoints
    BASE_URL = "https://oauth.reddit.com"
    TOKEN_URL = "https://www.reddit.com/api/v1/access_token"

    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        user_agent: str,
        on_token_refresh: Optional[Callable[[str], None]] = None,
    ):
        """Initialize the Reddit adapter.

        Args:
            access_token: OAuth access token.
            refresh_token: OAuth refresh token.
            client_id: Reddit app client ID.
            client_secret: Reddit app client secret.
            user_agent: User-Agent string for API requests.
            on_token_refresh: Optional callback when token is refreshed.
        """
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.on_token_refresh = on_token_refresh

    @property
    def provider_id(self) -> str:
        """Return the provider identifier."""
        return "reddit"

    def _get_headers(self) -> dict[str, str]:
        """Get headers for API requests."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": self.user_agent,
        }

    async def _refresh_access_token(self) -> None:
        """Refresh the access token using the refresh token."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                },
                auth=(self.client_id, self.client_secret),
                headers={"User-Agent": self.user_agent},
            )

        if response.status_code != 200:
            raise RedditAPIError("Failed to refresh token", response.status_code)

        data = response.json()
        self.access_token = data["access_token"]

        # Notify callback if set
        if self.on_token_refresh:
            self.on_token_refresh(self.access_token)

    async def _api_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        retry_on_401: bool = True,
    ) -> httpx.Response:
        """Make an API request with automatic token refresh.

        Args:
            method: HTTP method (GET, POST, etc.).
            endpoint: API endpoint path.
            params: Query parameters.
            retry_on_401: Whether to retry after refreshing token on 401.

        Returns:
            The HTTP response.
        """
        url = f"{self.BASE_URL}{endpoint}"

        async with httpx.AsyncClient() as client:
            if method == "GET":
                response = await client.get(
                    url, headers=self._get_headers(), params=params
                )
            else:
                response = await client.request(
                    method, url, headers=self._get_headers(), params=params
                )

        # Handle 401 by refreshing token and retrying
        if response.status_code == 401 and retry_on_401:
            await self._refresh_access_token()
            return await self._api_request(method, endpoint, params, retry_on_401=False)

        return response

    async def list_conversations(
        self,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> PaginatedResult[ProviderConversation]:
        """List the user's conversations (private messages).

        Reddit's inbox contains messages organized by threads (first_message_name),
        but we group by counterpart username to show all messages with a user
        in a single conversation.
        """
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["after"] = cursor

        response = await self._api_request("GET", "/message/inbox", params)

        if response.status_code != 200:
            return PaginatedResult(items=[], next_cursor=None, has_more=False)

        data = response.json()
        children = data.get("data", {}).get("children", [])
        after = data.get("data", {}).get("after")

        # Group messages into conversations BY USER PAIR
        # This merges all Reddit threads between the same two users
        # We store both users and let the sync service determine which is "us"
        conversations: dict[str, ProviderConversation] = {}
        user_pairs: dict[str, tuple[str, str]] = {}  # conv_id -> (author, dest)

        for child in children:
            if child.get("kind") != "t4":  # t4 = message
                continue

            msg_data = child.get("data", {})

            author = msg_data.get("author", "")
            dest = msg_data.get("dest", "")

            # Skip system/automated messages
            if not author or not dest:
                continue

            # Create a canonical key for this user pair (alphabetically sorted)
            # This ensures messages between A<->B always group together
            user_pair = tuple(sorted([author.lower(), dest.lower()]))
            conv_id = f"reddit:pair:{user_pair[0]}:{user_pair[1]}"

            msg_timestamp = self._parse_timestamp(msg_data.get("created_utc"))

            if conv_id not in conversations:
                # Store both users - sync service will determine the counterpart
                user_pairs[conv_id] = (author, dest)
                conversations[conv_id] = ProviderConversation(
                    external_id=conv_id,
                    counterpart_id=author,  # Temporary - sync service updates this
                    counterpart_username=author,  # Temporary - sync service updates this
                    subject=None,  # Multiple threads = no single subject
                    last_message_at=msg_timestamp,
                    is_unread=msg_data.get("new", False),
                    raw_data={"author": author, "dest": dest, "users": list(user_pair)},
                )
            else:
                # Update last_message_at if this message is newer
                existing = conversations[conv_id]
                if msg_timestamp and (existing.last_message_at is None or msg_timestamp > existing.last_message_at):
                    raw = existing.raw_data or {}
                    raw.update({"author": author, "dest": dest})
                    conversations[conv_id] = ProviderConversation(
                        external_id=conv_id,
                        counterpart_id=existing.counterpart_id,
                        counterpart_username=existing.counterpart_username,
                        subject=None,
                        last_message_at=msg_timestamp,
                        is_unread=existing.is_unread or msg_data.get("new", False),
                        raw_data=raw,
                    )

        return PaginatedResult(
            items=list(conversations.values()),
            next_cursor=after,
            has_more=after is not None,
        )

    async def list_messages(
        self,
        conversation_id: str,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> PaginatedResult[ProviderMessage]:
        """List messages in a conversation.

        The conversation_id is 'reddit:pair:{user1}:{user2}' (alphabetically sorted),
        so we fetch all messages between these two users.
        """
        # Extract user pair from the synthetic conversation ID
        # Format: "reddit:pair:{user1}:{user2}"
        if conversation_id.startswith("reddit:pair:"):
            parts = conversation_id[len("reddit:pair:"):].split(":")
            if len(parts) >= 2:
                user_pair = set([parts[0].lower(), parts[1].lower()])
            else:
                user_pair = set()
        else:
            # Fallback for legacy IDs
            user_pair = set()

        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["after"] = cursor

        response = await self._api_request("GET", "/message/inbox", params)

        if response.status_code != 200:
            return PaginatedResult(items=[], next_cursor=None, has_more=False)

        data = response.json()
        children = data.get("data", {}).get("children", [])
        after = data.get("data", {}).get("after")

        messages = []
        for child in children:
            if child.get("kind") != "t4":
                continue

            msg_data = child.get("data", {})
            author = (msg_data.get("author") or "").lower()
            dest = (msg_data.get("dest") or "").lower()

            # Include message if both author and dest are in our user pair
            msg_pair = set([author, dest])
            if msg_pair == user_pair:
                messages.append(self._map_message(msg_data, conversation_id))

        return PaginatedResult(
            items=messages,
            next_cursor=after,
            has_more=after is not None,
        )

    async def fetch_inbox_messages(
        self,
        cursor: Optional[str] = None,
        limit: int = 100,
        endpoint: str = "/message/inbox",
    ) -> PaginatedResult[dict]:
        """Fetch raw messages from inbox or sent folder.

        Args:
            cursor: Pagination cursor.
            limit: Max messages per page.
            endpoint: Either "/message/inbox" or "/message/sent".

        Returns raw message dictionaries instead of parsed objects,
        allowing the sync service to process them efficiently.
        """
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["after"] = cursor

        response = await self._api_request("GET", endpoint, params)

        if response.status_code != 200:
            return PaginatedResult(items=[], next_cursor=None, has_more=False)

        data = response.json()
        children = data.get("data", {}).get("children", [])
        after = data.get("data", {}).get("after")

        # Return raw message data dictionaries
        messages = []
        for child in children:
            if child.get("kind") != "t4":
                continue
            messages.append(child.get("data", {}))

        return PaginatedResult(
            items=messages,
            next_cursor=after,
            has_more=after is not None,
        )

    async def browse_location(
        self,
        location: str,
        cursor: Optional[str] = None,
        limit: int = 25,
        sort: str = "new",
    ) -> PaginatedResult[ProviderPost]:
        """Browse posts in a subreddit.

        Args:
            location: Subreddit name (with or without r/ prefix).
            cursor: Pagination cursor.
            limit: Maximum posts to return.
            sort: Sort order - 'new', 'hot', 'top', 'rising'.
        """
        # Normalize location
        if not location.startswith("r/"):
            location = f"r/{location}"

        # Validate sort parameter
        valid_sorts = {"new", "hot", "top", "rising"}
        if sort not in valid_sorts:
            sort = "new"

        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["after"] = cursor

        response = await self._api_request("GET", f"/{location}/{sort}", params)

        if response.status_code != 200:
            return PaginatedResult(items=[], next_cursor=None, has_more=False)

        data = response.json()
        children = data.get("data", {}).get("children", [])
        after = data.get("data", {}).get("after")

        posts = []
        for child in children:
            if child.get("kind") != "t3":  # t3 = link/post
                continue

            post_data = child.get("data", {})
            posts.append(self._map_post(post_data))

        return PaginatedResult(
            items=posts,
            next_cursor=after,
            has_more=after is not None,
        )

    async def fetch_post(self, post_id: str) -> Optional[ProviderPost]:
        """Fetch a single post by ID."""
        # Remove t3_ prefix if present
        if post_id.startswith("t3_"):
            post_id = post_id[3:]

        response = await self._api_request("GET", f"/comments/{post_id}")

        if response.status_code != 200:
            return None

        data = response.json()

        # Response is a list: [post_listing, comments_listing]
        if not data or not isinstance(data, list) or len(data) == 0:
            return None

        post_listing = data[0]
        children = post_listing.get("data", {}).get("children", [])

        if not children:
            return None

        post_data = children[0].get("data", {})
        return self._map_post(post_data)

    async def fetch_profile(self, user_id: str) -> Optional[ProviderProfile]:
        """Fetch a user's profile.

        Args:
            user_id: Username (not the t2_ ID).
        """
        response = await self._api_request("GET", f"/user/{user_id}/about")

        if response.status_code != 200:
            # Log the actual error from Reddit
            try:
                error_data = response.json()
                logger.error(
                    f"Reddit API error fetching profile for '{user_id}': "
                    f"status={response.status_code}, response={error_data}"
                )
            except Exception:
                logger.error(
                    f"Reddit API error fetching profile for '{user_id}': "
                    f"status={response.status_code}, body={response.text[:500]}"
                )
            return None

        data = response.json().get("data", {})
        return self._map_profile(data)

    async def fetch_profile_items(
        self,
        user_id: str,
        item_type: Optional[ProfileItemType] = None,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> PaginatedResult[ProviderProfileItem]:
        """Fetch a user's submitted content.

        Args:
            user_id: Username.
            item_type: Filter by type (POST or COMMENT).
            cursor: Pagination cursor.
            limit: Maximum items to return.
        """
        # Determine endpoint based on item_type
        if item_type == ProfileItemType.POST:
            endpoint = f"/user/{user_id}/submitted"
        elif item_type == ProfileItemType.COMMENT:
            endpoint = f"/user/{user_id}/comments"
        else:
            endpoint = f"/user/{user_id}/overview"

        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["after"] = cursor
        self.logger.info(f"Fetching profile items for {user_id} with params {params}")
        response = await self._api_request("GET", endpoint, params)

        if response.status_code != 200:
            return PaginatedResult(items=[], next_cursor=None, has_more=False)

        data = response.json()
        children = data.get("data", {}).get("children", [])
        after = data.get("data", {}).get("after")

        items = []
        for child in children:
            kind = child.get("kind")
            item_data = child.get("data", {})

            if kind == "t3":  # Post
                items.append(self._map_profile_item_post(item_data))
            elif kind == "t1":  # Comment
                items.append(self._map_profile_item_comment(item_data))

        return PaginatedResult(
            items=items,
            next_cursor=after,
            has_more=after is not None,
        )

    async def send_message(
        self,
        recipient_username: str,
        subject: str,
        body: str,
    ) -> SendMessageResult:
        """Send a private message to a Reddit user.

        Uses Reddit's /api/compose endpoint to send a new message.

        Args:
            recipient_username: The recipient's Reddit username.
            subject: The message subject.
            body: The message body text (markdown supported).

        Returns:
            SendMessageResult with success status and message ID if available.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.BASE_URL}/api/compose",
                    headers=self._get_headers(),
                    data={
                        "api_type": "json",
                        "to": recipient_username,
                        "subject": subject,
                        "text": body,
                    },
                )

            # Check for timeout or connection errors
            if response.status_code == 0:
                return SendMessageResult(
                    external_message_id="",
                    sent_at=datetime.now(timezone.utc),
                    success=False,
                    error_message="Connection failed",
                    is_ambiguous=True,  # Don't know if it was sent
                )

            # Parse response
            data = response.json()
            json_data = data.get("json", {})
            errors = json_data.get("errors", [])

            if errors:
                # Clear failure - we know the message wasn't sent
                error_msg = "; ".join([str(e) for e in errors])
                return SendMessageResult(
                    external_message_id="",
                    sent_at=datetime.now(timezone.utc),
                    success=False,
                    error_message=error_msg,
                    is_ambiguous=False,  # Clear failure
                )

            # Success - extract message ID if available
            # Reddit's compose endpoint doesn't always return the message ID
            # We use the current timestamp as a fallback identifier
            things = json_data.get("data", {}).get("things", [])
            msg_id = ""
            if things:
                msg_id = things[0].get("data", {}).get("id", "")

            return SendMessageResult(
                external_message_id=msg_id or f"sent_{int(datetime.now().timestamp())}",
                sent_at=datetime.now(timezone.utc),
                success=True,
            )

        except httpx.TimeoutException:
            # Timeout - ambiguous, don't know if message was sent
            return SendMessageResult(
                external_message_id="",
                sent_at=datetime.now(timezone.utc),
                success=False,
                error_message="Request timed out",
                is_ambiguous=True,
            )

        except httpx.HTTPStatusError as e:
            # HTTP error - could be ambiguous depending on status
            is_ambiguous = e.response.status_code >= 500  # Server errors are ambiguous
            return SendMessageResult(
                external_message_id="",
                sent_at=datetime.now(timezone.utc),
                success=False,
                error_message=f"HTTP {e.response.status_code}",
                is_ambiguous=is_ambiguous,
            )

        except Exception as e:
            # Unknown error - treat as ambiguous
            return SendMessageResult(
                external_message_id="",
                sent_at=datetime.now(timezone.utc),
                success=False,
                error_message=str(e),
                is_ambiguous=True,
            )

    # =========================================================================
    # MAPPING HELPERS
    # =========================================================================

    def _parse_timestamp(self, ts: Optional[float]) -> Optional[datetime]:
        """Parse a Reddit UTC timestamp."""
        if ts is None:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    def _map_message(self, data: dict, conversation_id: str) -> ProviderMessage:
        """Map Reddit message data to ProviderMessage."""
        return ProviderMessage(
            external_id=data.get("id", ""),
            conversation_id=conversation_id,
            direction=MessageDirection.IN,  # Will need context to determine direction
            body_text=data.get("body", ""),
            sent_at=self._parse_timestamp(data.get("created_utc")) or datetime.now(timezone.utc),
            sender_id=None,
            sender_username=data.get("author"),
            remote_visibility=RemoteVisibility.VISIBLE,
            raw_data=data,
        )

    def _map_post(self, data: dict) -> ProviderPost:
        """Map Reddit post data to ProviderPost."""
        author = data.get("author", "[deleted]")
        is_deleted = author == "[deleted]"

        visibility = RemoteVisibility.VISIBLE
        if is_deleted:
            visibility = RemoteVisibility.DELETED_BY_AUTHOR
        elif data.get("removed_by_category"):
            visibility = RemoteVisibility.REMOVED

        return ProviderPost(
            external_id=data.get("id", ""),
            author_id=data.get("author_fullname", ""),
            author_username=author,
            title=data.get("title", ""),
            url=data.get("url", ""),
            location=data.get("subreddit_name_prefixed", ""),
            body_text=data.get("selftext"),
            created_at=self._parse_timestamp(data.get("created_utc")),
            score=data.get("score", 0),
            num_comments=data.get("num_comments", 0),
            remote_visibility=visibility,
            is_nsfw=data.get("over_18", False),
            thumbnail_url=data.get("thumbnail") if data.get("thumbnail", "").startswith("http") else None,
            raw_data=data,
        )

    def _map_profile(self, data: dict) -> ProviderProfile:
        """Map Reddit user data to ProviderProfile."""
        subreddit = data.get("subreddit", {})

        return ProviderProfile(
            external_id=data.get("id", ""),
            username=data.get("name", ""),
            display_name=subreddit.get("display_name"),
            avatar_url=subreddit.get("icon_img"),
            bio=subreddit.get("public_description"),
            created_at=self._parse_timestamp(data.get("created_utc")),
            karma=data.get("link_karma", 0) + data.get("comment_karma", 0),
            is_verified=data.get("verified", False),
            is_suspended=data.get("is_suspended", False),
            raw_data=data,
        )

    def _map_profile_item_post(self, data: dict) -> ProviderProfileItem:
        """Map Reddit post to ProviderProfileItem."""
        author = data.get("author", "[deleted]")
        is_deleted = author == "[deleted]"

        visibility = RemoteVisibility.VISIBLE
        if is_deleted:
            visibility = RemoteVisibility.DELETED_BY_AUTHOR

        return ProviderProfileItem(
            external_id=data.get("id", ""),
            item_type=ProfileItemType.POST,
            author_id=data.get("author_fullname", ""),
            title=data.get("title"),
            body_text=data.get("selftext"),
            url=data.get("url"),
            created_at=self._parse_timestamp(data.get("created_utc")),
            location=data.get("subreddit_name_prefixed"),
            score=data.get("score", 0),
            remote_visibility=visibility,
            raw_data=data,
        )

    def _map_profile_item_comment(self, data: dict) -> ProviderProfileItem:
        """Map Reddit comment to ProviderProfileItem."""
        author = data.get("author", "[deleted]")
        is_deleted = author == "[deleted]"

        visibility = RemoteVisibility.VISIBLE
        if is_deleted:
            visibility = RemoteVisibility.DELETED_BY_AUTHOR

        return ProviderProfileItem(
            external_id=data.get("id", ""),
            item_type=ProfileItemType.COMMENT,
            author_id=data.get("author_fullname", ""),
            title=data.get("link_title"),  # Title of parent post
            body_text=data.get("body"),
            url=None,
            created_at=self._parse_timestamp(data.get("created_utc")),
            location=data.get("subreddit_name_prefixed"),
            score=data.get("score", 0),
            remote_visibility=visibility,
            raw_data=data,
        )
