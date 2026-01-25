"""Pydantic schemas for Scout Watch API."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# =============================================================================
# REQUEST SCHEMAS
# =============================================================================


class ScoutWatchCreate(BaseModel):
    """Request schema for creating a scout watch."""

    source_location: str = Field(..., description="Location to monitor (e.g., 'r/r4r')")
    search_query: Optional[str] = Field(None, description="Reddit search query")
    sort_by: str = Field("new", description="Sort order for posts")
    time_filter: str = Field("day", description="Time filter for search")
    identity_id: Optional[int] = Field(None, description="Identity to use for API calls")
    auto_analyze: bool = Field(True, description="Whether to auto-analyze posts")
    min_confidence: float = Field(0.7, ge=0.0, le=1.0, description="Minimum confidence for lead creation")


class ScoutWatchUpdate(BaseModel):
    """Request schema for updating a scout watch."""

    search_query: Optional[str] = Field(None, description="Reddit search query")
    sort_by: Optional[str] = Field(None, description="Sort order for posts")
    time_filter: Optional[str] = Field(None, description="Time filter for search")
    identity_id: Optional[int] = Field(None, description="Identity to use for API calls")
    is_active: Optional[bool] = Field(None, description="Whether the watch is active")
    auto_analyze: Optional[bool] = Field(None, description="Whether to auto-analyze posts")
    min_confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Minimum confidence")


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================


class ScoutWatchResponse(BaseModel):
    """Response schema for a scout watch."""

    id: int
    provider_id: str
    source_location: str
    search_query: Optional[str]
    sort_by: str
    time_filter: str
    identity_id: Optional[int]
    is_active: bool
    auto_analyze: bool
    min_confidence: float
    total_posts_seen: int
    total_matches: int
    total_leads_created: int
    last_run_at: Optional[datetime]
    last_match_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ScoutWatchListResponse(BaseModel):
    """Response schema for list of scout watches."""

    watches: list[ScoutWatchResponse]


class ScoutWatchRunResponse(BaseModel):
    """Response schema for a scout watch run."""

    id: int
    watch_id: int
    started_at: datetime
    completed_at: Optional[datetime]
    status: str
    posts_fetched: int
    posts_new: int
    posts_analyzed: int
    leads_created: int
    error_message: Optional[str]
    search_url: Optional[str] = None

    class Config:
        from_attributes = True


class ScoutWatchRunListResponse(BaseModel):
    """Response schema for list of scout watch runs with pagination."""

    runs: list[ScoutWatchRunResponse]
    total: int = 0
    offset: int = 0
    limit: int = 20


class ScoutWatchRunTriggerResponse(BaseModel):
    """Response schema for triggering a manual run."""

    run_id: int
    status: str
    message: str


class ScoutWatchPostResponse(BaseModel):
    """Response schema for a scout watch post."""

    id: int
    watch_id: int
    external_post_id: str
    post_title: Optional[str] = None
    post_author: Optional[str] = None
    first_seen_at: datetime
    run_id: Optional[int]

    # Profile data (from analysis pipeline)
    profile_fetched_at: Optional[datetime] = None
    user_interests: Optional[str] = None
    user_character: Optional[str] = None

    # Analysis result
    analysis_status: str
    analysis_id: Optional[int] = None
    analysis_recommendation: Optional[str] = None
    analysis_confidence: Optional[float] = None
    analysis_reasoning: Optional[str] = None

    # Full analysis dimension outputs (when analysis_id is present)
    analysis_dimensions: Optional[dict] = None

    # Lead creation
    lead_id: Optional[int] = None

    class Config:
        from_attributes = True


class ScoutWatchRunDetailResponse(BaseModel):
    """Response schema for detailed scout watch run with posts."""

    run: ScoutWatchRunResponse
    posts: list[ScoutWatchPostResponse]


class ScoutWatchPostReanalyzeResponse(BaseModel):
    """Response schema for re-analyze post request."""

    post_id: int
    status: str
    message: str


class ScoutWatchPostAddToLeadsResponse(BaseModel):
    """Response schema for adding a post to leads."""

    post_id: int
    lead_id: int
    message: str


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "ScoutWatchCreate",
    "ScoutWatchUpdate",
    "ScoutWatchResponse",
    "ScoutWatchListResponse",
    "ScoutWatchRunResponse",
    "ScoutWatchRunListResponse",
    "ScoutWatchRunTriggerResponse",
    "ScoutWatchPostResponse",
    "ScoutWatchRunDetailResponse",
    "ScoutWatchPostReanalyzeResponse",
    "ScoutWatchPostAddToLeadsResponse",
]
