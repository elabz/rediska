"""Pydantic schemas for the contact ban list API."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class BanEntryResponse(BaseModel):
    """One `do_not_contact` row, with the author's account and leads if known."""

    id: int
    provider_id: str
    username: str
    reason: Optional[str] = None
    notes: Optional[str] = None
    source: str
    status: str
    cluster_id: Optional[int] = None
    created_by: Optional[str] = None
    created_at: datetime
    lifted_at: Optional[datetime] = None
    account_id: Optional[int] = None
    lead_ids: list[int] = Field(default_factory=list)


class BanListResponse(BaseModel):
    items: list[BanEntryResponse]
    next_cursor: Optional[str] = None


class BanStatusResponse(BaseModel):
    """Ban state of one username (entry is the active ban, else the latest row)."""

    banned: bool
    entry: Optional[BanEntryResponse] = None


class BanCreateRequest(BaseModel):
    provider_id: str = "reddit"
    username: str = Field(..., min_length=1, max_length=128)
    reason: str = Field(..., min_length=1, max_length=255)
    notes: Optional[str] = Field(default=None, max_length=4000)


class BanCreateResponse(BaseModel):
    entry: BanEntryResponse
    created: bool
    reactivated: bool
    leads_withdrawn: list[int] = Field(default_factory=list)


class BanLiftRequest(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=4000)


class BanLiftResponse(BaseModel):
    entry: BanEntryResponse
    leads_restored: list[int] = Field(default_factory=list)


class BanBulkRequest(BaseModel):
    """Ban every author of a copy cluster (or an explicit list) as one batch."""

    provider_id: str = "reddit"
    cluster_id: Optional[int] = None
    usernames: Optional[list[str]] = None
    reason: str = Field(default="copy_ring", min_length=1, max_length=255)
    notes: Optional[str] = Field(default=None, max_length=4000)
    exclude_usernames: list[str] = Field(default_factory=list)


class BanBulkResponse(BaseModel):
    cluster_id: Optional[int] = None
    banned: list[BanCreateResponse]


class SuggestionAuthor(BaseModel):
    username: str
    account_id: Optional[int] = None
    remote_status: Optional[str] = None
    first_posted_at: Optional[datetime] = None
    post_count: int = 0
    banned: bool = False
    dismissed: bool = False
    earliest: bool = False


class BanSuggestion(BaseModel):
    """A ring cluster with at least one author not yet banned or dismissed."""

    cluster_id: int
    kind: str
    authors: list[SuggestionAuthor]
    suggested_usernames: list[str]


class BanSuggestionsResponse(BaseModel):
    # False when copy detection (post-fingerprint-dedupe) is not installed.
    available: bool
    items: list[BanSuggestion]


class DismissSuggestionRequest(BaseModel):
    cluster_id: int
    username: str = Field(..., min_length=1, max_length=128)
