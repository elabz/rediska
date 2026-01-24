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

    def _format_dimension_results(self, dimension_results: dict[str, Any]) -> str:
        """Format dimension results with clear labels for the LLM."""
        sections = []

        # Demographics
        if "demographics" in dimension_results:
            demo = dimension_results["demographics"].get("parsed_output", {})
            sections.append(f"""<demographics>
POST_AUTHOR_AGE: {demo.get('age', 'unknown')}
POST_AUTHOR_GENDER: {demo.get('gender', 'unknown')}
POST_AUTHOR_LOCATION: {demo.get('location', 'unknown')}
POST_AUTHOR_LOCATION_NEAR: {demo.get('location_near', False)}
</demographics>""")

        # Preferences
        if "preferences" in dimension_results:
            prefs = dimension_results["preferences"].get("parsed_output", {})
            sections.append(f"""<preferences>
HOBBIES: {prefs.get('hobbies', [])}
PREFERRED_HOBBIES_FOUND: {prefs.get('preferred_hobbies_found', [])}
KINKS: {prefs.get('kinks', [])}
PREFERRED_KINKS_FOUND: {prefs.get('preferred_kinks_found', [])}
COMPATIBILITY_SCORE: {prefs.get('compatibility_score', 0)}
</preferences>""")

        # Relationship Goals
        if "relationship_goals" in dimension_results:
            goals = dimension_results["relationship_goals"].get("parsed_output", {})
            sections.append(f"""<relationship_goals>
RELATIONSHIP_INTENT: {goals.get('relationship_intent', 'unknown')}
PARTNER_MAX_AGE: {goals.get('partner_max_age', 'no_max_age')}
DEAL_BREAKERS: {goals.get('deal_breakers', [])}
</relationship_goals>""")

        # Risk Assessment
        if "risk_flags" in dimension_results:
            risk = dimension_results["risk_flags"].get("parsed_output", {})
            sections.append(f"""<risk_assessment>
IS_AUTHENTIC: {risk.get('is_authentic', True)}
ASSESSMENT: {risk.get('assessment', 'unknown')}
RED_FLAGS: {risk.get('red_flags', [])}
SCAM_INDICATORS: {risk.get('scam_indicators', [])}
</risk_assessment>""")

        # Intimacy & Compatibility
        if "sexual_preferences" in dimension_results:
            intimate = dimension_results["sexual_preferences"].get("parsed_output", {})
            sections.append(f"""<intimacy>
POST_AUTHOR_DS_ORIENTATION: {intimate.get('ds_orientation', 'unknown')}
KINKS_INTERESTS: {intimate.get('kinks_interests', [])}
</intimacy>""")

        return "\n\n".join(sections)

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
            formatted_results = self._format_dimension_results(dimension_results)

            input_prompt = f"""Analyze this POST AUTHOR and decide if they are a suitable match:

{formatted_results}

Apply the decision rules and output your recommendation as JSON."""

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
