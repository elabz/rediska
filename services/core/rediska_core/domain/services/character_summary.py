"""Character summary service for analyzing user comments.

This service summarizes a user's communication style, personality traits,
and character based on their Reddit comments. Used by the Scout Watch
pipeline to enrich the analysis context before running the 6-agent
multi-agent analysis.

Usage:
    service = CharacterSummaryService(inference_client=client, db=db)

    summary = await service.summarize(comments)
    # Returns: "User communicates in a friendly, helpful manner..."
"""

import logging
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from rediska_core.domain.models import ProfileItem
from rediska_core.domain.services.agent import AgentConfig, AgentHarness
from rediska_core.domain.services.inference import InferenceClient


logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================


MAX_PROFILE_COMMENTS = 100
SCOUT_CHARACTER_DIMENSION = "scout_character_summary"


# =============================================================================
# OUTPUT SCHEMA
# =============================================================================


class CharacterSummaryOutput(BaseModel):
    """Output schema for character summary."""

    model_config = {"populate_by_name": True}

    summary: str = Field(
        default="",
        description="A 2-3 paragraph summary of the user's communication style and personality"
    )
    communication_style: str = Field(
        default="unknown",
        alias="communicationStyle",
        description="Primary communication style (e.g., friendly, formal, casual, aggressive)"
    )
    personality_traits: list[str] = Field(
        default_factory=list,
        alias="personalityTraits",
        description="Key personality traits observed (e.g., helpful, critical, supportive)"
    )
    engagement_style: str = Field(
        default="unknown",
        alias="engagementStyle",
        description="How they typically engage with others (e.g., constructive, confrontational)"
    )
    emotional_tone: str = Field(
        default="unknown",
        alias="emotionalTone",
        description="General emotional tone (e.g., positive, negative, neutral, sarcastic)"
    )
    red_flags: list[str] = Field(
        default_factory=list,
        alias="redFlags",
        description="Any concerning patterns or red flags observed"
    )


# =============================================================================
# RESULT DATACLASS
# =============================================================================


@dataclass
class CharacterSummaryResult:
    """Result of a character summary analysis."""

    summary: str
    communication_style: str
    personality_traits: list[str]
    engagement_style: str
    emotional_tone: str
    red_flags: list[str]
    success: bool = True
    error: Optional[str] = None

    @classmethod
    def from_error(cls, error: str) -> "CharacterSummaryResult":
        """Create a failed result from an error."""
        return cls(
            summary="",
            communication_style="unknown",
            personality_traits=[],
            engagement_style="unknown",
            emotional_tone="unknown",
            red_flags=[],
            success=False,
            error=error,
        )

    @classmethod
    def empty(cls) -> "CharacterSummaryResult":
        """Create an empty result when no comments are available."""
        return cls(
            summary="No comments available for analysis.",
            communication_style="unknown",
            personality_traits=[],
            engagement_style="unknown",
            emotional_tone="unknown",
            red_flags=[],
            success=True,
        )


# =============================================================================
# DEFAULT PROMPT
# =============================================================================


CHARACTER_SUMMARY_SYSTEM_PROMPT = """You are an analyst that assesses a Reddit user's communication style and personality based on their comment history.

Your task is to analyze the user's comments and provide a comprehensive assessment of:

1. **Communication Style**: How does this person communicate? (friendly, formal, casual, aggressive, passive-aggressive, etc.)
2. **Personality Traits**: What traits are evident from their interactions? (helpful, critical, supportive, confrontational, empathetic, etc.)
3. **Engagement Style**: How do they typically engage with others? (constructive discussion, debates, trolling, supportive, dismissive, etc.)
4. **Emotional Tone**: What is their general emotional tone? (positive, negative, neutral, sarcastic, enthusiastic, etc.)
5. **Red Flags**: Are there any concerning patterns? (hostility, manipulation, dishonesty, boundary violations, etc.)

Guidelines:
- Be OBJECTIVE and base your assessment ONLY on the content provided
- Avoid assumptions beyond what's evident in the text
- Note both positive traits and any concerning patterns
- Consider the context of different subreddits when assessing tone
- Summarize in 2-3 paragraphs that would help someone understand how this person interacts

Respond in JSON format matching the output schema."""


# =============================================================================
# SERVICE
# =============================================================================


class CharacterSummaryService:
    """Service for summarizing user character from their comments.

    Analyzes a user's Reddit comments to assess their communication
    style, personality traits, and general character.

    Supports DB-backed prompts: if a db session is provided, it will look up
    the active prompt for the "scout_character_summary" dimension.
    """

    def __init__(
        self,
        inference_client: InferenceClient,
        db: Optional[Session] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ):
        """Initialize the character summary service.

        Args:
            inference_client: Client for LLM inference.
            db: Database session for prompt lookup (optional).
            system_prompt: Custom system prompt (optional, overrides DB lookup).
            temperature: LLM temperature setting.
            max_tokens: Maximum tokens for response.
        """
        self.inference_client = inference_client

        # Try to load prompt from DB if session is provided
        if db and not system_prompt:
            self._load_prompt_from_db(db, temperature, max_tokens)
        else:
            self.system_prompt = system_prompt or CHARACTER_SUMMARY_SYSTEM_PROMPT
            self.temperature = temperature
            self.max_tokens = max_tokens

    def _load_prompt_from_db(
        self,
        db: Session,
        default_temperature: float,
        default_max_tokens: int,
    ) -> None:
        """Load prompt configuration from database."""
        try:
            from rediska_core.domain.services.agent_prompt import AgentPromptService

            prompt_service = AgentPromptService(db)
            prompt = prompt_service.get_active_prompt(SCOUT_CHARACTER_DIMENSION)

            self.system_prompt = prompt.system_prompt
            self.temperature = prompt.temperature
            self.max_tokens = prompt.max_tokens
            logger.info(
                f"Loaded character prompt from DB: dimension={SCOUT_CHARACTER_DIMENSION}, "
                f"version={prompt.version}"
            )
        except ValueError:
            logger.debug(
                f"No DB prompt found for {SCOUT_CHARACTER_DIMENSION}, using default"
            )
            self.system_prompt = CHARACTER_SUMMARY_SYSTEM_PROMPT
            self.temperature = default_temperature
            self.max_tokens = default_max_tokens
        except Exception as e:
            logger.warning(f"Error loading prompt from DB: {e}, using default")
            self.system_prompt = CHARACTER_SUMMARY_SYSTEM_PROMPT
            self.temperature = default_temperature
            self.max_tokens = default_max_tokens

    async def summarize(
        self,
        comments: list[ProfileItem],
        max_comments: int = MAX_PROFILE_COMMENTS,
    ) -> CharacterSummaryResult:
        """Summarize user character from their comments.

        Args:
            comments: List of ProfileItem objects (comments only).
            max_comments: Maximum number of comments to analyze.

        Returns:
            CharacterSummaryResult with summary and extracted traits.
        """
        # Filter to comments only and limit
        comment_items = [c for c in comments if c.item_type == "comment"][:max_comments]

        if not comment_items:
            logger.info("No comments available for character summary")
            return CharacterSummaryResult.empty()

        try:
            # Build input prompt
            input_prompt = self._build_input_prompt(comment_items)

            # Configure agent
            config = AgentConfig(
                name="character_summary",
                system_prompt=self.system_prompt,
                output_schema=CharacterSummaryOutput,
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
            if result.success and result.parsed_output:
                output = result.parsed_output
                # Handle both snake_case and camelCase field names from LLM
                summary = output.get("summary", "")
                comm_style = output.get("communication_style") or output.get("communicationStyle", "unknown")
                traits = output.get("personality_traits") or output.get("personalityTraits", [])
                engage_style = output.get("engagement_style") or output.get("engagementStyle", "unknown")
                tone = output.get("emotional_tone") or output.get("emotionalTone", "unknown")
                flags = output.get("red_flags") or output.get("redFlags", [])

                # Generate summary from available data if empty
                if not summary:
                    parts = []
                    if comm_style and comm_style != "unknown":
                        parts.append(f"Communication style: {comm_style}.")
                    if traits:
                        trait_str = traits if isinstance(traits, str) else ", ".join(traits[:5])
                        parts.append(f"Traits: {trait_str}.")
                    if tone and tone != "unknown":
                        parts.append(f"Emotional tone: {tone}.")
                    summary = " ".join(parts) if parts else "Character traits analyzed."

                return CharacterSummaryResult(
                    summary=summary,
                    communication_style=comm_style if isinstance(comm_style, str) else "unknown",
                    personality_traits=traits if isinstance(traits, list) else [],
                    engagement_style=engage_style if isinstance(engage_style, str) else "unknown",
                    emotional_tone=tone if isinstance(tone, str) else "unknown",
                    red_flags=flags if isinstance(flags, list) else [],
                    success=True,
                )
            else:
                error = result.error or "Analysis failed"
                logger.warning(f"Character summary failed: {error}")
                return CharacterSummaryResult.from_error(error)

        except Exception as e:
            logger.exception(f"Character summary error: {e}")
            return CharacterSummaryResult.from_error(str(e))

    def _build_input_prompt(self, comments: list[ProfileItem]) -> str:
        """Build the input prompt for analysis.

        Args:
            comments: List of comment ProfileItems to analyze.

        Returns:
            Formatted input prompt string.
        """
        parts = [
            "Please analyze this Reddit user's comments to understand their communication style and personality.",
            "",
            f"**Number of Comments**: {len(comments)}",
            "",
            "---",
            "",
            "**Comments:**",
            "",
        ]

        for i, comment in enumerate(comments, 1):
            parts.append(f"### Comment {i}")

            if comment.item_created_at:
                parts.append(f"*Posted: {comment.item_created_at.strftime('%Y-%m-%d')}*")

            content = comment.text_content or "(No content)"
            # Truncate very long comments
            if len(content) > 1000:
                content = content[:1000] + "... (truncated)"

            parts.append("")
            parts.append(content)
            parts.append("")
            parts.append("---")
            parts.append("")

        parts.append("Provide your analysis in JSON format.")

        return "\n".join(parts)


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "CharacterSummaryService",
    "CharacterSummaryResult",
    "CharacterSummaryOutput",
    "CHARACTER_SUMMARY_SYSTEM_PROMPT",
    "SCOUT_CHARACTER_DIMENSION",
    "MAX_PROFILE_COMMENTS",
]
