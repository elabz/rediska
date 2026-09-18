"""Pydantic schemas for the source discovery API."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# =============================================================================
# SHARED
# =============================================================================


class LocationInfo(BaseModel):
    """Normalized provider location summary (``ProviderLocation``)."""

    name: str
    title: Optional[str] = None
    description: Optional[str] = None
    member_count: Optional[int] = None
    active_count: Optional[int] = None
    is_nsfw: bool = False
    created_at: Optional[datetime] = None


class TrialYield(BaseModel):
    """Yield report of a completed (or cancelled) trial."""

    posts_fetched: int = 0
    posts_recorded: int = 0
    skipped_empty: int = 0
    link_only_resolved: int = 0
    suitable: int = 0
    needs_review: int = 0
    not_recommended: int = 0
    skipped_prior_verdict: int = 0
    failed: int = 0
    top_failing_gate: Optional[str] = None
    top_failing_gate_count: int = 0
    gate_failures: dict[str, int] = Field(default_factory=dict)
    median_post_age_hours: Optional[float] = None


class SourceTrialResponse(BaseModel):
    id: int
    candidate_id: int
    watch_id: Optional[int] = None
    run_id: Optional[int] = None
    status: str
    sample_size: int
    posts_total: int
    progress: int
    yield_report: Optional[TrialYield] = None
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class SourceCandidateResponse(BaseModel):
    id: int
    provider_id: str
    kind: str
    name: str
    origin: str
    status: str
    lift: Optional[float] = None
    evidence_count: int
    evidence: dict[str, Any] = Field(default_factory=dict)
    snoozed_until: Optional[datetime] = None
    location_info: Optional[LocationInfo] = None
    location_unavailable: bool = False
    watch_id: Optional[int] = None
    latest_trial: Optional[SourceTrialResponse] = None
    computed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class SourceCandidateListResponse(BaseModel):
    items: list[SourceCandidateResponse]
    total: int
    next_cursor: Optional[str] = None
    running_trial: Optional[SourceTrialResponse] = None


# =============================================================================
# REQUESTS
# =============================================================================


class SnoozeRequest(BaseModel):
    until: datetime = Field(..., description="Hide the candidate until this time (UTC)")


class AcceptRequest(BaseModel):
    """Settings for the scout watch created from a candidate."""

    search_query: Optional[str] = None
    sort_by: str = "new"
    time_filter: str = "day"
    identity_id: Optional[int] = None
    auto_analyze: bool = True
    min_confidence: float = Field(0.7, ge=0.0, le=1.0)


class AcceptResponse(BaseModel):
    candidate: SourceCandidateResponse
    watch_id: int
    converted_trial_watch: bool


class ManualCandidateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Location, e.g. 'r/foo'")
    location_info: Optional[LocationInfo] = None


class TrialRequest(BaseModel):
    sample_size: Optional[int] = Field(None, ge=1, le=50)
    identity_id: Optional[int] = None


class LocationSearchResult(LocationInfo):
    watched: bool = False
    candidate_id: Optional[int] = None
    candidate_status: Optional[str] = None


class LocationSearchResponse(BaseModel):
    query: str
    results: list[LocationSearchResult]
