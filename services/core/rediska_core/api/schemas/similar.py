"""Schemas for the similarity ("more like this") endpoint."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from rediska_core.domain.services.similarity import (
    DEFAULT_LIMIT,
    DEFAULT_MIN_SCORE,
    MAX_LIMIT,
)


class SimilarRequest(BaseModel):
    """Ask what else reads like this document, or like this text."""

    doc_type: Optional[str] = Field(
        default=None,
        description="Type of the reference document (lead_post, scout_post, ...)",
    )
    entity_id: Optional[int] = Field(
        default=None,
        description="Id of the reference document",
    )
    text: Optional[str] = Field(
        default=None,
        description="Raw text to compare against, instead of a reference",
    )

    doc_types: Optional[list[str]] = Field(
        default=None,
        description="Restrict neighbours to these document types",
    )
    author: str = Field(
        default="any",
        description="'any', 'same' or 'other', relative to the source's author",
    )
    location: Optional[str] = Field(
        default=None,
        description="Restrict to one community / location",
    )
    since: Optional[datetime] = Field(
        default=None,
        description="Only documents created at or after this time",
    )
    until: Optional[datetime] = Field(
        default=None,
        description="Only documents created at or before this time",
    )
    lead_status: Optional[list[str]] = Field(
        default=None,
        description="Keep only leads in these statuses",
    )
    include_deleted: bool = Field(
        default=False,
        description="Include locally deleted documents",
    )
    min_score: float = Field(
        default=DEFAULT_MIN_SCORE,
        ge=-1.0,
        le=1.0,
        description="Minimum cosine similarity",
    )
    limit: int = Field(
        default=DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description=f"Maximum results (max {MAX_LIMIT})",
    )

    @model_validator(mode="after")
    def _needs_a_subject(self) -> "SimilarRequest":
        has_reference = self.doc_type is not None and self.entity_id is not None
        if not has_reference and not (self.text and self.text.strip()):
            raise ValueError(
                "Provide either a reference (doc_type and entity_id) or text"
            )
        return self


class SimilarHit(BaseModel):
    """One neighbour, with what became of it."""

    id: str
    doc_type: str
    entity_id: Optional[int] = None
    score: float = Field(..., description="Raw Elasticsearch score")
    similarity: Optional[float] = Field(
        default=None,
        description="Cosine similarity (-1..1); null for a text match",
    )
    title: Optional[str] = None
    excerpt: Optional[str] = None
    author_username: Optional[str] = None
    account_id: Optional[int] = None
    location: Optional[str] = None
    created_at: Optional[str] = None
    post_url: Optional[str] = None
    lead_status: Optional[str] = None
    recommendation: Optional[str] = None
    priority: Optional[str] = None
    compatibility_score: Optional[float] = None
    human_verdict: Optional[str] = None
    author_banned: bool = False


class SimilarSource(BaseModel):
    """What the neighbours were measured against."""

    doc_type: Optional[str] = None
    entity_id: Optional[int] = None
    author_username: Optional[str] = None


class SimilarResponse(BaseModel):
    """Neighbours, and how they were found."""

    method: str = Field(..., description="'vector' or 'text'")
    min_score: float
    source: SimilarSource
    results: list[SimilarHit]
