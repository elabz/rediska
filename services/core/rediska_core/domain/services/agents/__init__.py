"""Analysis agents for multi-dimensional lead evaluation.

This package contains specialized LLM agents for analyzing different
dimensions of lead profiles and generating suitability recommendations.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from rediska_core.config import get_settings
from rediska_core.domain.models import AgentPrompt, AnalysisDimension

# Import AgentConfig - will be available from domain.services.agent
try:
    from rediska_core.domain.services.agent import AgentConfig, AgentHarness
except ImportError:
    # Fallback if agent module not yet created
    AgentConfig = None
    AgentHarness = None


@dataclass(frozen=True)
class ContextSpec:
    """Which optional context sections a dimension agent receives.

    The lead ``<title>``/``<body>`` are always included and are not listed here.
    ``sections`` is ordered — it is also the render order.
    """

    sections: tuple[str, ...] = ()
    max_posts: int | None = None
    per_item_chars: int | None = None


# Section names
SECTION_PROFILE_SUMMARY = "profile_summary"
SECTION_INTERESTS_SUMMARY = "interests_summary"
SECTION_CHARACTER_SUMMARY = "character_summary"
SECTION_ACCOUNT_METADATA = "account_metadata"
SECTION_RECENT_POSTS = "recent_posts"

# Per-dimension context specification. Raw comment dumps are deliberately absent
# from every spec: the character summary is distilled from exactly those comments
# and the other dimensions never needed them.
DIMENSION_CONTEXT_SPECS: dict[str, ContextSpec] = {
    "demographics": ContextSpec(sections=(SECTION_PROFILE_SUMMARY,)),
    "preferences": ContextSpec(
        sections=(SECTION_INTERESTS_SUMMARY, SECTION_RECENT_POSTS),
    ),
    "sexual_preferences": ContextSpec(
        sections=(SECTION_INTERESTS_SUMMARY, SECTION_RECENT_POSTS),
    ),
    "relationship_goals": ContextSpec(sections=(SECTION_INTERESTS_SUMMARY,)),
    "risk_flags": ContextSpec(
        sections=(SECTION_ACCOUNT_METADATA, SECTION_CHARACTER_SUMMARY),
    ),
}

# Used for any dimension not in the table (e.g. a new dimension added before its
# spec entry). Conservative: the same summary the old unbounded builder led with.
DEFAULT_CONTEXT_SPEC = ContextSpec(sections=(SECTION_PROFILE_SUMMARY,))

# Order in which sections are sacrificed when the assembled input exceeds the
# budget. ``recent_posts`` is trimmed item-by-item (oldest first) before any
# section is dropped whole; account metadata is tiny and highest-signal, so it
# goes last. The lead title/body are never trimmed.
_SECTION_DROP_ORDER = (
    SECTION_CHARACTER_SUMMARY,
    SECTION_PROFILE_SUMMARY,
    SECTION_INTERESTS_SUMMARY,
    SECTION_ACCOUNT_METADATA,
)


@dataclass
class AssembledInput:
    """The prompt actually sent to a dimension agent, plus audit metadata."""

    prompt: str
    sections: list[str] = field(default_factory=list)
    total_chars: int = 0

    def audit_record(self) -> dict[str, Any]:
        """Audit payload for ``analysis_dimensions.input_data_json``."""
        return {
            "prompt_excerpt": self.prompt[:2000],
            "sections": self.sections,
            "total_chars": self.total_chars,
        }


class BaseAnalysisAgent(ABC):
    """Base class for all analysis agents."""

    def __init__(
        self,
        inference_client: Any,
        chat_template: str | None = None,
    ) -> None:
        """
        Initialize agent.

        Args:
            inference_client: LLM inference client
            chat_template: Chat template name for response parsing (llama3, qwen_thinking, etc.)
        """
        self.inference_client = inference_client
        self.chat_template = chat_template
        # Execution attempt number (1 = first run, 2 = automatic retry);
        # recorded in analysis_dimensions.input_data_json.
        self.attempt = 1

    @abstractmethod
    async def analyze(
        self,
        dimension: str,
        input_context: dict[str, Any],
        prompt: AgentPrompt,
        analysis_id: int,
        db: Session,
    ) -> dict[str, Any]:
        """
        Run analysis on input context.

        Args:
            dimension: Agent dimension name
            input_context: Input data to analyze
            prompt: Agent prompt configuration
            analysis_id: Parent analysis ID (for tracking)
            db: Database session

        Returns:
            dict: Result with success, output, parsed_output, error, etc.
        """
        pass

    async def _run_agent_harness(
        self,
        config: AgentConfig,
        input_prompt: str,
    ) -> dict[str, Any]:
        """
        Run the agent harness with given configuration.

        Args:
            config: Agent configuration
            input_prompt: Input prompt for agent

        Returns:
            dict: Agent result
        """
        # Inject chat_template from self if not set in config
        if self.chat_template and not config.chat_template:
            config.chat_template = self.chat_template

        harness = AgentHarness(
            config=config,
            inference_client=self.inference_client,
        )

        result = await harness.run(input_prompt)

        # Log full agent output for debugging
        logger.info(f"Agent '{config.name}' raw output:\n{result.output[:2000]}...")
        logger.info(f"Agent '{config.name}' success={result.success}, error={result.error}")
        logger.info(f"Agent '{config.name}' parsed_output={result.parsed_output}")

        return {
            "success": result.success,
            "output": result.output,
            "parsed_output": result.parsed_output,
            "error": result.error,
            "model_info": result.model_info,
            "raw_response": result.output,
        }

    @staticmethod
    def _select_recent_posts(
        input_context: dict[str, Any],
        max_posts: int,
        per_item_chars: int,
    ) -> list[str]:
        """Newest-first author posts, each capped at ``per_item_chars``.

        Prefers the structured ``items_by_type["post"]`` list (which carries
        timestamps); falls back to the flat ``profile.post_text`` blob as a
        single item when only that is available.
        """
        items = (input_context.get("items_by_type") or {}).get("post") or []
        if not items:
            post_text = (input_context.get("profile") or {}).get("post_text") or ""
            items = [{"text": post_text}] if post_text.strip() else []

        # Newest first. Items without a timestamp sort as oldest; the sort is
        # stable, so ties keep their input order (the scout path puts the
        # discovery post first).
        def sort_key(item: dict[str, Any]) -> tuple[int, str]:
            created = item.get("created_at") or ""
            return (1 if created else 0, str(created))

        ordered = sorted(items, key=sort_key, reverse=True)

        selected = []
        for item in ordered[:max_posts]:
            text = (item.get("text") or "").strip()
            if text:
                selected.append(text[:per_item_chars])
        return selected

    @staticmethod
    def _render_account_metadata(input_context: dict[str, Any]) -> str:
        """Structured account signals — the strongest scam/authenticity cues."""
        profile = input_context.get("profile") or {}

        parts = []
        karma = profile.get("karma")
        if karma is not None:
            parts.append(f"karma={karma}")

        created_at = profile.get("created_at")
        age_days = BaseAnalysisAgent._account_age_days(created_at)
        if age_days is not None:
            parts.append(f"account_age_days={age_days}")

        if profile.get("is_verified") is not None:
            parts.append(f"verified={bool(profile.get('is_verified'))}")

        bio = (profile.get("bio") or "").strip()
        if bio:
            parts.append(f"bio={bio}")

        return ", ".join(parts)

    @staticmethod
    def _account_age_days(created_at: Any) -> int | None:
        """Days since account creation, from an ISO string or datetime."""
        if not created_at:
            return None
        value = created_at
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        if not isinstance(value, datetime):
            return None
        now = datetime.now(timezone.utc)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return max(0, (now - value).days)

    def _build_agent_input(
        self,
        dimension: str,
        input_context: dict[str, Any],
    ) -> AssembledInput:
        """
        Assemble the model input for a dimension per its `ContextSpec`.

        The lead title and body are always included and never trimmed. Optional
        sections come from `DIMENSION_CONTEXT_SPECS`; the assembled result is
        capped at `ANALYSIS_CONTEXT_MAX_CHARS`, dropping the oldest posts first
        and then whole sections in `_SECTION_DROP_ORDER`.

        Args:
            dimension: Agent dimension
            input_context: Input context data

        Returns:
            AssembledInput: prompt plus the sections/size actually sent
        """
        settings = get_settings()
        spec = DIMENSION_CONTEXT_SPECS.get(dimension, DEFAULT_CONTEXT_SPEC)

        lead = input_context.get("lead") or {}
        lead_title = lead.get("title") or ""
        lead_body = lead.get("body") or ""

        # Sections the spec asks for, in render order, keyed by name.
        rendered: dict[str, str] = {}
        posts: list[str] = []

        for section in spec.sections:
            if section == SECTION_PROFILE_SUMMARY:
                text = (input_context.get("profile") or {}).get("summary") or ""
                if text:
                    rendered[section] = text
            elif section == SECTION_INTERESTS_SUMMARY:
                text = (input_context.get("summaries") or {}).get("user_interests") or ""
                if text:
                    rendered[section] = text
            elif section == SECTION_CHARACTER_SUMMARY:
                text = (input_context.get("summaries") or {}).get("user_character") or ""
                if text:
                    rendered[section] = text
            elif section == SECTION_ACCOUNT_METADATA:
                text = self._render_account_metadata(input_context)
                if text:
                    rendered[section] = text
            elif section == SECTION_RECENT_POSTS:
                posts = self._select_recent_posts(
                    input_context,
                    max_posts=spec.max_posts or settings.analysis_max_recent_posts,
                    per_item_chars=(
                        spec.per_item_chars or settings.analysis_post_item_chars
                    ),
                )
                if posts:
                    rendered[section] = ""  # filled in by _assemble

        def assemble() -> tuple[str, list[str]]:
            parts = []
            names = []
            if lead_title:
                parts.append(f"<title>{lead_title}</title>")
                names.append("title")
            if lead_body:
                parts.append(f"<body>{lead_body}</body>")
                names.append("body")
            for name in spec.sections:
                if name not in rendered:
                    continue
                if name == SECTION_RECENT_POSTS:
                    if not posts:
                        continue
                    body = "\n---\n".join(posts)
                else:
                    body = rendered[name]
                parts.append(f"<{name}>{body}</{name}>")
                names.append(name)
            content = "\n\n".join(parts)
            return (
                f"Analyze this user content:\n\n{content}\n\n"
                "Provide your analysis in valid JSON format.",
                names,
            )

        prompt, names = assemble()
        budget = settings.analysis_context_max_chars

        # Over budget: shed the oldest posts one at a time, then whole sections.
        while len(prompt) > budget and posts:
            posts.pop()  # newest-first, so the tail is the oldest
            if not posts:
                rendered.pop(SECTION_RECENT_POSTS, None)
            prompt, names = assemble()

        for name in _SECTION_DROP_ORDER:
            if len(prompt) <= budget:
                break
            if rendered.pop(name, None) is not None:
                prompt, names = assemble()

        if len(prompt) > budget:
            # Only the lead itself remains, and it is never trimmed.
            logger.warning(
                f"Dimension '{dimension}' input is {len(prompt)} chars, over the "
                f"{budget} budget, from the lead post alone; sending untrimmed."
            )

        return AssembledInput(prompt=prompt, sections=names, total_chars=len(prompt))

    def _build_input_prompt(
        self,
        dimension: str,
        input_context: dict[str, Any],
    ) -> str:
        """Build the input prompt for a dimension agent (see `_build_agent_input`)."""
        return self._build_agent_input(dimension, input_context).prompt

    async def _store_dimension_result(
        self,
        analysis_id: int | None,
        dimension: str,
        prompt_version: int,
        input_data: dict[str, Any],
        output_data: dict[str, Any] | None,
        status: str,
        error: str | None,
        db: Session | None,
    ) -> None:
        """
        Store dimension analysis result in database.

        Args:
            analysis_id: Parent analysis ID (if None, skips DB storage)
            dimension: Dimension name
            prompt_version: Prompt version used
            input_data: Input data used
            output_data: Output data from agent
            status: Analysis status
            error: Error message if failed
            db: Database session (if None, skips DB storage)
        """
        # Skip DB storage if no analysis_id or db session
        # This allows scout pipeline to run agents without persisting dimension records
        if analysis_id is None or db is None:
            logger.debug(f"Skipping dimension storage for {dimension} (no analysis_id)")
            return

        dim_record = AnalysisDimension(
            analysis_id=analysis_id,
            dimension=dimension,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            status=status,
            input_data_json={**input_data, "attempt": self.attempt},
            output_json=output_data,
            prompt_version=prompt_version,
            error_detail=error,
        )
        db.add(dim_record)
        db.flush()
