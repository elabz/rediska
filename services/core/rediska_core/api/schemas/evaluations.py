"""Pydantic schemas for human evaluation of agent decisions."""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from rediska_core.domain.schemas.evaluation import EffectiveEvaluation, ModelInput

__all__ = ["EffectiveEvaluation", "ModelInput"]

# Controlled reason-tag vocabulary. Mirrored in the web app
# (apps/web/src/lib/evaluations.ts); adding a tag is a code + spec change.
REASON_TAGS: tuple[str, ...] = (
    "missed_location",
    "wrong_age",
    "wrong_gender",
    "misread_intent",
    "misread_orientation",
    "hallucinated_fact",
    "missing_context",
    "stale_context",
    "too_strict",
    "too_lenient",
    "unparseable_output",
    "risk_missed",
    "risk_overcalled",
    "other",
)

EVALUABLE_DIMENSIONS: tuple[str, ...] = (
    "demographics",
    "preferences",
    "relationship_goals",
    "risk_flags",
    "sexual_preferences",
)

HumanVerdictLiteral = Literal["agree", "partial", "disagree"]
RecommendationLiteral = Literal["suitable", "not_recommended", "needs_review"]
SubjectTypeLiteral = Literal["lead_analysis", "scout_post"]
ReasonTagLiteral = Literal[
    "missed_location",
    "wrong_age",
    "wrong_gender",
    "misread_intent",
    "misread_orientation",
    "hallucinated_fact",
    "missing_context",
    "stale_context",
    "too_strict",
    "too_lenient",
    "unparseable_output",
    "risk_missed",
    "risk_overcalled",
    "other",
]
DimensionLiteral = Literal[
    "demographics",
    "preferences",
    "relationship_goals",
    "risk_flags",
    "sexual_preferences",
]


# =============================================================================
# Evaluations
# =============================================================================


class EvaluationCreate(BaseModel):
    """Record a human verdict on a final recommendation or one dimension."""

    subject_type: SubjectTypeLiteral
    subject_id: int
    dimension: Optional[DimensionLiteral] = Field(
        default=None, description="NULL for the final recommendation"
    )
    human_verdict: HumanVerdictLiteral
    corrected_value: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Final verdict: {'recommendation': ...}; dimension: corrected field values"
        ),
    )
    reason_tags: list[ReasonTagLiteral] = Field(default_factory=list)
    missing_info: Optional[str] = Field(
        default=None, description="Required when 'missing_context' is tagged"
    )
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _validate(self) -> "EvaluationCreate":
        # Dedupe tags preserving order
        seen: set[str] = set()
        self.reason_tags = [
            t for t in self.reason_tags if not (t in seen or seen.add(t))
        ]
        if "missing_context" in self.reason_tags and not (
            self.missing_info and self.missing_info.strip()
        ):
            raise ValueError(
                "missing_info is required when 'missing_context' is tagged"
            )
        if self.missing_info is not None:
            self.missing_info = self.missing_info.strip() or None
        if self.dimension is None and self.corrected_value is not None:
            rec = self.corrected_value.get("recommendation")
            if rec not in ("suitable", "not_recommended", "needs_review"):
                raise ValueError(
                    "corrected_value.recommendation must be one of "
                    "suitable, not_recommended, needs_review"
                )
        return self


class EvaluationResponse(BaseModel):
    """A stored evaluation row."""

    id: int
    subject_type: str
    subject_id: int
    account_id: Optional[int] = None
    dimension: Optional[str] = None
    human_verdict: str
    corrected_value: Optional[dict[str, Any]] = None
    reason_tags: list[str] = Field(default_factory=list)
    missing_info: Optional[str] = None
    notes: Optional[str] = None
    agent_snapshot: dict[str, Any] = Field(default_factory=dict)
    prompt_versions: dict[str, Any] = Field(default_factory=dict)
    model_name: Optional[str] = None
    created_at: datetime
    created_by: str


class EvaluationListResponse(BaseModel):
    """Evaluations for one subject (all rows, newest first) + effective map."""

    subject_type: str
    subject_id: int
    evaluations: list[EvaluationResponse]
    effective: dict[str, Optional[EffectiveEvaluation]] = Field(
        default_factory=dict,
        description="Keyed by dimension name, or 'final' for the final verdict",
    )


# =============================================================================
# Review queue
# =============================================================================


class GateResultItem(BaseModel):
    gate: str
    status: str
    reason: str


class QueueItem(BaseModel):
    """One unevaluated analysis subject with enough context to judge it."""

    subject_type: SubjectTypeLiteral
    subject_id: int
    reason: str = Field(
        description="Why it is queued: contradiction_ignored_suitable, "
        "contradiction_promoted_not_suitable, sample"
    )
    recommendation: Optional[str] = None
    confidence: Optional[float] = None
    gate_results: list[GateResultItem] = Field(default_factory=list)
    unclear_gate_count: int = 0
    failed_gate_count: int = 0

    # Where it came from
    lead_id: Optional[int] = None
    lead_status: Optional[str] = None
    analysis_id: Optional[int] = None
    scout_post_id: Optional[int] = None
    watch_id: Optional[int] = None
    account_id: Optional[int] = None

    # Content (verbatim)
    author: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None
    post_url: Optional[str] = None
    interests_summary: Optional[str] = None
    character_summary: Optional[str] = None

    # Analysis summary
    reasoning: Optional[str] = None
    dimensions: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-dimension parsed outputs (or {'error': ...})",
    )
    meta_analysis: Optional[dict[str, Any]] = None
    prompt_versions: dict[str, Any] = Field(default_factory=dict)
    analyzed_at: Optional[datetime] = None
    # When the post itself was published (leads) or first seen by a scout watch
    posted_at: Optional[datetime] = None
    posted_at_kind: Optional[str] = Field(default=None, description="posted | first_seen")
    # Per-dimension verbatim model input, so the reviewer sees what the agent saw
    model_inputs: dict[str, ModelInput] = Field(default_factory=dict)

    # Existing per-dimension evaluations (final is absent by definition)
    evaluations: dict[str, Optional[EffectiveEvaluation]] = Field(default_factory=dict)


class QueueResponse(BaseModel):
    items: list[QueueItem]
    next_cursor: Optional[str] = None
    total_remaining: int = Field(
        0, description="Unevaluated subjects matching the filters (approximate)"
    )


# =============================================================================
# Summary / metrics
# =============================================================================


class VerdictCounts(BaseModel):
    agree: int = 0
    partial: int = 0
    disagree: int = 0
    total: int = 0
    agreement: Optional[float] = Field(
        default=None, description="(agree + 0.5*partial) / total; null when total is 0"
    )


class DimensionSummary(BaseModel):
    dimension: str
    counts: VerdictCounts
    tags: dict[str, int] = Field(default_factory=dict)
    by_prompt_version: dict[str, VerdictCounts] = Field(default_factory=dict)


class TrendPoint(BaseModel):
    week: str = Field(description="ISO week label, e.g. 2026-W37")
    dimension: str
    counts: VerdictCounts


class MissingInfoItem(BaseModel):
    text: str
    count: int
    dimensions: list[str] = Field(default_factory=list)


class EvaluationSummary(BaseModel):
    total_evaluations: int = 0
    overall: VerdictCounts
    dimensions: list[DimensionSummary] = Field(default_factory=list)
    confusion_matrix: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description="agent recommendation -> human recommendation -> count",
    )
    trend: list[TrendPoint] = Field(default_factory=list)
    missing_info: list[MissingInfoItem] = Field(default_factory=list)
    period_since: Optional[datetime] = None
    watch_id: Optional[int] = None


# =============================================================================
# Prompt replay
# =============================================================================


class ReplayCreate(BaseModel):
    """Replay a draft (or existing version) prompt against labelled cases."""

    system_prompt: Optional[str] = Field(
        default=None, description="Draft prompt text; required unless version is given"
    )
    version: Optional[int] = Field(
        default=None, description="Existing version to replay instead of a draft"
    )
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    max_cases: Optional[int] = Field(
        default=None, ge=1, description="Cap on cases; clamped to EVALUATION_REPLAY_MAX_CASES"
    )

    @model_validator(mode="after")
    def _one_source(self) -> "ReplayCreate":
        if not (self.system_prompt and self.system_prompt.strip()) and self.version is None:
            raise ValueError("Provide system_prompt (draft) or version")
        return self


class ReplayCaseResult(BaseModel):
    evaluation_id: int
    subject_type: str
    subject_id: int
    agreed: Optional[bool] = None
    skipped: Optional[str] = None
    expected: Optional[dict[str, Any]] = None
    produced: Optional[dict[str, Any]] = None
    field_results: dict[str, bool] = Field(default_factory=dict)
    error: Optional[str] = None


class ReplayResponse(BaseModel):
    id: int
    dimension: str
    candidate_version: Optional[int] = None
    candidate_system_prompt: Optional[str] = None
    status: str
    case_count: int
    completed_count: int
    agreed_count: int
    skipped_no_input: int
    agreement: Optional[float] = None
    results: list[ReplayCaseResult] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class ReplayListResponse(BaseModel):
    dimension: str
    replays: list[ReplayResponse]


class PromptVersionMetrics(BaseModel):
    evaluations: int = 0
    agreement: Optional[float] = None
