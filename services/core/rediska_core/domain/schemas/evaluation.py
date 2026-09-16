"""Shared read-model schema for human evaluations attached to analysis payloads."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class EffectiveEvaluation(BaseModel):
    """Compact effective (latest) evaluation for one subject + dimension."""

    id: int
    human_verdict: str
    reason_tags: list[str] = Field(default_factory=list)
    corrected_value: Optional[dict[str, Any]] = None
    missing_info: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime


class ModelInput(BaseModel):
    """What a dimension agent actually received (verbatim).

    ``source``: ``stored`` (full prompt kept), ``excerpt`` (pre-feature row
    with only the first 2,000 chars), ``reconstructed`` (scout-only post: no
    prompt was kept, rebuilt from the stored post text and summaries), or
    ``unavailable``.
    """

    source: str
    prompt: Optional[str] = None
    sections: list[str] = Field(default_factory=list)
    total_chars: Optional[int] = None
    attempt: Optional[int] = None
