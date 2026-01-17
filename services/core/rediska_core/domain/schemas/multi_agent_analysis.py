"""Pydantic schemas for multi-agent lead analysis output."""

from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================================================
# Demographics Agent Output Schema
# ============================================================================


class DemographicsOutput(BaseModel):
    """Demographics analysis output - age, gender, location."""

    age_range: Optional[Any] = Field(
        None,
        description="Estimated age range (min, max) in years - can be tuple or list",
    )
    age_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in age estimation (0.0-1.0)",
    )

    gender: Optional[str] = Field(
        None,
        description="Apparent gender identity (e.g., 'male', 'female', 'non-binary', 'unclear')",
    )
    gender_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in gender assessment",
    )

    location: Optional[Any] = Field(
        None,
        description="Geographic location (city, region, country) - can be string or object",
    )
    location_specificity: str = Field(
        default="unknown",
        description="Level of specificity - 'city', 'region', 'country', or 'unknown'",
    )
    location_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in location assessment",
    )

    ethnicity_indicators: list[str] = Field(
        default_factory=list,
        description="Cultural or ethnic indicators if mentioned or implied",
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
    """Personal preferences and interests analysis."""

    hobbies: list[str] = Field(
        default_factory=list,
        description="Identified hobbies and activities",
    )

    lifestyle: Optional[str] = Field(
        None,
        description="Lifestyle category (e.g., 'active', 'sedentary', 'social', 'introverted')",
    )

    values: list[str] = Field(
        default_factory=list,
        description="Core values expressed or implied",
    )

    interests: dict[str, float] = Field(
        default_factory=dict,
        description="Interest categories with confidence scores 0-1",
    )

    personality_traits: list[str] = Field(
        default_factory=list,
        description="Observable personality characteristics",
    )

    communication_style: Optional[str] = Field(
        None,
        description="Communication style assessment (e.g., 'direct', 'indirect', 'playful', 'formal')",
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

    partner_criteria: Any = Field(
        default_factory=dict,
        description="Stated partner requirements and preferences (dict or list)",
    )

    deal_breakers: list[Any] = Field(
        default_factory=list,
        description="Explicitly stated deal-breakers or hard requirements",
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


class RiskFlag(BaseModel):
    """Individual risk flag with context."""

    type: str = Field(
        ...,
        description="Risk category (e.g., 'manipulation', 'deception', 'aggression', 'safety_concern')",
    )
    severity: str = Field(
        ...,
        description="Severity level - 'low', 'medium', 'high', or 'critical'",
    )
    description: str = Field(
        ...,
        description="Detailed explanation of the risk",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Specific evidence from content",
    )


class RiskFlagsOutput(BaseModel):
    """Risk and red flag analysis."""

    flags: list[RiskFlag] = Field(
        default_factory=list,
        description="Identified risk flags with severity",
    )

    behavioral_concerns: list[str] = Field(
        default_factory=list,
        description="Concerning behavioral patterns or attitudes",
    )

    safety_assessment: str = Field(
        default="unknown",
        description="Overall safety assessment - 'safe', 'caution', or 'unsafe'",
    )

    authenticity_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Profile authenticity confidence (1.0 = definitely authentic, 0.0 = likely fake)",
    )

    manipulation_indicators: list[str] = Field(
        default_factory=list,
        description="Signs of manipulation, deception, or scam patterns",
    )

    overall_risk_level: str = Field(
        default="unknown",
        description="Overall risk assessment - 'low', 'medium', 'high', or 'critical'",
    )

    # Additional fields that LLM may output
    red_flags: list[str] = Field(
        default_factory=list,
        description="Red flags identified",
        alias="redFlags",
    )

    safety_concerns: list[Any] = Field(
        default_factory=list,
        description="Safety concerns identified - can be strings or objects",
        alias="safetyConcerns",
    )

    authenticity_issues: list[Any] = Field(
        default_factory=list,
        description="Authenticity issues identified - can be strings or objects",
        alias="authenticityIssues",
    )

    model_config = {"populate_by_name": True, "extra": "allow"}


# ============================================================================
# Sexual Preferences Agent Output Schema
# ============================================================================


class SexualPreferencesOutput(BaseModel):
    """Sexual orientation, preferences, and desired partner age analysis."""

    sexual_orientation: Optional[str] = Field(
        None,
        description="Stated or implied sexual orientation (e.g., 'heterosexual', 'homosexual', 'bisexual')",
    )
    orientation_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in sexual orientation assessment",
    )

    kinks_interests: list[str] = Field(
        default_factory=list,
        description="Stated sexual interests, kinks, or preferences",
    )

    intimacy_expectations: Optional[str] = Field(
        None,
        description="Expectations around physical intimacy and frequency",
    )

    desired_partner_age_range: Optional[Any] = Field(
        None,
        description="Preferred partner age range (min, max) in years - can be tuple or list",
    )
    age_preference_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in age preference assessment",
    )

    age_gap_concerns: list[str] = Field(
        default_factory=list,
        description="Concerns about age preferences if any (e.g., 'seeks much younger partners')",
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
        description="Final suitability recommendation - 'suitable', 'not_recommended', or 'needs_review'",
    )

    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Overall confidence in the recommendation",
    )

    reasoning: str = Field(
        default="",
        description="Detailed explanation of the recommendation decision",
    )

    strengths: list[str] = Field(
        default_factory=list,
        description="Positive factors and strengths identified",
    )

    concerns: list[str] = Field(
        default_factory=list,
        description="Concerns, risks, or negative factors identified",
    )

    compatibility_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Overall compatibility score based on all dimensions",
    )

    priority_level: str = Field(
        default="medium",
        description="Recommended contact priority - 'high', 'medium', or 'low'",
    )

    suggested_approach: Optional[str] = Field(
        None,
        description="Suggested approach or messaging strategy if contacting",
    )

    dimension_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Brief summary of key findings from each dimension",
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
