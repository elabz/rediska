"""Leads API schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# =============================================================================
# SAVE LEAD SCHEMAS
# =============================================================================


class SaveLeadRequest(BaseModel):
    """Request schema for saving a post as a lead."""

    provider_id: str = Field(..., description="Provider ID (e.g., 'reddit')")
    source_location: str = Field(..., description="Source location (e.g., 'r/programming')")
    external_post_id: str = Field(..., description="Provider's post ID")
    post_url: str = Field(..., description="URL to the post")
    title: Optional[str] = Field(default=None, description="Post title")
    body_text: Optional[str] = Field(default=None, description="Post body text")
    author_username: Optional[str] = Field(default=None, description="Author's username")
    author_external_id: Optional[str] = Field(default=None, description="Author's external ID")
    post_created_at: Optional[datetime] = Field(default=None, description="When the post was created")


class AuthorInfo(BaseModel):
    """Author information from analysis."""

    username: str = Field(..., description="Author's username")
    account_created_at: Optional[datetime] = Field(default=None, description="When the account was created")
    karma: Optional[int] = Field(default=None, description="Total karma")
    post_count: Optional[int] = Field(default=None, description="Number of posts analyzed")
    comment_count: Optional[int] = Field(default=None, description="Number of comments analyzed")
    analysis_state: Optional[str] = Field(default=None, description="Analysis state")
    bio: Optional[str] = Field(default=None, description="User bio")
    is_verified: Optional[bool] = Field(default=None, description="Whether user is verified")
    is_suspended: Optional[bool] = Field(default=None, description="Whether user is suspended")


class LeadResponse(BaseModel):
    """Response schema for a lead."""

    id: int = Field(..., description="Lead ID")
    provider_id: str = Field(..., description="Provider ID")
    source_location: str = Field(..., description="Source location")
    external_post_id: str = Field(..., description="External post ID")
    post_url: str = Field(..., description="URL to the post")
    title: Optional[str] = Field(default=None, description="Post title")
    body_text: Optional[str] = Field(default=None, description="Post body text")
    author_account_id: Optional[int] = Field(default=None, description="Author account ID")
    author_username: Optional[str] = Field(default=None, description="Author's username")
    author_info: Optional[AuthorInfo] = Field(default=None, description="Detailed author info from analysis")
    status: str = Field(..., description="Lead status")
    score: Optional[int] = Field(default=None, description="Lead score")
    lead_source: Optional[str] = Field(default=None, description="How the lead was created ('manual' or 'scout_watch')")
    post_created_at: Optional[datetime] = Field(default=None, description="When the post was created")
    created_at: datetime = Field(..., description="When the lead was saved")

    # Analysis fields
    latest_analysis_id: Optional[int] = Field(default=None, description="ID of the latest analysis")
    analysis_recommendation: Optional[str] = Field(default=None, description="Latest analysis recommendation")
    analysis_confidence: Optional[float] = Field(default=None, description="Latest analysis confidence score")

    class Config:
        from_attributes = True


# =============================================================================
# LIST LEADS SCHEMAS
# =============================================================================


class ListLeadsRequest(BaseModel):
    """Query parameters for listing leads."""

    provider_id: Optional[str] = Field(default=None, description="Filter by provider")
    source_location: Optional[str] = Field(default=None, description="Filter by source location")
    status: Optional[str] = Field(default=None, description="Filter by status")
    offset: int = Field(default=0, ge=0, description="Pagination offset")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum results")


class ListLeadsResponse(BaseModel):
    """Response schema for listing leads."""

    leads: list[LeadResponse] = Field(..., description="List of leads")
    total: int = Field(..., description="Total count (for pagination)")


# =============================================================================
# UPDATE STATUS SCHEMAS
# =============================================================================


class UpdateLeadStatusRequest(BaseModel):
    """Request schema for updating lead status."""

    status: str = Field(
        ...,
        description="New status ('new', 'saved', 'ignored', 'contact_queued', 'contacted')",
    )


# =============================================================================
# ANALYZE LEAD SCHEMAS
# =============================================================================


class AnalyzeLeadResponse(BaseModel):
    """Response schema for analyzing a lead."""

    lead_id: int = Field(..., description="Lead ID that was analyzed")
    account_id: int = Field(..., description="Author account ID")
    profile_snapshot_id: int = Field(..., description="Created profile snapshot ID")
    profile_items_count: int = Field(..., description="Number of profile items fetched")
    indexed_count: int = Field(..., description="Number of documents indexed")
    embedded_count: int = Field(..., description="Number of embeddings generated")
    success: bool = Field(..., description="Whether analysis completed successfully")
    error: Optional[str] = Field(default=None, description="Error message if failed")
