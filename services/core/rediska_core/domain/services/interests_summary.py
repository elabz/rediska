"""Interests summary service for analyzing user posts.

This service summarizes a user's interests, hobbies, and activities
based on their Reddit posts. Used by the Scout Watch pipeline to
enrich the analysis context before running the 6-agent multi-agent analysis.

Usage:
    service = InterestsSummaryService(inference_client=client, db=db)

    summary = await service.summarize(posts)
    # Returns: "User is interested in gaming, fitness, and cooking..."
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


MAX_PROFILE_POSTS = 20
SCOUT_INTERESTS_DIMENSION = "scout_interests_summary"


# =============================================================================
# OUTPUT SCHEMA
# =============================================================================


class InterestsSummaryOutput(BaseModel):
    """Output schema for interests summary."""

    model_config = {"populate_by_name": True}

    summary: str = Field(
        default="",
        description="A 2-3 paragraph summary of the user's interests, hobbies, and activities"
    )
    main_interests: list[str] = Field(
        default_factory=list,
        alias="mainInterests",
        description="List of main interests/hobbies identified"
    )
    subreddits_frequented: list[str] = Field(
        default_factory=list,
        alias="subredditsFrequented",
        description="Subreddits the user frequently posts in"
    )
    posting_patterns: Optional[str] = Field(
        None,
        alias="postingPatterns",
        description="Notable patterns in posting behavior"
    )


# =============================================================================
# RESULT DATACLASS
# =============================================================================


@dataclass
class InterestsSummaryResult:
    """Result of an interests summary analysis."""

    summary: str
    main_interests: list[str]
    subreddits_frequented: list[str]
    posting_patterns: Optional[str]
    success: bool = True
    error: Optional[str] = None

    @classmethod
    def from_error(cls, error: str) -> "InterestsSummaryResult":
        """Create a failed result from an error."""
        return cls(
            summary="",
            main_interests=[],
            subreddits_frequented=[],
            posting_patterns=None,
            success=False,
            error=error,
        )

    @classmethod
    def empty(cls) -> "InterestsSummaryResult":
        """Create an empty result when no posts are available."""
        return cls(
            summary="No posts available for analysis.",
            main_interests=[],
            subreddits_frequented=[],
            posting_patterns=None,
            success=True,
        )


# =============================================================================
# DEFAULT PROMPT
# =============================================================================


INTERESTS_SUMMARY_SYSTEM_PROMPT = """You are an analyst that summarizes a Reddit user's interests and activities based on their post history.

Your task is to analyze the user's posts and provide a comprehensive summary of:

1. **Main Interests & Hobbies**: What activities, hobbies, or topics does this person engage in?
2. **Topics Discussed**: What subjects do they frequently discuss or are passionate about?
3. **Communities**: Which subreddits do they participate in and what does this reveal?
4. **Posting Patterns**: Any notable patterns in their posting behavior?

Guidelines:
- Focus on FACTUAL observations from the content provided
- Be objective and avoid assumptions beyond what's evident
- Note both positive interests and any concerning patterns
- Summarize in 2-3 paragraphs that would help someone understand this person's lifestyle

Respond in JSON format matching the output schema."""


# =============================================================================
# SERVICE
# =============================================================================


class InterestsSummaryService:
    """Service for summarizing user interests from their posts.

    Analyzes a user's Reddit posts to extract their interests,
    hobbies, activities, and posting patterns.

    Supports DB-backed prompts: if a db session is provided, it will look up
    the active prompt for the "scout_interests_summary" dimension.
    """

    def __init__(
        self,
        inference_client: InferenceClient,
        db: Optional[Session] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ):
        """Initialize the interests summary service.

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
            self.system_prompt = system_prompt or INTERESTS_SUMMARY_SYSTEM_PROMPT
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
            prompt = prompt_service.get_active_prompt(SCOUT_INTERESTS_DIMENSION)

            self.system_prompt = prompt.system_prompt
            self.temperature = prompt.temperature
            self.max_tokens = prompt.max_tokens
            logger.info(
                f"Loaded interests prompt from DB: dimension={SCOUT_INTERESTS_DIMENSION}, "
                f"version={prompt.version}"
            )
        except ValueError:
            logger.debug(
                f"No DB prompt found for {SCOUT_INTERESTS_DIMENSION}, using default"
            )
            self.system_prompt = INTERESTS_SUMMARY_SYSTEM_PROMPT
            self.temperature = default_temperature
            self.max_tokens = default_max_tokens
        except Exception as e:
            logger.warning(f"Error loading prompt from DB: {e}, using default")
            self.system_prompt = INTERESTS_SUMMARY_SYSTEM_PROMPT
            self.temperature = default_temperature
            self.max_tokens = default_max_tokens

    async def summarize(
        self,
        posts: list[ProfileItem],
        max_posts: int = MAX_PROFILE_POSTS,
    ) -> InterestsSummaryResult:
        """Summarize user interests from their posts.

        Args:
            posts: List of ProfileItem objects (posts only).
            max_posts: Maximum number of posts to analyze.

        Returns:
            InterestsSummaryResult with summary and extracted interests.
        """
        # Filter to posts only and limit
        post_items = [p for p in posts if p.item_type == "post"][:max_posts]

        if not post_items:
            logger.info("No posts available for interests summary")
            return InterestsSummaryResult.empty()

        try:
            # Build input prompt
            input_prompt = self._build_input_prompt(post_items)

            # Configure agent
            config = AgentConfig(
                name="interests_summary",
                system_prompt=self.system_prompt,
                output_schema=InterestsSummaryOutput,
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
                main_interests = output.get("main_interests") or output.get("mainInterests", [])
                subreddits = output.get("subreddits_frequented") or output.get("subredditsFrequented", [])
                patterns = output.get("posting_patterns") or output.get("postingPatterns")

                # Generate summary from available data if empty
                if not summary and main_interests:
                    summary = f"User interests include: {', '.join(main_interests[:5])}."
                    if subreddits:
                        summary += f" Active in: {', '.join(subreddits[:3])}."

                return InterestsSummaryResult(
                    summary=summary,
                    main_interests=main_interests if isinstance(main_interests, list) else [],
                    subreddits_frequented=subreddits if isinstance(subreddits, list) else [],
                    posting_patterns=patterns if isinstance(patterns, str) else None,
                    success=True,
                )
            else:
                error = result.error or "Analysis failed"
                logger.warning(f"Interests summary failed: {error}")
                return InterestsSummaryResult.from_error(error)

        except Exception as e:
            logger.exception(f"Interests summary error: {e}")
            return InterestsSummaryResult.from_error(str(e))

    def _build_input_prompt(self, posts: list[ProfileItem]) -> str:
        """Build the input prompt for analysis.

        Args:
            posts: List of post ProfileItems to analyze.

        Returns:
            Formatted input prompt string.
        """
        parts = [
            "Please analyze this Reddit user's posts to understand their interests and activities.",
            "",
            f"**Number of Posts**: {len(posts)}",
            "",
            "---",
            "",
            "**Posts:**",
            "",
        ]

        for i, post in enumerate(posts, 1):
            # Extract subreddit from external_item_id if possible
            # Reddit post IDs are typically in format like "t3_xxxxx"
            parts.append(f"### Post {i}")

            if post.item_created_at:
                parts.append(f"*Posted: {post.item_created_at.strftime('%Y-%m-%d')}*")

            content = post.text_content or "(No content)"
            # Truncate very long posts
            if len(content) > 2000:
                content = content[:2000] + "... (truncated)"

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
    "InterestsSummaryService",
    "InterestsSummaryResult",
    "InterestsSummaryOutput",
    "INTERESTS_SUMMARY_SYSTEM_PROMPT",
    "SCOUT_INTERESTS_DIMENSION",
    "MAX_PROFILE_POSTS",
]
