"""Demographics analysis agent - extracts age, gender, location."""

from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rediska_core.domain.models import AgentPrompt
from rediska_core.domain.schemas.multi_agent_analysis import (
    DemographicsOutput,
)
from rediska_core.domain.services.agent import AgentConfig
from rediska_core.domain.services.geocoding import classify_location

from . import BaseAnalysisAgent


class DemographicsAgent(BaseAnalysisAgent):
    """Analyzes demographics - age, gender, location."""

    async def analyze(
        self,
        dimension: str,
        input_context: dict[str, Any],
        prompt: AgentPrompt,
        analysis_id: int,
        db: Session,
    ) -> dict[str, Any]:
        """
        Analyze demographics from input context.

        Extracts age, gender, and location information from lead/profile content.

        Args:
            dimension: "demographics"
            input_context: Profile and lead data
            prompt: Agent prompt configuration
            analysis_id: Parent analysis ID
            db: Database session

        Returns:
            dict: Analysis result
        """
        try:
            # Build input prompt
            agent_input = self._build_agent_input(dimension, input_context)
            input_prompt = agent_input.prompt

            # Configure agent
            config = AgentConfig(
                name="demographics",
                system_prompt=prompt.system_prompt,
                output_schema=DemographicsOutput,
                temperature=prompt.temperature,
                max_tokens=prompt.max_tokens,
                tool_allowlist=[],
            )

            # Run agent
            result = await self._run_agent_harness(config, input_prompt)

            # Try to validate output
            if result.get("success") and result.get("parsed_output"):
                try:
                    output = DemographicsOutput(**result["parsed_output"])

                    # Post-process: three-state classification from the offline
                    # geocoder; location_near kept as derived bool for the UI.
                    geo = classify_location(output.location)
                    output.location_state = geo["location_state"]
                    output.location_near = geo["location_near"]
                    output.distance_miles = geo["distance_miles"]

                    result["parsed_output"] = output.model_dump()
                except (ValidationError, TypeError):
                    # Schema validation failed, but agent returned something
                    pass

            # Store result in database
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
            # Store error result
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
