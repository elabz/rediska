"""Pydantic schemas for multi-agent lead analysis output."""

from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================================================
# Demographics Agent Output Schema
# ============================================================================


class DemographicsOutput(BaseModel):
    """Demographics analysis output - age, gender, location."""

    age: Optional[int] = Field(
        None,
        description="Author's age as a single number extracted from post title or body",
    )
    age_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in age extraction (0.0-1.0)",
    )

    gender: Optional[str] = Field(
        None,
        description="Author's gender: 'male', 'female', 'non-binary', or 'unclear'",
    )
    gender_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in gender assessment",
    )

    location: Optional[str] = Field(
        None,
        description="Geographic location code or name (e.g., 'PA', 'Philadelphia', 'NJ')",
    )
    location_near: bool = Field(
        default=False,
        description="True if location is in our target area (PA, NJ, DE, Philadelphia area)",
    )
    distance_miles: Optional[int] = Field(
        None,
        description="Distance in miles from home location (computed by geocoder)",
    )
    location_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in location assessment",
    )

    evidence: list[str] = Field(
        default_factory=list,
        description="Supporting evidence from post content",
    )

    flags: list[str] = Field(
        default_factory=list,
        description="Any concerns or inconsistencies in demographic information",
    )

    model_config = {"extra": "allow"}


# ============================================================================
# Preferences & Interests Agent Output Schema
# ============================================================================


class PreferencesOutput(BaseModel):
    """Personal preferences, hobbies, and kinks analysis with compatibility scoring."""

    hobbies: list[str] = Field(
        default_factory=list,
        description="All hobbies and activities mentioned",
    )

    preferred_hobbies_found: list[str] = Field(
        default_factory=list,
        description="High-value hobbies found (reading, hiking)",
    )

    kinks: list[str] = Field(
        default_factory=list,
        description="All kinks and interests mentioned",
    )

    preferred_kinks_found: list[str] = Field(
        default_factory=list,
        description="High-value kinks found (rope, spanking, shibari, kinbaku)",
    )

    lifestyle: Optional[str] = Field(
        None,
        description="Lifestyle category (e.g., 'active', 'creative', 'social', 'introverted')",
    )

    compatibility_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Overall compatibility based on preferred hobbies and kinks (0.0-1.0)",
    )

    evidence: list[str] = Field(
        default_factory=list,
        description="Supporting evidence from content",
    )

    model_config = {"extra": "allow"}


# ============================================================================
# Relationship Goals & Criteria Agent Output Schema
# ============================================================================


class RelationshipGoalsOutput(BaseModel):
    """Relationship goals and partner criteria analysis."""

    relationship_intent: Optional[str] = Field(
        None,
        description="Type of relationship sought - 'casual', 'serious', 'marriage', 'open', or 'unclear'",
    )
    intent_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in relationship intent assessment",
    )

    relationship_timeline: Optional[str] = Field(
        None,
        description="Urgency/timeline indicators (e.g., 'immediate', 'soon', 'eventually', 'no rush')",
    )

    relationship_goals: list[str] = Field(
        default_factory=list,
        description="All identifiable relationship goals",
    )

    partner_max_age: Optional[str] = Field(
        None,
        description="Maximum partner age as string (e.g., '35', '50') or 'no_max_age' if not specified",
    )

    partner_criteria: Any = Field(
        default_factory=dict,
        description="Stated partner requirements and preferences (dict or list)",
    )

    deal_breakers: list[str] = Field(
        default_factory=list,
        description="Explicitly stated deal-breakers (e.g., 'wants children', 'must be religious')",
    )

    relationship_history: list[str] = Field(
        default_factory=list,
        description="References to past relationships or relationship status",
    )

    compatibility_factors: list[str] = Field(
        default_factory=list,
        description="Factors that indicate compatibility",
    )

    incompatibility_factors: list[str] = Field(
        default_factory=list,
        description="Factors that indicate incompatibility",
    )

    evidence: list[str] = Field(
        default_factory=list,
        description="Supporting evidence from content",
    )

    model_config = {"extra": "allow"}


# ============================================================================
# Risk Flags Agent Output Schema
# ============================================================================


class RiskFlagsOutput(BaseModel):
    """Risk and authenticity analysis - focused on scam/seller detection."""

    is_authentic: bool = Field(
        default=True,
        description="True if appears to be a genuine person seeking connection, False if likely scam/seller",
    )

    red_flags: list[str] = Field(
        default_factory=list,
        description="Identified red flags (OF/TG mentions, 'generous' language, sugar references)",
    )

    scam_indicators: list[str] = Field(
        default_factory=list,
        description="Signs this may be a scam, seller, or promotional account",
    )

    assessment: str = Field(
        default="genuine",
        description="Overall assessment: 'genuine', 'suspicious', or 'likely_scam'",
    )

    evidence: list[str] = Field(
        default_factory=list,
        description="Supporting evidence from content",
    )

    model_config = {"extra": "allow"}


# ============================================================================
# Sexual Preferences Agent Output Schema
# ============================================================================


class SexualPreferencesOutput(BaseModel):
    """D/s orientation and intimacy preferences analysis."""

    ds_orientation: Optional[str] = Field(
        None,
        description="Dominant/submissive orientation: 'dominant', 'submissive', 'switch', or null if unclear",
    )
    ds_orientation_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in D/s orientation assessment",
    )

    kinks_interests: list[str] = Field(
        default_factory=list,
        description="Stated sexual interests, kinks, or preferences",
    )

    intimacy_expectations: Optional[str] = Field(
        None,
        description="Expectations around physical intimacy and frequency",
    )

    sexual_compatibility_notes: list[str] = Field(
        default_factory=list,
        description="General sexual compatibility observations",
    )

    evidence: list[str] = Field(
        default_factory=list,
        description="Supporting evidence from content",
    )

    model_config = {"extra": "allow"}


# ============================================================================
# Meta-Analysis Coordinator Output Schema
# ============================================================================


class MetaAnalysisOutput(BaseModel):
    """Final meta-analysis and suitability recommendation."""

    recommendation: str = Field(
        default="needs_review",
        description="Final recommendation - 'suitable', 'not_recommended', or 'needs_review'",
    )

    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in the recommendation (0.0-1.0)",
    )

    reasoning: str = Field(
        default="",
        description="Which rule passed or failed and why",
    )

    failed_rule: Optional[str] = Field(
        None,
        description="The rule that caused failure, or null if passed",
    )

    strengths: list[str] = Field(
        default_factory=list,
        description="Positive factors identified",
    )

    concerns: list[str] = Field(
        default_factory=list,
        description="Concerns or negative factors",
    )

    compatibility_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Overall compatibility score from preferences",
    )

    priority_level: str = Field(
        default="medium",
        description="Contact priority - 'high', 'medium', or 'low'",
    )

    model_config = {"extra": "allow"}


# ============================================================================
# Database Model for AgentPrompt
# ============================================================================


class AgentPrompt(BaseModel):
    """Agent prompt database model."""

    id: int
    agent_dimension: str
    version: int
    system_prompt: str
    output_schema_json: dict[str, Any]
    temperature: float
    max_tokens: int
    is_active: bool
    created_at: str
    created_by: str
    notes: Optional[str]

    class Config:
        from_attributes = True


# ============================================================================
# Analysis Result Models
# ============================================================================


class DimensionAnalysisResult(BaseModel):
    """Result of analyzing a single dimension."""

    dimension: str
    status: str  # pending|running|completed|failed
    output: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    model_info: Optional[dict[str, Any]] = None
    started_at: str
    completed_at: Optional[str] = None


class MultiAgentAnalysisResponse(BaseModel):
    """Complete multi-agent analysis response."""

    id: int
    lead_id: int
    account_id: int
    status: str
    started_at: str
    completed_at: Optional[str]

    # Dimension results
    demographics: Optional[DimensionAnalysisResult] = None
    preferences: Optional[DimensionAnalysisResult] = None
    relationship_goals: Optional[DimensionAnalysisResult] = None
    risk_flags: Optional[DimensionAnalysisResult] = None
    sexual_preferences: Optional[DimensionAnalysisResult] = None

    # Meta-analysis
    final_recommendation: Optional[str] = None
    recommendation_reasoning: Optional[str] = None
    confidence_score: Optional[float] = None
    meta_analysis: Optional[dict[str, Any]] = None

    # Metadata
    prompt_versions: dict[str, int]
    model_info: Optional[dict[str, Any]] = None

    class Config:
        from_attributes = True


class MultiAgentAnalysisSummary(BaseModel):
    """Summary of a lead analysis for history listing."""

    id: int
    lead_id: int
    status: str
    final_recommendation: Optional[str]
    confidence_score: Optional[float]
    created_at: str
    completed_at: Optional[str]

    class Config:
        from_attributes = True
