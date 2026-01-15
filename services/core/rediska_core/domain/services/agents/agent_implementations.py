"""Complete agent implementations for all analysis dimensions.

This module provides all 5 dimension agents + meta-analysis coordinator,
all following the same pattern as DemographicsAgent.
"""

from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rediska_core.domain.models import AgentPrompt
from rediska_core.domain.schemas.multi_agent_analysis import (
    MetaAnalysisOutput,
    PreferencesOutput,
    RelationshipGoalsOutput,
    RiskFlagsOutput,
    SexualPreferencesOutput,
)
from rediska_core.domain.services.agent import AgentConfig

from . import BaseAnalysisAgent


class PreferencesAgent(BaseAnalysisAgent):
    """Analyzes personal preferences and interests."""

    async def analyze(
        self,
        dimension: str,
        input_context: dict[str, Any],
        prompt: AgentPrompt,
        analysis_id: int,
        db: Session,
    ) -> dict[str, Any]:
        """Analyze preferences from input context."""
        try:
            input_prompt = self._build_input_prompt(dimension, input_context)

            config = AgentConfig(
                name="preferences",
                system_prompt=prompt.system_prompt,
                output_schema=PreferencesOutput,
                temperature=prompt.temperature,
                max_tokens=prompt.max_tokens,
                tool_allowlist=[],
            )

            result = await self._run_agent_harness(config, input_prompt)

            if result.get("success") and result.get("parsed_output"):
                try:
                    output = PreferencesOutput(**result["parsed_output"])
                    result["parsed_output"] = output.model_dump()
                except (ValidationError, TypeError):
                    pass

            await self._store_dimension_result(
                analysis_id=analysis_id,
                dimension=dimension,
                prompt_version=prompt.version,
                input_data={"profile_text_excerpt": input_context.get("profile", {}).get("post_text", "")[:1000]},
                output_data=result.get("parsed_output"),
                status="completed" if result.get("success") else "failed",
                error=result.get("error"),
                db=db,
            )

            return result

        except Exception as e:
            await self._store_dimension_result(
                analysis_id=analysis_id,
                dimension=dimension,
                prompt_version=prompt.version,
                input_data={},
                output_data=None,
                status="failed",
                error=str(e),
                db=db,
            )
            return {
                "success": False,
                "error": str(e),
                "output": None,
                "parsed_output": None,
            }


class RelationshipGoalsAgent(BaseAnalysisAgent):
    """Analyzes relationship goals and partner criteria."""

    async def analyze(
        self,
        dimension: str,
        input_context: dict[str, Any],
        prompt: AgentPrompt,
        analysis_id: int,
        db: Session,
    ) -> dict[str, Any]:
        """Analyze relationship goals from input context."""
        try:
            input_prompt = self._build_input_prompt(dimension, input_context)

            config = AgentConfig(
                name="relationship_goals",
                system_prompt=prompt.system_prompt,
                output_schema=RelationshipGoalsOutput,
                temperature=prompt.temperature,
                max_tokens=prompt.max_tokens,
                tool_allowlist=[],
            )

            result = await self._run_agent_harness(config, input_prompt)

            if result.get("success") and result.get("parsed_output"):
                try:
                    output = RelationshipGoalsOutput(**result["parsed_output"])
                    result["parsed_output"] = output.model_dump()
                except (ValidationError, TypeError):
                    pass

            await self._store_dimension_result(
                analysis_id=analysis_id,
                dimension=dimension,
                prompt_version=prompt.version,
                input_data={"lead_title": input_context.get("lead", {}).get("title", "")},
                output_data=result.get("parsed_output"),
                status="completed" if result.get("success") else "failed",
                error=result.get("error"),
                db=db,
            )

            return result

        except Exception as e:
            await self._store_dimension_result(
                analysis_id=analysis_id,
                dimension=dimension,
                prompt_version=prompt.version,
                input_data={},
                output_data=None,
                status="failed",
                error=str(e),
                db=db,
            )
            return {
                "success": False,
                "error": str(e),
                "output": None,
                "parsed_output": None,
            }


class RiskFlagsAgent(BaseAnalysisAgent):
    """Analyzes risk flags, safety concerns, and authenticity."""

    async def analyze(
        self,
        dimension: str,
        input_context: dict[str, Any],
        prompt: AgentPrompt,
        analysis_id: int,
        db: Session,
    ) -> dict[str, Any]:
        """Analyze risk flags from input context."""
        try:
            input_prompt = self._build_input_prompt(dimension, input_context)

            config = AgentConfig(
                name="risk_flags",
                system_prompt=prompt.system_prompt,
                output_schema=RiskFlagsOutput,
                temperature=prompt.temperature,
                max_tokens=prompt.max_tokens,
                tool_allowlist=[],
            )

            result = await self._run_agent_harness(config, input_prompt)

            if result.get("success") and result.get("parsed_output"):
                try:
                    output = RiskFlagsOutput(**result["parsed_output"])
                    result["parsed_output"] = output.model_dump()
                except (ValidationError, TypeError):
                    pass

            await self._store_dimension_result(
                analysis_id=analysis_id,
                dimension=dimension,
                prompt_version=prompt.version,
                input_data={"full_context": "risk assessment"},
                output_data=result.get("parsed_output"),
                status="completed" if result.get("success") else "failed",
                error=result.get("error"),
                db=db,
            )

            return result

        except Exception as e:
            await self._store_dimension_result(
                analysis_id=analysis_id,
                dimension=dimension,
                prompt_version=prompt.version,
                input_data={},
                output_data=None,
                status="failed",
                error=str(e),
                db=db,
            )
            return {
                "success": False,
                "error": str(e),
                "output": None,
                "parsed_output": None,
            }


class SexualPreferencesAgent(BaseAnalysisAgent):
    """Analyzes sexual orientation, preferences, and age preferences."""

    async def analyze(
        self,
        dimension: str,
        input_context: dict[str, Any],
        prompt: AgentPrompt,
        analysis_id: int,
        db: Session,
    ) -> dict[str, Any]:
        """Analyze sexual preferences from input context."""
        try:
            input_prompt = self._build_input_prompt(dimension, input_context)

            config = AgentConfig(
                name="sexual_preferences",
                system_prompt=prompt.system_prompt,
                output_schema=SexualPreferencesOutput,
                temperature=prompt.temperature,
                max_tokens=prompt.max_tokens,
                tool_allowlist=[],
            )

            result = await self._run_agent_harness(config, input_prompt)

            if result.get("success") and result.get("parsed_output"):
                try:
                    output = SexualPreferencesOutput(**result["parsed_output"])
                    result["parsed_output"] = output.model_dump()
                except (ValidationError, TypeError):
                    pass

            await self._store_dimension_result(
                analysis_id=analysis_id,
                dimension=dimension,
                prompt_version=prompt.version,
                input_data={"lead_body": input_context.get("lead", {}).get("body", "")[:1000]},
                output_data=result.get("parsed_output"),
                status="completed" if result.get("success") else "failed",
                error=result.get("error"),
                db=db,
            )

            return result

        except Exception as e:
            await self._store_dimension_result(
                analysis_id=analysis_id,
                dimension=dimension,
                prompt_version=prompt.version,
                input_data={},
                output_data=None,
                status="failed",
                error=str(e),
                db=db,
            )
            return {
                "success": False,
                "error": str(e),
                "output": None,
                "parsed_output": None,
            }


class MetaAnalysisAgent(BaseAnalysisAgent):
    """Meta-analysis coordinator - synthesizes results into final recommendation."""

    async def analyze(
        self,
        dimension: str,
        input_context: dict[str, Any],
        prompt: AgentPrompt,
        analysis_id: int,
        db: Session,
    ) -> dict[str, Any]:
        """Run meta-analysis on dimension results."""
        try:
            # Build meta-analysis prompt with dimension results
            dimension_results = input_context.get("dimension_results", {})
            results_summary = "\n".join([
                f"{dim}: {result.get('parsed_output', {})}"
                for dim, result in dimension_results.items()
            ])

            input_prompt = f"""Synthesize these analysis results:

{results_summary}

Provide a final suitability recommendation in JSON format."""

            config = AgentConfig(
                name="meta_analysis",
                system_prompt=prompt.system_prompt,
                output_schema=MetaAnalysisOutput,
                temperature=prompt.temperature,
                max_tokens=prompt.max_tokens,
                tool_allowlist=[],
            )

            result = await self._run_agent_harness(config, input_prompt)

            if result.get("success") and result.get("parsed_output"):
                try:
                    output = MetaAnalysisOutput(**result["parsed_output"])
                    result["parsed_output"] = output.model_dump()
                except (ValidationError, TypeError):
                    pass

            await self._store_dimension_result(
                analysis_id=analysis_id,
                dimension=dimension,
                prompt_version=prompt.version,
                input_data={"dimensions_analyzed": list(dimension_results.keys())},
                output_data=result.get("parsed_output"),
                status="completed" if result.get("success") else "failed",
                error=result.get("error"),
                db=db,
            )

            return result

        except Exception as e:
            await self._store_dimension_result(
                analysis_id=analysis_id,
                dimension=dimension,
                prompt_version=prompt.version,
                input_data={},
                output_data=None,
                status="failed",
                error=str(e),
                db=db,
            )
            return {
                "success": False,
                "error": str(e),
                "output": None,
                "parsed_output": None,
            }
