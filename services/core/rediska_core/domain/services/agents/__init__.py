"""Analysis agents for multi-dimensional lead evaluation.

This package contains specialized LLM agents for analyzing different
dimensions of lead profiles and generating suitability recommendations.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from rediska_core.domain.models import AgentPrompt, AnalysisDimension

# Import AgentConfig - will be available from domain.services.agent
try:
    from rediska_core.domain.services.agent import AgentConfig, AgentHarness
except ImportError:
    # Fallback if agent module not yet created
    AgentConfig = None
    AgentHarness = None


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

    def _build_input_prompt(
        self,
        dimension: str,
        input_context: dict[str, Any],
    ) -> str:
        """
        Build input prompt for agent from context.

        Args:
            dimension: Agent dimension
            input_context: Input context data

        Returns:
            str: Formatted input prompt
        """
        # Extract relevant content for analysis
        lead_title = input_context.get("lead", {}).get("title", "")
        lead_body = input_context.get("lead", {}).get("body", "")
        post_text = input_context.get("profile", {}).get("post_text", "")
        comment_text = input_context.get("profile", {}).get("comment_text", "")
        summary = input_context.get("profile", {}).get("summary", "")

        # Build content - title wrapped in XML tags, then body
        content_parts = []
        if lead_title:
            content_parts.append(f"<title>{lead_title}</title>")
        if lead_body:
            content_parts.append(f"<body>{lead_body}</body>")
        if summary:
            content_parts.append(f"<profile_summary>{summary}</profile_summary>")
        if post_text:
            content_parts.append(f"<recent_posts>{post_text}</recent_posts>")
        if comment_text:
            content_parts.append(f"<comments>{comment_text}</comments>")

        content = "\n\n".join(content_parts)

        return f"""Analyze this user content:

{content}

Provide your analysis in valid JSON format."""

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
            input_data_json=input_data,
            output_json=output_data,
            prompt_version=prompt_version,
            error_detail=error,
        )
        db.add(dim_record)
        db.flush()
