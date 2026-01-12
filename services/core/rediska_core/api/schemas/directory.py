"""Directory API schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# =============================================================================
# DIRECTORY ENTRY SCHEMA
# =============================================================================


class DirectoryEntryResponse(BaseModel):
    """Response schema for a directory entry."""

    id: int = Field(..., description="Account ID")
    provider_id: str = Field(..., description="Provider ID")
    external_username: str = Field(..., description="External username")
    external_user_id: Optional[str] = Field(default=None, description="External user ID")
    remote_status: str = Field(..., description="Remote account status")

    # State fields
    analysis_state: str = Field(..., description="Analysis state")
    contact_state: str = Field(..., description="Contact state")
    engagement_state: str = Field(..., description="Engagement state")

    # Timestamps
    first_analyzed_at: Optional[datetime] = Field(
        default=None, description="When first analyzed"
    )
    first_contacted_at: Optional[datetime] = Field(
        default=None, description="When first contacted"
    )
    first_inbound_after_contact_at: Optional[datetime] = Field(
        default=None, description="When first response received after contact"
    )
    created_at: datetime = Field(..., description="When account was created")

    # Related data
    latest_summary: Optional[str] = Field(
        default=None, description="Latest profile summary"
    )
    lead_count: int = Field(default=0, description="Number of leads for this account")


# =============================================================================
# DIRECTORY LIST RESPONSE
# =============================================================================


class DirectoryListResponse(BaseModel):
    """Response schema for directory listing."""

    entries: list[DirectoryEntryResponse] = Field(
        ..., description="List of directory entries"
    )
    total: int = Field(..., description="Total count for pagination")
    directory_type: str = Field(..., description="Type of directory (analyzed/contacted/engaged)")


# =============================================================================
# DIRECTORY COUNTS RESPONSE
# =============================================================================


class DirectoryCountsResponse(BaseModel):
    """Response schema for directory counts."""

    analyzed: int = Field(..., description="Count of analyzed accounts")
    contacted: int = Field(..., description="Count of contacted accounts")
    engaged: int = Field(..., description="Count of engaged accounts")
