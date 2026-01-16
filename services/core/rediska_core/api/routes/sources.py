"""Sources API routes for browsing provider locations.

Provides endpoints for:
- GET /sources/{provider_id}/locations/{location}/posts - Browse posts from a location
"""

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from rediska_core.api.deps import CurrentUser, get_db
from rediska_core.api.schemas.sources import (
    BrowsePost,
    BrowsePostsResponse,
)
from rediska_core.config import get_settings
from rediska_core.domain.models import Identity, Provider
from rediska_core.domain.services.credentials import CredentialsService
from rediska_core.infrastructure.crypto import CryptoService
from rediska_core.providers.reddit.adapter import RedditAdapter

router = APIRouter(prefix="/sources", tags=["sources"])


# =============================================================================
# BROWSE POSTS
# =============================================================================


@router.get(
    "/{provider_id}/locations/{location:path}/posts",
    response_model=BrowsePostsResponse,
    summary="Browse or search posts from location",
    description="Browse or search posts from a provider location (e.g., subreddit). "
                "Supports pagination with cursors, sorting options, and Reddit search syntax.",
)
async def browse_posts(
    provider_id: str,
    location: str,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    query: Optional[str] = Query(default=None, alias="q", description="Search query (supports Reddit syntax: AND, OR, parentheses)"),
    sort: str = Query(default="hot", description="Sort order ('hot', 'new', 'top', 'rising', 'controversial', 'relevance')"),
    time_filter: Optional[str] = Query(default=None, alias="t", description="Time filter for 'top', 'controversial', and search ('hour', 'day', 'week', 'month', 'year', 'all')"),
    limit: int = Query(default=25, ge=1, le=100, description="Maximum posts to return"),
    cursor: Optional[str] = Query(default=None, description="Cursor for pagination"),
    identity_id: Optional[int] = Query(default=None, description="Identity to use for API access"),
):
    """Browse posts from a provider location.

    Fetches posts from the specified location (e.g., subreddit)
    and returns them in a normalized format.
    """
    settings = get_settings()

    # Validate provider
    provider = db.query(Provider).filter(Provider.provider_id == provider_id).first()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": f"Unknown provider: {provider_id}"},
        )

    # Only Reddit is supported for now
    if provider_id != "reddit":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": f"Provider '{provider_id}' does not support browsing"},
        )

    # Get identity with credentials
    if identity_id:
        identity = db.query(Identity).filter_by(id=identity_id, is_active=True).first()
    else:
        identity = db.query(Identity).filter_by(is_active=True).first()

    if not identity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "No active identity found. Please set up an identity first."},
        )

    # Get credentials
    if not settings.encryption_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Encryption key not configured"},
        )
    crypto = CryptoService(settings.encryption_key)
    credentials_service = CredentialsService(db=db, crypto=crypto)
    credential = credentials_service.get_credential_decrypted(
        provider_id="reddit",
        identity_id=identity.id,
        credential_type="oauth_tokens",
    )

    if not credential:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "No Reddit credentials found. Please connect your Reddit account."},
        )

    try:
        tokens = json.loads(credential)

        # Create token refresh callback
        def on_token_refresh(new_access_token: str) -> None:
            tokens["access_token"] = new_access_token
            credentials_service.store_credential(
                provider_id="reddit",
                identity_id=identity.id,
                credential_type="oauth_tokens",
                secret=json.dumps(tokens),
            )

        # Create Reddit adapter
        adapter = RedditAdapter(
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            client_id=settings.provider_reddit_client_id,
            client_secret=settings.provider_reddit_client_secret,
            user_agent=settings.provider_reddit_user_agent,
            on_token_refresh=on_token_refresh,
        )

        # Fetch posts from Reddit (browse or search)
        result = await adapter.browse_location(
            location=location,
            cursor=cursor,
            limit=limit,
            sort=sort,
            time_filter=time_filter,
            query=query,
        )

        # Convert to response schema
        posts = []
        for post in result.items:
            # Convert timestamp
            created_at = None
            if post.created_at:
                created_at = post.created_at.isoformat()

            posts.append(BrowsePost(
                provider_id=provider_id,
                source_location=location,
                external_post_id=post.external_id,
                title=post.title or "",
                body_text=post.body_text or "",
                author_username=post.author_username or "",
                author_external_id=post.author_id,
                post_url=post.url or "",
                post_created_at=created_at,
                score=post.score or 0,
                num_comments=post.num_comments or 0,
            ))

        return BrowsePostsResponse(
            posts=posts,
            cursor=result.next_cursor,
            source_location=location,
            provider_id=provider_id,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": f"Failed to browse location: {e}"},
        )
