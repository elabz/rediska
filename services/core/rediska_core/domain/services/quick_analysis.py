"""Quick analysis service for lightweight post screening.

This service provides fast analysis of posts using only the Meta-Analysis
agent without fetching full profile data. Used by Scout Watch for
initial post screening.

Usage:
    service = QuickAnalysisService(inference_client=client)

    result = await service.analyze_post(
        title="Post title",
        body="Post content",
        author_username="username",
    )

    if result.recommendation == "suitable":
        # Create lead
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

from pydantic import BaseModel, Field

from rediska_core.domain.services.agent import AgentConfig, AgentHarness
from rediska_core.domain.services.inference import InferenceClient


logger = logging.getLogger(__name__)


# =============================================================================
# OUTPUT SCHEMA
# =============================================================================


class QuickAnalysisOutput(BaseModel):
    """Output schema for quick post analysis."""

    recommendation: str = Field(
        description="Suitability recommendation: 'suitable', 'not_recommended', or 'needs_review'"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score between 0 and 1",
    )
    reasoning: str = Field(
        description="Brief explanation for the recommendation",
    )
    key_signals: list[str] = Field(
        default_factory=list,
        description="Key signals identified in the post",
    )


# =============================================================================
# RESULT DATACLASS
# =============================================================================


@dataclass
class QuickAnalysisResult:
    """Result of a quick analysis."""

    recommendation: str
    confidence: float
    reasoning: str
    key_signals: list[str]
    success: bool = True
    error: Optional[str] = None

    @classmethod
    def from_error(cls, error: str) -> "QuickAnalysisResult":
        """Create a failed result from an error."""
        return cls(
            recommendation="needs_review",
            confidence=0.0,
            reasoning=f"Analysis failed: {error}",
            key_signals=[],
            success=False,
            error=error,
        )


# =============================================================================
# DEFAULT PROMPT
# =============================================================================


QUICK_ANALYSIS_SYSTEM_PROMPT = """You are a quick screening agent that evaluates Reddit personals posts to determine if they are potentially suitable matches.

You will analyze the POST CONTENT ONLY (not full profile data). Your task is to make a fast initial assessment based on:

1. **Post Content Quality**: Is the post well-written, genuine, and detailed?
2. **Intent Clarity**: Does the author clearly express what they're looking for?
3. **Red Flags**: Are there any obvious warning signs (spam, bots, scams, minors)?
4. **Compatibility Signals**: Does the post indicate potential compatibility based on:
   - Age (must be 18+)
   - Location (if specified)
   - Relationship type sought
   - Communication style

Guidelines:
- Mark as "suitable" if the post shows genuine interest and no red flags
- Mark as "not_recommended" if there are clear red flags or obvious incompatibility
- Mark as "needs_review" if you're uncertain and more information is needed

Be somewhat permissive in initial screening - it's better to include borderline posts than miss good ones.

Respond in JSON format matching the output schema."""


# =============================================================================
# SERVICE
# =============================================================================


class QuickAnalysisService:
    """Service for lightweight post analysis.

    Runs a fast single-agent analysis on post content without
    fetching full profile data.
    """

    def __init__(
        self,
        inference_client: InferenceClient,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ):
        """Initialize the quick analysis service.

        Args:
            inference_client: Client for LLM inference.
            system_prompt: Custom system prompt (optional).
            temperature: LLM temperature setting.
            max_tokens: Maximum tokens for response.
        """
        self.inference_client = inference_client
        self.system_prompt = system_prompt or QUICK_ANALYSIS_SYSTEM_PROMPT
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def analyze_post(
        self,
        title: str,
        body: str,
        author_username: str,
        source_location: Optional[str] = None,
    ) -> QuickAnalysisResult:
        """Analyze a post for suitability.

        Args:
            title: Post title.
            body: Post body text.
            author_username: Author's username.
            source_location: Source subreddit (optional).

        Returns:
            QuickAnalysisResult with recommendation and confidence.
        """
        try:
            # Build input prompt
            input_prompt = self._build_input_prompt(
                title=title,
                body=body,
                author_username=author_username,
                source_location=source_location,
            )

            # Configure agent
            config = AgentConfig(
                name="quick_analysis",
                system_prompt=self.system_prompt,
                output_schema=QuickAnalysisOutput,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                tool_allowlist=[],
            )

            # Run analysis
            harness = AgentHarness(
                config=config,
                inference_client=self.inference_client,
            )
            result = await harness.run(input_prompt)

            # Parse result
            if result.get("success") and result.get("parsed_output"):
                output = result["parsed_output"]
                return QuickAnalysisResult(
                    recommendation=output.get("recommendation", "needs_review"),
                    confidence=output.get("confidence", 0.0),
                    reasoning=output.get("reasoning", ""),
                    key_signals=output.get("key_signals", []),
                    success=True,
                )
            else:
                error = result.get("error", "Analysis failed")
                logger.warning(f"Quick analysis failed: {error}")
                return QuickAnalysisResult.from_error(error)

        except Exception as e:
            logger.exception(f"Quick analysis error: {e}")
            return QuickAnalysisResult.from_error(str(e))

    def _build_input_prompt(
        self,
        title: str,
        body: str,
        author_username: str,
        source_location: Optional[str] = None,
    ) -> str:
        """Build the input prompt for analysis.

        Args:
            title: Post title.
            body: Post body text.
            author_username: Author's username.
            source_location: Source subreddit (optional).

        Returns:
            Formatted input prompt string.
        """
        parts = [
            "Please analyze this Reddit post for initial suitability screening.",
            "",
            f"**Author**: u/{author_username}",
        ]

        if source_location:
            parts.append(f"**Subreddit**: {source_location}")

        parts.extend([
            "",
            f"**Title**: {title}",
            "",
            "**Post Content**:",
            body or "(No body text)",
            "",
            "Provide your analysis in JSON format.",
        ])

        return "\n".join(parts)


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "QuickAnalysisService",
    "QuickAnalysisResult",
    "QuickAnalysisOutput",
    "QUICK_ANALYSIS_SYSTEM_PROMPT",
]
