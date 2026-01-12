"""Lead scoring agent for evaluating lead quality.

Scores leads and provides:
1. Score (0-100) - Quality/fit score for the lead
2. Reasons - Why the lead received this score
3. Flags - Any concerns or special considerations
4. Recommended action - What to do next with this lead

Usage:
    agent = LeadScoringAgent(inference_client=client)

    input_data = LeadScoringInput(
        lead_data={"title": "...", "body_text": "..."},
        profile_summary={"summary": "..."},
    )

    result = await agent.score(input_data)

    if result.success:
        print(f"Score: {result.output.score}")
        print(f"Action: {result.output.recommended_action}")
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError

from rediska_core.domain.services.inference import ChatMessage, InferenceClient


# =============================================================================
# OUTPUT SCHEMAS
# =============================================================================


class ScoringReason(BaseModel):
    """A reason explaining part of the score.

    Captures why a particular factor contributed to the score.
    """

    factor: str = Field(..., description="The factor being evaluated (e.g., 'budget_fit', 'intent')")
    impact: str = Field(..., description="Impact on score: positive, negative, or neutral")
    description: str = Field(..., description="Explanation of this factor's contribution")
    weight: float = Field(default=0.1, ge=0.0, le=1.0, description="Weight of this factor (0-1)")


class ScoringFlag(BaseModel):
    """A flag indicating a concern or special consideration.

    Used to highlight issues that may affect lead handling.
    """

    type: str = Field(..., description="Type of flag (e.g., 'low_budget', 'competitor_mention')")
    severity: str = Field(default="medium", description="Severity: low, medium, high")
    description: str = Field(..., description="Description of the concern")


class LeadScoringOutput(BaseModel):
    """Structured output from the lead scoring agent."""

    score: int = Field(..., ge=0, le=100, description="Lead quality score 0-100")
    reasons: list[ScoringReason] = Field(
        default_factory=list, description="Reasons for the score"
    )
    flags: list[ScoringFlag] = Field(
        default_factory=list, description="Flags/concerns about the lead"
    )
    recommended_action: str = Field(
        ..., description="Recommended action: contact, review, nurture, skip, prioritize"
    )
    confidence: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Confidence in the scoring (0-1)"
    )

    def to_storage_format(self) -> dict:
        """Convert to format suitable for database storage.

        Returns:
            Dictionary with score and related data
        """
        return {
            "score": self.score,
            "reasons_json": [r.model_dump() for r in self.reasons],
            "flags_json": [f.model_dump() for f in self.flags],
            "recommended_action": self.recommended_action,
            "confidence": self.confidence,
        }


# =============================================================================
# INPUT DATA
# =============================================================================


@dataclass
class LeadScoringInput:
    """Input data for the lead scoring agent.

    Combines lead post data, optional profile summary, and scoring criteria.
    """

    lead_data: dict = field(default_factory=dict)
    profile_summary: Optional[dict] = None
    scoring_criteria: Optional[dict] = None

    def to_prompt(self) -> str:
        """Generate a prompt from the input data.

        Returns:
            Formatted prompt string for the agent
        """
        parts = []

        # Lead post section
        parts.append("## Lead Post")
        parts.append(f"Title: {self.lead_data.get('title', 'N/A')}")
        parts.append(f"Source: {self.lead_data.get('source_location', 'N/A')}")
        if self.lead_data.get('post_created_at'):
            parts.append(f"Posted: {self.lead_data.get('post_created_at')}")
        parts.append("")
        parts.append("Content:")
        parts.append(self.lead_data.get('body_text', 'No content available')[:2000])
        parts.append("")

        # Profile summary section (if available)
        if self.profile_summary:
            parts.append("## Author Profile")
            parts.append(f"Summary: {self.profile_summary.get('summary', 'N/A')}")

            signals = self.profile_summary.get('signals', [])
            if signals:
                parts.append("\nKnown signals:")
                for signal in signals[:5]:  # Limit to 5 signals
                    name = signal.get('name', '')
                    value = signal.get('value', '')
                    parts.append(f"- {name}: {value}")

            risk_flags = self.profile_summary.get('risk_flags', [])
            if risk_flags:
                parts.append("\nProfile risk flags:")
                for flag in risk_flags[:3]:
                    parts.append(f"- {flag.get('type', '')}: {flag.get('description', '')}")

            parts.append("")

        # Scoring criteria section (if provided)
        if self.scoring_criteria:
            parts.append("## Scoring Criteria")
            for key, value in self.scoring_criteria.items():
                parts.append(f"- {key}: {value}")
            parts.append("")

        return "\n".join(parts)


# =============================================================================
# AGENT RESULT
# =============================================================================


@dataclass
class LeadScoringResult:
    """Result from running the lead scoring agent."""

    success: bool
    output: Optional[LeadScoringOutput] = None
    error: Optional[str] = None
    model_info: Optional[dict] = None
    raw_response: Optional[str] = None


# =============================================================================
# LEAD SCORING AGENT
# =============================================================================


LEAD_SCORING_SYSTEM_PROMPT = """You are an expert lead qualification specialist. Your task is to score leads based on their potential value and fit.

Given a lead post and optionally the author's profile, you must evaluate and score the lead from 0 to 100:

**Scoring Guidelines:**
- 90-100: Hot lead - High intent, clear budget, decision maker, urgent need
- 70-89: Warm lead - Good fit, some buying signals, worth immediate contact
- 50-69: Moderate lead - Potential fit, needs nurturing or more qualification
- 30-49: Cool lead - Limited fit, low priority, consider for future
- 0-29: Poor lead - Not a fit, likely waste of time

**Factors to Consider:**
1. **Intent Signals**: Are they actively looking to buy/solve a problem?
2. **Budget Indicators**: Do they mention budget? Is it realistic?
3. **Authority**: Do they appear to be a decision maker?
4. **Need**: Is the need clear and urgent?
5. **Timing**: Are they looking to act soon?
6. **Fit**: Do they match target customer profile?

**Recommended Actions:**
- "prioritize": Score 85+, contact immediately
- "contact": Score 70-84, reach out soon
- "review": Score 50-69, needs more research
- "nurture": Score 30-49, add to nurture campaign
- "skip": Score below 30, not worth pursuing

You MUST respond with valid JSON in this exact format:
{
    "score": 75,
    "reasons": [
        {"factor": "factor_name", "impact": "positive|negative|neutral", "description": "why", "weight": 0.2}
    ],
    "flags": [
        {"type": "flag_type", "severity": "low|medium|high", "description": "concern"}
    ],
    "recommended_action": "contact|review|nurture|skip|prioritize",
    "confidence": 0.8
}

Respond ONLY with the JSON object, no other text."""


class LeadScoringAgent:
    """Agent for scoring leads.

    Evaluates lead quality and provides scoring with reasons,
    flags, and recommended actions.
    """

    def __init__(self, inference_client: InferenceClient):
        """Initialize the lead scoring agent.

        Args:
            inference_client: Client for LLM inference
        """
        self.inference_client = inference_client

    def get_system_prompt(self) -> str:
        """Get the system prompt for the agent.

        Returns:
            System prompt string
        """
        return LEAD_SCORING_SYSTEM_PROMPT

    async def score(self, input_data: LeadScoringInput) -> LeadScoringResult:
        """Score a lead.

        Args:
            input_data: Lead scoring input data

        Returns:
            LeadScoringResult with output or error
        """
        # Build messages
        messages = [
            ChatMessage(role="system", content=self.get_system_prompt()),
            ChatMessage(role="user", content=input_data.to_prompt()),
        ]

        # Make inference request
        try:
            response = await self.inference_client.chat(messages)
        except Exception as e:
            return LeadScoringResult(
                success=False,
                error=f"Inference error: {e}",
            )

        # Parse response
        try:
            content = response.content.strip()

            # Handle potential markdown code blocks
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])

            data = json.loads(content)

            # Validate against schema
            output = LeadScoringOutput.model_validate(data)

            return LeadScoringResult(
                success=True,
                output=output,
                model_info=response.model_info.to_dict(),
                raw_response=response.content,
            )

        except json.JSONDecodeError as e:
            return LeadScoringResult(
                success=False,
                error=f"Invalid JSON response: {e}",
                model_info=response.model_info.to_dict() if response.model_info else None,
                raw_response=response.content,
            )
        except ValidationError as e:
            return LeadScoringResult(
                success=False,
                error=f"Validation error: {e}",
                model_info=response.model_info.to_dict() if response.model_info else None,
                raw_response=response.content,
            )


# =============================================================================
# LEAD SCORING SERVICE
# =============================================================================


class LeadScoringService:
    """Service for orchestrating lead scoring.

    Loads lead data, optionally fetches profile summary, runs scoring,
    and updates the lead record.
    """

    def __init__(
        self,
        db,
        inference_client: InferenceClient,
    ):
        """Initialize the lead scoring service.

        Args:
            db: Database session
            inference_client: Client for LLM inference
        """
        self.db = db
        self.inference_client = inference_client

    async def score_lead(
        self,
        lead_id: int,
        scoring_criteria: Optional[dict] = None,
    ) -> LeadScoringResult:
        """Score a lead by ID.

        Args:
            lead_id: ID of the lead post
            scoring_criteria: Optional custom scoring criteria

        Returns:
            LeadScoringResult with the score
        """
        from rediska_core.domain.models import LeadPost, ProfileSnapshot

        # Load lead
        lead = self.db.get(LeadPost, lead_id)
        if not lead:
            return LeadScoringResult(
                success=False,
                error=f"Lead {lead_id} not found",
            )

        # Build lead data
        lead_data = {
            "id": lead.id,
            "provider_id": lead.provider_id,
            "source_location": lead.source_location,
            "external_post_id": lead.external_post_id,
            "title": lead.title,
            "body_text": lead.body_text,
            "post_created_at": str(lead.post_created_at) if lead.post_created_at else None,
        }

        # Get profile summary if author exists
        profile_summary = None
        if lead.author_account_id:
            snapshot = (
                self.db.query(ProfileSnapshot)
                .filter(ProfileSnapshot.account_id == lead.author_account_id)
                .order_by(ProfileSnapshot.fetched_at.desc())
                .first()
            )

            if snapshot:
                profile_summary = {
                    "summary": snapshot.summary_text,
                    "signals": snapshot.signals_json or [],
                    "risk_flags": snapshot.risk_flags_json or [],
                }

        # Create agent and run
        agent = LeadScoringAgent(inference_client=self.inference_client)

        input_data = LeadScoringInput(
            lead_data=lead_data,
            profile_summary=profile_summary,
            scoring_criteria=scoring_criteria,
        )

        result = await agent.score(input_data)

        # Store score in lead if successful
        # Note: This would require adding score fields to LeadPost model
        # For now, we just return the result

        return result


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "LeadScoringAgent",
    "LeadScoringInput",
    "LeadScoringOutput",
    "LeadScoringResult",
    "LeadScoringService",
    "ScoringFlag",
    "ScoringReason",
]
