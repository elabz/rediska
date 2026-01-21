"""Multi-agent lead analysis service orchestration.

Coordinates execution of specialized analysis agents and synthesizes results
into a final suitability recommendation.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from rediska_core.config import get_settings
from rediska_core.domain.models import (
    AgentPrompt,
    AnalysisDimension,
    ExternalAccount,
    LeadAnalysis,
    LeadPost,
    ProfileItem,
    ProfileSnapshot,
)
from rediska_core.domain.services.agent_prompt import AgentPromptService


class MultiAgentAnalysisService:
    """Orchestrates multi-agent lead analysis pipeline."""

    # Agent dimension names
    DIMENSIONS = [
        "demographics",
        "preferences",
        "relationship_goals",
        "risk_flags",
        "sexual_preferences",
    ]

    META_ANALYSIS_DIMENSION = "meta_analysis"

    def __init__(
        self,
        db: Session,
        inference_client: Any,  # InferenceClient
        prompt_service: AgentPromptService | None = None,
        chat_template: str | None = None,
    ) -> None:
        """
        Initialize analysis service.

        Args:
            db: Database session
            inference_client: LLM inference client
            prompt_service: Agent prompt service (creates if None)
            chat_template: Chat template override (default: from settings)
        """
        self.db = db
        self.inference_client = inference_client
        self.prompt_service = prompt_service or AgentPromptService(db)
        # Get chat template from settings if not provided
        settings = get_settings()
        self.chat_template = chat_template or settings.inference_chat_template

    def _normalize_meta_output(self, meta_output: dict[str, Any]) -> dict[str, Any]:
        """Normalize meta-analysis output to expected schema fields.

        Handles variations in LLM output field names and values:
        - Maps suitability_recommendation → recommendation
        - Maps PASS/FAIL → suitable/not_recommended
        - Extracts confidence from various field names
        - Normalizes reasoning to string format

        Args:
            meta_output: Raw parsed output from meta-analysis agent

        Returns:
            Normalized output with expected field names and values
        """
        normalized = dict(meta_output)

        # Map recommendation field names
        rec = None
        for field in ["recommendation", "suitability_recommendation", "final_recommendation"]:
            if field in meta_output and meta_output[field]:
                rec = meta_output[field]
                break

        # Also check nested structures
        if not rec and "suitability_recommendation" in meta_output:
            nested = meta_output["suitability_recommendation"]
            if isinstance(nested, dict):
                rec = nested.get("overall_suitability") or nested.get("recommendation")
                # If no explicit recommendation, infer from score
                if not rec and "overall_suitability_score" in nested:
                    score = nested.get("overall_suitability_score", 0.5)
                    try:
                        score = float(score)
                        if score >= 0.7:
                            rec = "PASS"
                        elif score <= 0.3:
                            rec = "FAIL"
                        else:
                            rec = "NEEDS_REVIEW"
                    except (ValueError, TypeError):
                        pass
            else:
                rec = nested
        if not rec and "final_recommendation" in meta_output:
            nested = meta_output["final_recommendation"]
            if isinstance(nested, dict):
                rec = nested.get("suitable_for_leads")
                if rec is True:
                    rec = "PASS"
                elif rec is False:
                    rec = "FAIL"
            else:
                rec = nested

        # Normalize recommendation values
        if rec:
            rec_upper = str(rec).upper()
            if rec_upper in ["PASS", "SUITABLE", "YES", "TRUE"]:
                normalized["recommendation"] = "suitable"
            elif rec_upper in ["FAIL", "NOT_RECOMMENDED", "NO", "FALSE"]:
                normalized["recommendation"] = "not_recommended"
            elif rec_upper in ["NEEDS_REVIEW", "REVIEW", "MAYBE", "UNCLEAR"]:
                normalized["recommendation"] = "needs_review"
            else:
                normalized["recommendation"] = rec.lower() if isinstance(rec, str) else "needs_review"
        else:
            normalized["recommendation"] = meta_output.get("recommendation", "needs_review")

        # Map confidence field names
        conf = None
        for field in ["confidence", "confidence_score", "overall_confidence", "overall_suitability_score"]:
            if field in meta_output and meta_output[field] is not None:
                conf = meta_output[field]
                break

        # Also check nested structures
        if conf is None and "suitability_recommendation" in meta_output:
            nested = meta_output["suitability_recommendation"]
            if isinstance(nested, dict):
                conf = (
                    nested.get("confidence")
                    or nested.get("overall_suitability_score")
                    or nested.get("suitability_score")
                )

        if conf is not None:
            try:
                normalized["confidence"] = float(conf)
            except (ValueError, TypeError):
                normalized["confidence"] = 0.5
        else:
            # Default confidence based on recommendation
            if normalized["recommendation"] == "suitable":
                normalized["confidence"] = 0.7
            elif normalized["recommendation"] == "not_recommended":
                normalized["confidence"] = 0.7
            else:
                normalized["confidence"] = 0.5

        # Normalize reasoning to string
        reasoning = meta_output.get("reasoning")
        if reasoning is None:
            # Try to extract from nested structures
            if "suitability_recommendation" in meta_output:
                nested = meta_output["suitability_recommendation"]
                if isinstance(nested, dict):
                    reasoning = nested.get("reasoning") or nested.get("notes")
            if not reasoning and "final_recommendation" in meta_output:
                nested = meta_output["final_recommendation"]
                if isinstance(nested, dict):
                    reasoning = nested.get("notes") or nested.get("reasoning")

        if isinstance(reasoning, list):
            normalized["reasoning"] = " ".join(str(r) for r in reasoning)
        elif isinstance(reasoning, dict):
            normalized["reasoning"] = json.dumps(reasoning)
        elif reasoning:
            normalized["reasoning"] = str(reasoning)
        else:
            normalized["reasoning"] = ""

        logger.info(
            f"Normalized meta output: recommendation={normalized['recommendation']}, "
            f"confidence={normalized['confidence']}"
        )

        return normalized

    async def analyze_lead(
        self,
        lead_id: int,
        include_dimensions: list[str] | None = None,
        regenerate_summaries: bool = False,
    ) -> LeadAnalysis:
        """
        Run full multi-agent analysis on a lead.

        Orchestrates the analysis pipeline:
        1. Create analysis record
        2. Fetch lead data and profile snapshot
        3. Generate or reuse user summaries
        4. Run dimension agents in parallel
        5. Run meta-analysis coordinator
        6. Update analysis record with results
        7. Update lead_posts.latest_analysis_id

        Args:
            lead_id: ID of lead to analyze
            include_dimensions: Specific dimensions to analyze (defaults to all)
            regenerate_summaries: If True, regenerate user interest/character summaries
                                  even if they already exist on the lead. Default False.

        Returns:
            LeadAnalysis: Completed analysis with results

        Raises:
            ValueError: If lead or profile data not found
        """
        # Fetch lead
        lead = self.db.query(LeadPost).filter(LeadPost.id == lead_id).first()
        if not lead:
            raise ValueError(f"Lead not found: {lead_id}")

        if not lead.author_account_id:
            raise ValueError(f"Lead has no author account: {lead_id}")

        # Fetch profile snapshot
        profile_snapshot = (
            self.db.query(ProfileSnapshot)
            .filter(ProfileSnapshot.account_id == lead.author_account_id)
            .order_by(ProfileSnapshot.fetched_at.desc())
            .first()
        )
        if not profile_snapshot:
            raise ValueError(
                f"No profile snapshot for account: {lead.author_account_id}"
            )

        # Fetch profile items
        profile_items = self.db.query(ProfileItem).filter(
            ProfileItem.account_id == lead.author_account_id
        ).all()

        # Generate or reuse user summaries
        user_interests_summary = lead.user_interests_summary or ""
        user_character_summary = lead.user_character_summary or ""

        if regenerate_summaries or (not user_interests_summary and not user_character_summary):
            # Generate new summaries from profile items
            try:
                from rediska_core.domain.services.interests_summary import InterestsSummaryService
                from rediska_core.domain.services.character_summary import CharacterSummaryService

                # Generate interests summary from posts
                posts = [item for item in profile_items if item.item_type == "post"]
                if posts:
                    interests_service = InterestsSummaryService(
                        inference_client=self.inference_client,
                        db=self.db,
                    )
                    interests_result = await interests_service.summarize(posts)
                    if interests_result.success:
                        user_interests_summary = interests_result.summary
                        logger.info(f"Generated interests summary for lead {lead_id}")

                # Generate character summary from comments
                comments = [item for item in profile_items if item.item_type == "comment"]
                if comments:
                    character_service = CharacterSummaryService(
                        inference_client=self.inference_client,
                        db=self.db,
                    )
                    character_result = await character_service.summarize(comments)
                    if character_result.success:
                        user_character_summary = character_result.summary
                        logger.info(f"Generated character summary for lead {lead_id}")

                # Update lead with new summaries
                if user_interests_summary:
                    lead.user_interests_summary = user_interests_summary
                if user_character_summary:
                    lead.user_character_summary = user_character_summary
                self.db.flush()

            except Exception as e:
                logger.warning(f"Failed to generate summaries for lead {lead_id}: {e}")
                # Continue without summaries - they're helpful but not required

        # Create analysis record
        analysis = LeadAnalysis(
            lead_id=lead_id,
            account_id=lead.author_account_id,
            started_at=datetime.utcnow(),
            status="running",
            prompt_versions_json={},
        )
        self.db.add(analysis)
        self.db.flush()

        try:
            # Build input context
            input_context = self._build_input_context(
                lead, profile_snapshot, profile_items,
                user_interests_summary=user_interests_summary,
                user_character_summary=user_character_summary,
            )

            # Determine which dimensions to analyze
            dimensions_to_analyze = (
                include_dimensions or self.DIMENSIONS
            )

            # Run dimension agents in parallel
            dimension_results = await self._run_dimension_agents(
                analysis.id, input_context, dimensions_to_analyze
            )

            # Run meta-analysis coordinator
            meta_result = await self._run_meta_analysis(
                analysis.id, dimension_results
            )

            # Update analysis record with results (use parsed_output for JSON fields)
            analysis.demographics_json = dimension_results.get(
                "demographics", {}
            ).get("parsed_output")
            analysis.preferences_json = dimension_results.get(
                "preferences", {}
            ).get("parsed_output")
            analysis.relationship_goals_json = dimension_results.get(
                "relationship_goals", {}
            ).get("parsed_output")
            analysis.risk_flags_json = dimension_results.get(
                "risk_flags", {}
            ).get("parsed_output")
            analysis.sexual_preferences_json = dimension_results.get(
                "sexual_preferences", {}
            ).get("parsed_output")
            analysis.meta_analysis_json = meta_result.get("parsed_output")

            meta_output = meta_result.get("parsed_output")
            if meta_result.get("success") and meta_output:
                # Normalize the output to handle different field names/values from LLM
                normalized = self._normalize_meta_output(meta_output)
                analysis.final_recommendation = normalized.get("recommendation")
                analysis.recommendation_reasoning = normalized.get("reasoning")
                analysis.confidence_score = normalized.get("confidence")
            else:
                analysis.final_recommendation = "needs_review"
                analysis.recommendation_reasoning = (
                    "Analysis failed or produced unclear results"
                )
                analysis.confidence_score = 0.0

            analysis.status = "completed"
            analysis.completed_at = datetime.utcnow()

            # Record prompt versions used
            versions = {}
            for dim in self.DIMENSIONS + [self.META_ANALYSIS_DIMENSION]:
                if dim in dimension_results or dim == self.META_ANALYSIS_DIMENSION:
                    prompt = self.prompt_service.get_active_prompt(dim)
                    versions[dim] = prompt.version
            analysis.prompt_versions_json = versions

            # Update lead_posts
            lead.latest_analysis_id = analysis.id
            lead.analysis_recommendation = analysis.final_recommendation
            lead.analysis_confidence = analysis.confidence_score

            self.db.commit()

            return analysis

        except Exception as e:
            analysis.status = "failed"
            analysis.error_detail = str(e)
            analysis.completed_at = datetime.utcnow()
            self.db.commit()
            raise

    async def _run_dimension_agents(
        self,
        analysis_id: int,
        input_context: dict[str, Any],
        dimensions: list[str],
    ) -> dict[str, dict[str, Any]]:
        """
        Run all dimension agents in parallel.

        Args:
            analysis_id: ID of parent analysis
            input_context: Input data for agents
            dimensions: List of dimensions to analyze

        Returns:
            dict: Results keyed by dimension name
        """
        # Import agent classes here to avoid circular imports
        from rediska_core.domain.services.agents.demographics import (
            DemographicsAgent,
        )
        from rediska_core.domain.services.agents.agent_implementations import (
            PreferencesAgent,
            RelationshipGoalsAgent,
            RiskFlagsAgent,
            SexualPreferencesAgent,
        )

        agent_classes = {
            "demographics": DemographicsAgent,
            "preferences": PreferencesAgent,
            "relationship_goals": RelationshipGoalsAgent,
            "risk_flags": RiskFlagsAgent,
            "sexual_preferences": SexualPreferencesAgent,
        }

        tasks = {}
        for dimension in dimensions:
            if dimension in agent_classes:
                agent_class = agent_classes[dimension]
                agent = agent_class(
                    self.inference_client,
                    chat_template=self.chat_template,
                )
                prompt = self.prompt_service.get_active_prompt(dimension)

                task = agent.analyze(
                    dimension=dimension,
                    input_context=input_context,
                    prompt=prompt,
                    analysis_id=analysis_id,
                    db=self.db,
                )
                tasks[dimension] = task

        # Execute all agents in parallel
        results = {}
        if tasks:
            task_results = await asyncio.gather(
                *tasks.values(), return_exceptions=True
            )
            for dimension, result in zip(tasks.keys(), task_results):
                if isinstance(result, Exception):
                    results[dimension] = {
                        "success": False,
                        "error": str(result),
                        "output": None,
                    }
                else:
                    results[dimension] = result

        return results

    async def _run_meta_analysis(
        self,
        analysis_id: int,
        dimension_results: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Run meta-analysis coordinator agent.

        Feeds all dimension results to meta-analysis agent for final recommendation.

        Args:
            analysis_id: ID of parent analysis
            dimension_results: Results from all dimension agents

        Returns:
            dict: Meta-analysis result with recommendation
        """
        from rediska_core.domain.services.agents.agent_implementations import (
            MetaAnalysisAgent,
        )

        agent = MetaAnalysisAgent(
            self.inference_client,
            chat_template=self.chat_template,
        )
        prompt = self.prompt_service.get_active_prompt(self.META_ANALYSIS_DIMENSION)

        result = await agent.analyze(
            dimension=self.META_ANALYSIS_DIMENSION,
            input_context={"dimension_results": dimension_results},
            prompt=prompt,
            analysis_id=analysis_id,
            db=self.db,
        )

        return result

    def _build_input_context(
        self,
        lead: LeadPost,
        profile_snapshot: ProfileSnapshot,
        profile_items: list[ProfileItem],
        user_interests_summary: str = "",
        user_character_summary: str = "",
    ) -> dict[str, Any]:
        """
        Build unified input context for all agents.

        Combines lead data, profile snapshot, profile items, and summaries
        into a single context dictionary for agent analysis.

        Args:
            lead: Lead post data
            profile_snapshot: Profile snapshot with summary
            profile_items: List of profile items (posts, comments, images)
            user_interests_summary: Summary of user interests from posts
            user_character_summary: Summary of user character from comments

        Returns:
            dict: Unified input context
        """
        # Organize profile items by type
        items_by_type = {}
        for item_type in ["post", "comment", "image"]:
            items_by_type[item_type] = [
                {
                    "id": item.id,
                    "text": item.text_content,
                    "created_at": item.item_created_at.isoformat()
                    if item.item_created_at
                    else None,
                }
                for item in profile_items
                if item.item_type == item_type and item.text_content
            ]

        # Build context
        context = {
            "lead": {
                "id": lead.id,
                "title": lead.title,
                "body": lead.body_text,
                "url": lead.post_url,
                "created_at": lead.post_created_at.isoformat()
                if lead.post_created_at
                else None,
            },
            "profile": {
                "post_text": " ".join(
                    [
                        item.get("text", "")
                        for item in items_by_type.get("post", [])
                        if item.get("text")
                    ]
                ),
                "comment_text": " ".join(
                    [
                        item.get("text", "")
                        for item in items_by_type.get("comment", [])
                        if item.get("text")
                    ]
                ),
                "summary": profile_snapshot.summary_text or "",
            },
            "summaries": {
                "user_interests": user_interests_summary,
                "user_character": user_character_summary,
            },
            "items_by_type": items_by_type,
        }

        return context
