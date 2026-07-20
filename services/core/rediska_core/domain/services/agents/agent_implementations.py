"""Complete agent implementations for all analysis dimensions.

This module provides all 5 dimension agents + meta-analysis coordinator,
all following the same pattern as DemographicsAgent.
"""

import json
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
            agent_input = self._build_agent_input(dimension, input_context)
            input_prompt = agent_input.prompt

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
                input_data=agent_input.audit_record(),
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
            agent_input = self._build_agent_input(dimension, input_context)
            input_prompt = agent_input.prompt

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
                input_data=agent_input.audit_record(),
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
            agent_input = self._build_agent_input(dimension, input_context)
            input_prompt = agent_input.prompt

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
                input_data=agent_input.audit_record(),
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
            agent_input = self._build_agent_input(dimension, input_context)
            input_prompt = agent_input.prompt

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
                input_data=agent_input.audit_record(),
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
    """Advisory meta-analysis coordinator.

    Synthesizes dimension results and the code-computed gate verdict into
    reasoning, strengths, concerns, and a priority level. It does NOT decide
    the final recommendation — that comes from lead_gates.evaluate_gates.
    """

    @staticmethod
    def _field(data: dict[str, Any], key: str) -> Any:
        """Render a field value, or MISSING explicitly — no optimistic defaults."""
        value = data.get(key)
        if value is None:
            return "MISSING"
        return value

    def _format_dimension_results(self, dimension_results: dict[str, Any]) -> str:
        """Format dimension results with clear labels for the LLM.

        Missing or failed dimensions render their fields as MISSING explicitly.
        """
        sections = []
        f = self._field

        # Demographics
        if "demographics" in dimension_results:
            demo = dimension_results["demographics"].get("parsed_output") or {}
            sections.append(f"""<demographics>
POST_AUTHOR_AGE: {f(demo, 'age')}
POST_AUTHOR_GENDER: {f(demo, 'gender')}
POST_AUTHOR_LOCATION: {f(demo, 'location')}
POST_AUTHOR_LOCATION_STATE: {f(demo, 'location_state')}
</demographics>""")

        # Preferences
        if "preferences" in dimension_results:
            prefs = dimension_results["preferences"].get("parsed_output") or {}
            sections.append(f"""<preferences>
HOBBIES: {f(prefs, 'hobbies')}
PREFERRED_HOBBIES_FOUND: {f(prefs, 'preferred_hobbies_found')}
KINKS: {f(prefs, 'kinks')}
PREFERRED_KINKS_FOUND: {f(prefs, 'preferred_kinks_found')}
COMPATIBILITY_SCORE: {f(prefs, 'compatibility_score')}
</preferences>""")

        # Relationship Goals
        if "relationship_goals" in dimension_results:
            goals = dimension_results["relationship_goals"].get("parsed_output") or {}
            sections.append(f"""<relationship_goals>
RELATIONSHIP_INTENT: {f(goals, 'relationship_intent')}
PARTNER_MAX_AGE: {f(goals, 'partner_max_age')}
DEAL_BREAKERS: {f(goals, 'deal_breakers')}
</relationship_goals>""")

        # Risk Assessment
        if "risk_flags" in dimension_results:
            risk = dimension_results["risk_flags"].get("parsed_output") or {}
            sections.append(f"""<risk_assessment>
IS_AUTHENTIC: {f(risk, 'is_authentic')}
ASSESSMENT: {f(risk, 'assessment')}
RED_FLAGS: {f(risk, 'red_flags')}
SCAM_INDICATORS: {f(risk, 'scam_indicators')}
</risk_assessment>""")

        # Intimacy & Compatibility
        if "sexual_preferences" in dimension_results:
            intimate = dimension_results["sexual_preferences"].get("parsed_output") or {}
            sections.append(f"""<intimacy>
POST_AUTHOR_DS_ORIENTATION: {f(intimate, 'ds_orientation')}
KINKS_INTERESTS: {f(intimate, 'kinks_interests')}
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
            # Build advisory prompt with dimension results + gate verdict
            dimension_results = input_context.get("dimension_results", {})
            formatted_results = self._format_dimension_results(dimension_results)

            gate_verdict = input_context.get("gate_verdict") or {}
            verdict_section = ""
            if gate_verdict:
                verdict_section = f"""

<gate_verdict>
{json.dumps(gate_verdict, indent=2, default=str)}
</gate_verdict>"""

            input_prompt = f"""Review this POST AUTHOR analysis:

{formatted_results}{verdict_section}

The final recommendation was already decided deterministically (see gate_verdict).
Provide your advisory synthesis as JSON: reasoning, strengths, concerns, priority_level."""

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
