"""Search API schemas."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Request schema for search endpoint."""

    query: str = Field(..., min_length=0, description="Search query string")
    mode: str = Field(
        default="hybrid",
        description="Search mode: 'hybrid', 'text', or 'vector'",
    )
    provider_id: Optional[str] = Field(
        default=None,
        description="Filter by provider ID",
    )
    identity_id: Optional[int] = Field(
        default=None,
        description="Filter by identity ID",
    )
    doc_types: Optional[list[str]] = Field(
        default=None,
        description="Filter by document types (message, conversation, lead_post, profile)",
    )
    exclude_visibility: Optional[list[str]] = Field(
        default=None,
        description="Visibility values to exclude (e.g., 'removed', 'deleted_by_author')",
    )
    include_deleted: bool = Field(
        default=False,
        description="Include locally deleted items",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Pagination offset",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum results to return (max 100)",
    )


class SearchHit(BaseModel):
    """A single search result."""

    id: str = Field(..., description="Document ID (format: doc_type:entity_id)")
    score: float = Field(..., description="Relevance score")
    source: dict[str, Any] = Field(..., description="Document source fields")


class SearchResponse(BaseModel):
    """Response schema for search endpoint."""

    total: int = Field(..., description="Total number of matching documents")
    hits: list[SearchHit] = Field(..., description="Search result hits")
    max_score: Optional[float] = Field(
        default=None,
        description="Maximum relevance score",
    )
