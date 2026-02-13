"""Profile items API schemas for batch ingestion."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class BrowsePostForIngest(BaseModel):
    """A single post from browse/scout results to ingest as a profile_item."""

    provider_id: str = Field(..., description="Provider ID (e.g., 'reddit')")
    external_post_id: str = Field(..., description="Provider's post ID")
    author_username: str = Field(..., description="Post author's username")
    title: Optional[str] = Field(default=None, description="Post title")
    body_text: Optional[str] = Field(default=None, description="Post body text")
    source_location: Optional[str] = Field(default=None, description="Subreddit / channel")
    post_created_at: Optional[datetime] = Field(default=None, description="When the post was created")


class IngestBrowsePostsRequest(BaseModel):
    """Request to ingest browse/scout posts for known authors."""

    posts: list[BrowsePostForIngest] = Field(
        ...,
        description="Posts to ingest",
        max_length=100,
    )


class IngestBrowsePostsResponse(BaseModel):
    """Response from batch post ingestion."""

    ingested_count: int = Field(..., description="Number of posts ingested as profile_items")
    new_items_count: int = Field(..., description="Number of newly created profile_items (vs updated)")
    known_authors: list[str] = Field(
        default_factory=list,
        description="Usernames of authors that already exist in external_accounts",
    )
