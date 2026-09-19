"""Schemas for post copy detection (copy clusters)."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

CopyDecision = Literal["confirmed_ring", "same_person", "coincidence"]


class CopyInfo(BaseModel):
    """The ``copy`` field carried by lead, scout post and needs-review read models."""

    cluster_id: int
    kind: str = Field(description="Effective kind: the human decision, else the computed kind")
    computed_kind: str
    decision: Optional[str] = None
    author_count: int
    handled: bool = Field(
        default=False, description="Spam ring handled automatically (skipped + hidden)"
    )
    earliest_other_posted_at: Optional[datetime] = None


class CopyClusterSummary(BaseModel):
    id: int
    provider_id: str
    kind: str = Field(description="Effective kind")
    computed_kind: str
    decision: Optional[str] = None
    decision_notes: Optional[str] = None
    decided_at: Optional[datetime] = None
    author_count: int
    member_count: int
    avg_char_len: int = 0
    handled: bool = False
    first_posted_at: Optional[datetime] = None
    last_posted_at: Optional[datetime] = None
    created_at: datetime


class CopyClusterListResponse(BaseModel):
    items: list[CopyClusterSummary]
    next_cursor: Optional[str] = None


class CopyClusterMemberResponse(BaseModel):
    member_id: int
    fingerprint_id: int
    external_post_id: str
    author_username: Optional[str] = None
    account_id: Optional[int] = None
    remote_status: Optional[str] = None
    posted_at: Optional[datetime] = None
    first_seen_at: datetime
    location: Optional[str] = None
    source: str
    char_len: int
    similarity: Optional[float] = None
    repost_of_id: Optional[int] = None
    lead_id: Optional[int] = None
    lead_status: Optional[str] = None
    scout_post_id: Optional[int] = None
    scout_watch_id: Optional[int] = None
    analysis_id: Optional[int] = None
    recommendation: Optional[str] = None
    human_verdict: Optional[str] = None
    ban_id: Optional[int] = None
    ban_status: Optional[str] = None


class CopyClusterDetailResponse(BaseModel):
    cluster: CopyClusterSummary
    members: list[CopyClusterMemberResponse]


class CopyClusterDecisionRequest(BaseModel):
    decision: Optional[CopyDecision] = Field(
        description="confirmed_ring / same_person / coincidence; null clears the decision"
    )
    notes: Optional[str] = Field(default=None, max_length=2000)
