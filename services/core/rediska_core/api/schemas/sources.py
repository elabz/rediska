"""Sources API schemas for browsing provider locations."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# =============================================================================
# BROWSE POSTS SCHEMAS
# =============================================================================


class BrowsePostsQuery(BaseModel):
    """Query parameters for browsing posts."""

    sort: str = Field(
        default="hot",
        description="Sort order ('hot', 'new', 'top', 'rising')",
    )
    limit: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Maximum posts to return",
    )
    cursor: Optional[str] = Field(
        default=None,
        description="Cursor for pagination",
    )


class BrowsePost(BaseModel):
    """A post from browsing a location."""

    provider_id: str = Field(..., description="Provider ID")
    source_location: str = Field(..., description="Source location")
    external_post_id: str = Field(..., description="External post ID")
    title: str = Field(..., description="Post title")
    body_text: str = Field(default="", description="Post body text")
    author_username: str = Field(default="", description="Author's username")
    author_external_id: Optional[str] = Field(default=None, description="Author's external ID")
    post_url: str = Field(..., description="URL to the post")
    post_created_at: Optional[str] = Field(default=None, description="When the post was created (ISO format)")
    score: int = Field(default=0, description="Post score/upvotes")
    num_comments: int = Field(default=0, description="Number of comments")


class BrowsePostsResponse(BaseModel):
    """Response schema for browsing posts."""

    posts: list[BrowsePost] = Field(..., description="List of posts")
    cursor: Optional[str] = Field(
        default=None,
        description="Cursor for next page (null if no more pages)",
    )
    source_location: str = Field(..., description="The location that was browsed")
    provider_id: str = Field(..., description="The provider ID")
