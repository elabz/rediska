"""Sources API routes for browsing provider locations.

Provides endpoints for:
- GET /sources/{provider_id}/locations/{location}/posts - Browse posts from a location
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from rediska_core.api.deps import CurrentUser, get_db
from rediska_core.api.schemas.sources import (
    BrowsePost,
    BrowsePostsResponse,
)
from rediska_core.domain.services.browse import BrowseError, BrowseService, ProviderClient

router = APIRouter(prefix="/sources", tags=["sources"])


# =============================================================================
# PROVIDER CLIENT FACTORY
# =============================================================================


# Global provider client registry (can be overridden in tests)
_provider_clients: dict[str, ProviderClient] = {}


def register_provider_client(provider_id: str, client: ProviderClient) -> None:
    """Register a provider client for a given provider."""
    _provider_clients[provider_id] = client


def get_provider_client(provider_id: str) -> Optional[ProviderClient]:
    """Get a provider client for the given provider.

    Args:
        provider_id: The provider ID.

    Returns:
        A provider client instance or None.
    """
    return _provider_clients.get(provider_id)


def get_browse_service(
    db: Session = Depends(get_db),
) -> BrowseService:
    """Get the browse service."""
    return BrowseService(db=db, provider_client=None)


BrowseServiceDep = Annotated[BrowseService, Depends(get_browse_service)]


# =============================================================================
# BROWSE POSTS
# =============================================================================


@router.get(
    "/{provider_id}/locations/{location:path}/posts",
    response_model=BrowsePostsResponse,
    summary="Browse posts from location",
    description="Browse posts from a provider location (e.g., subreddit). "
                "Supports pagination with cursors and sorting options.",
)
async def browse_posts(
    provider_id: str,
    location: str,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    sort: str = Query(default="hot", description="Sort order ('hot', 'new', 'top', 'rising')"),
    limit: int = Query(default=25, ge=1, le=100, description="Maximum posts to return"),
    cursor: Optional[str] = Query(default=None, description="Cursor for pagination"),
):
    """Browse posts from a provider location.

    Fetches posts from the specified location (e.g., subreddit)
    and returns them in a normalized format.
    """
    # Get provider client
    provider_client = get_provider_client(provider_id)

    # Create browse service with provider client
    browse_service = BrowseService(db=db, provider_client=provider_client)

    try:
        result = browse_service.browse_location(
            provider_id=provider_id,
            location=location,
            sort=sort,
            limit=limit,
            cursor=cursor,
        )

        # Convert to response schema
        posts = [BrowsePost(**post) for post in result["posts"]]

        return BrowsePostsResponse(
            posts=posts,
            cursor=result.get("cursor"),
            source_location=location,
            provider_id=provider_id,
        )

    except BrowseError as e:
        error_msg = str(e)
        if "Unknown provider" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": error_msg},
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": error_msg},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": f"Failed to browse location: {e}"},
        )
