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
from rediska_core.domain.services.external_listing import ensure_lead_listing_content
from rediska_core.domain.services.lead_gates import (
    GateVerdict,
    UserConstraints,
    evaluate_gates,
)
from rediska_core.domain.services.lead_priority import priority_for_analysis


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
        """Normalize ADVISORY meta-analysis output to expected schema fields.

        The meta agent is advisory only: the final recommendation and gating
        confidence are computed by the deterministic gate evaluator
        (lead_gates.evaluate_gates), never taken from this output. This
        normalization exists purely so the advisory fields display
        consistently. No default confidence is supplied for a missing value.

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
                val = meta_output[field]
                if isinstance(val, dict):
                    # Extract recommendation from nested dict
                    rec = val.get("overall_suitability") or val.get("recommendation")
                    if not rec and field == "final_recommendation":
                        suitable = val.get("suitable_for_leads")
                        if suitable is True:
                            rec = "PASS"
                        elif suitable is False:
                            rec = "FAIL"
                    # If no explicit recommendation, infer from score
                    if not rec and "overall_suitability_score" in val:
                        try:
                            score = float(val["overall_suitability_score"])
                            if score >= 0.7:
                                rec = "PASS"
                            elif score <= 0.3:
                                rec = "FAIL"
                            else:
                                rec = "NEEDS_REVIEW"
                        except (ValueError, TypeError):
                            pass
                else:
                    rec = val
                if rec:
                    break

        # Normalize recommendation values (advisory only — never gates)
        if rec:
            rec_upper = str(rec).upper()
            if rec_upper in ["PASS", "SUITABLE", "YES", "TRUE"]:
                normalized["recommendation"] = "suitable"
            elif rec_upper in ["FAIL", "NOT_RECOMMENDED", "NO", "FALSE"]:
                normalized["recommendation"] = "not_recommended"
            elif rec_upper in ["NEEDS_REVIEW", "REVIEW", "MAYBE", "UNCLEAR"]:
                normalized["recommendation"] = "needs_review"
            else:
                normalized["recommendation"] = rec.lower() if isinstance(rec, str) else None
        else:
            normalized["recommendation"] = meta_output.get("recommendation")

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

        # Advisory only: no default substitutes for a missing model confidence
        if conf is not None:
            try:
                normalized["confidence"] = float(conf)
            except (ValueError, TypeError):
                normalized["confidence"] = None
        else:
            normalized["confidence"] = None

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

        # Leads saved before listing resolution existed may still hold a bare
        # link; resolve once so agent context contains real content.
        ensure_lead_listing_content(self.db, lead)

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

            # Run dimension agents in parallel (failed dimensions retried once)
            dimension_results = await self._run_dimension_agents(
                analysis.id, input_context, dimensions_to_analyze
            )

            # Deterministic hard gates decide the verdict (fail-closed)
            verdict = evaluate_gates(
                dimension_results, UserConstraints.from_settings()
            )

            # Run meta-analysis coordinator (advisory only; failure tolerated)
            meta_result = await self._run_meta_analysis(
                analysis.id, dimension_results, gate_verdict=verdict
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
            # Store advisory meta output alongside the gate verdict
            meta_output = meta_result.get("parsed_output")
            meta_json = dict(meta_output) if isinstance(meta_output, dict) else {}
            meta_json["gate_verdict"] = verdict.to_dict()
            analysis.meta_analysis_json = meta_json

            # Verdict and score come from the deterministic gate evaluator;
            # meta output is advisory context and cannot flip them.
            analysis.final_recommendation = verdict.recommendation
            analysis.confidence_score = verdict.score

            reasoning_parts = [verdict.summary()]
            if meta_result.get("success") and meta_output:
                normalized = self._normalize_meta_output(meta_output)
                if normalized.get("reasoning"):
                    reasoning_parts.append(f"Advisory: {normalized['reasoning']}")
            analysis.recommendation_reasoning = " | ".join(reasoning_parts)

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
            lead.priority, lead.compatibility_score = priority_for_analysis(
                dimension_results, meta_output, verdict
            )

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

        def make_task(dimension: str, attempt: int):
            agent = agent_classes[dimension](
                self.inference_client,
                chat_template=self.chat_template,
            )
            agent.attempt = attempt
            prompt = self.prompt_service.get_active_prompt(dimension)
            return agent.analyze(
                dimension=dimension,
                input_context=input_context,
                prompt=prompt,
                analysis_id=analysis_id,
                db=self.db,
            )

        async def gather_dimensions(
            dims: list[str], attempt: int
        ) -> dict[str, dict[str, Any]]:
            tasks = {d: make_task(d, attempt) for d in dims if d in agent_classes}
            gathered: dict[str, dict[str, Any]] = {}
            if tasks:
                task_results = await asyncio.gather(
                    *tasks.values(), return_exceptions=True
                )
                for dimension, result in zip(tasks.keys(), task_results):
                    if isinstance(result, BaseException):
                        gathered[dimension] = {
                            "success": False,
                            "error": str(result),
                            "output": None,
                            "parsed_output": None,
                        }
                    else:
                        gathered[dimension] = result
            return gathered

        results = await gather_dimensions(list(dimensions), attempt=1)

        # One automatic retry for failed dimensions (fail-closed after that).
        # Both attempts are recorded in analysis_dimensions.
        failed = [d for d, r in results.items() if not r.get("success")]
        if failed:
            logger.warning(
                f"Retrying failed dimension agents once: {failed}"
            )
            retry_results = await gather_dimensions(failed, attempt=2)
            results.update(retry_results)

        return results

    async def _run_meta_analysis(
        self,
        analysis_id: int,
        dimension_results: dict[str, Any],
        gate_verdict: GateVerdict | None = None,
    ) -> dict[str, Any]:
        """
        Run the ADVISORY meta-analysis coordinator agent.

        Feeds dimension results plus the code-computed gate verdict to the
        meta agent, which synthesizes reasoning, strengths, concerns, and a
        priority level. Its output never changes the gate verdict, and a
        meta-agent failure does not block the analysis.

        Args:
            analysis_id: ID of parent analysis
            dimension_results: Results from all dimension agents
            gate_verdict: The deterministic gate evaluator's verdict

        Returns:
            dict: Advisory meta-analysis result
        """
        from rediska_core.domain.services.agents.agent_implementations import (
            MetaAnalysisAgent,
        )

        agent = MetaAnalysisAgent(
            self.inference_client,
            chat_template=self.chat_template,
        )
        prompt = self.prompt_service.get_active_prompt(self.META_ANALYSIS_DIMENSION)

        input_context: dict[str, Any] = {"dimension_results": dimension_results}
        if gate_verdict is not None:
            input_context["gate_verdict"] = gate_verdict.to_dict()

        try:
            result = await agent.analyze(
                dimension=self.META_ANALYSIS_DIMENSION,
                input_context=input_context,
                prompt=prompt,
                analysis_id=analysis_id,
                db=self.db,
            )
        except Exception as e:
            logger.error(f"Advisory meta-analysis failed: {e}")
            result = {
                "success": False,
                "error": str(e),
                "output": None,
                "parsed_output": None,
            }

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

        # Account metadata for the risk_flags agent. `signals_json` is a dict of
        # provider profile fields when written by AnalysisService, but a list of
        # signal objects when written by ProfileSummaryService — only the former
        # carries account metadata.
        signals = profile_snapshot.signals_json
        account_signals = signals if isinstance(signals, dict) else {}

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
                "username": account_signals.get("username"),
                "bio": account_signals.get("bio") or "",
                "karma": account_signals.get("karma"),
                "created_at": account_signals.get("created_at"),
                "is_verified": account_signals.get("is_verified"),
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
