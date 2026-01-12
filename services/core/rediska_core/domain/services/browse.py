"""Browse service for fetching posts from provider locations.

This service provides:
1. Browsing posts from provider locations (e.g., subreddits)
2. Pagination with cursors
3. Post data normalization to common schema
4. Sort options (hot, new, top)

Usage:
    service = BrowseService(db=session, provider_client=client)

    # Browse a subreddit
    result = service.browse_location(
        provider_id="reddit",
        location="r/programming",
        sort="hot",
        limit=25,
    )

    # Get next page
    result = service.browse_location(
        provider_id="reddit",
        location="r/programming",
        cursor=result["cursor"],
    )
"""

from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from sqlalchemy.orm import Session

from rediska_core.domain.models import Provider


# =============================================================================
# EXCEPTIONS
# =============================================================================


class BrowseError(Exception):
    """Exception raised for browse errors."""

    pass


# =============================================================================
# PROVIDER CLIENT PROTOCOL
# =============================================================================


class ProviderClient(Protocol):
    """Protocol for provider client interface."""

    def browse_location(
        self,
        location: str,
        sort: str = "hot",
        limit: int = 25,
        after: Optional[str] = None,
    ) -> dict[str, Any]:
        """Browse posts from a location.

        Args:
            location: The location to browse (e.g., 'r/programming').
            sort: Sort order ('hot', 'new', 'top').
            limit: Maximum posts to return.
            after: Cursor for pagination.

        Returns:
            Dict with 'posts' and 'after' cursor.
        """
        ...


# =============================================================================
# CONSTANTS
# =============================================================================


DEFAULT_LIMIT = 25
MAX_LIMIT = 100
VALID_SORTS = {"hot", "new", "top", "rising"}


# =============================================================================
# SERVICE
# =============================================================================


class BrowseService:
    """Service for browsing posts from provider locations.

    Fetches posts from a provider location and normalizes them
    to a common schema for the application.
    """

    def __init__(
        self,
        db: Session,
        provider_client: Optional[ProviderClient] = None,
    ):
        """Initialize the browse service.

        Args:
            db: SQLAlchemy database session.
            provider_client: Client for provider API calls.
        """
        self.db = db
        self.provider_client = provider_client

    # =========================================================================
    # BROWSE LOCATION
    # =========================================================================

    def browse_location(
        self,
        provider_id: str,
        location: str,
        sort: str = "hot",
        limit: int = DEFAULT_LIMIT,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        """Browse posts from a provider location.

        Args:
            provider_id: The provider ID (e.g., 'reddit').
            location: The location to browse (e.g., 'r/programming').
            sort: Sort order ('hot', 'new', 'top').
            limit: Maximum posts to return.
            cursor: Cursor for pagination.

        Returns:
            Dict with 'posts' list and 'cursor' for next page.

        Raises:
            BrowseError: If browsing fails.
        """
        # Validate provider
        provider = (
            self.db.query(Provider)
            .filter(Provider.provider_id == provider_id)
            .first()
        )
        if not provider:
            raise BrowseError(f"Unknown provider: {provider_id}")

        if not self.provider_client:
            raise BrowseError("No provider client configured")

        # Enforce limits
        limit = min(limit, MAX_LIMIT)

        try:
            # Fetch posts from provider
            result = self.provider_client.browse_location(
                location=location,
                sort=sort,
                limit=limit,
                after=cursor,
            )

            # Normalize posts
            normalized_posts = [
                self._normalize_post(post, provider_id, location)
                for post in result.get("posts", [])
            ]

            return {
                "posts": normalized_posts,
                "cursor": result.get("after"),
            }

        except BrowseError:
            raise
        except Exception as e:
            raise BrowseError(f"Failed to browse {location}: {e}")

    # =========================================================================
    # POST NORMALIZATION
    # =========================================================================

    def _normalize_post(
        self,
        post: dict[str, Any],
        provider_id: str,
        location: str,
    ) -> dict[str, Any]:
        """Normalize a post from provider format to common schema.

        Args:
            post: Raw post data from provider.
            provider_id: The provider ID.
            location: The source location.

        Returns:
            Normalized post dict.
        """
        # Convert Unix timestamp to ISO format if present
        created_at = None
        if "created_utc" in post:
            created_at = datetime.fromtimestamp(
                post["created_utc"],
                tz=timezone.utc,
            ).isoformat()
        elif "created_at" in post:
            created_at = post["created_at"]

        return {
            "provider_id": provider_id,
            "source_location": location,
            "external_post_id": post.get("id", ""),
            "title": post.get("title", ""),
            "body_text": post.get("body", post.get("selftext", "")),
            "author_username": post.get("author", ""),
            "author_external_id": post.get("author_id", post.get("author_fullname", "")),
            "post_url": post.get("url", post.get("permalink", "")),
            "post_created_at": created_at,
            "score": post.get("score", 0),
            "num_comments": post.get("num_comments", 0),
        }


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "BrowseService",
    "BrowseError",
    "ProviderClient",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
]
