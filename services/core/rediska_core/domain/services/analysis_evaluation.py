"""Human evaluation of agent decisions.

Records explicit, append-only human verdicts on the final recommendation and on
each dimension of a completed analysis subject (a ``lead_analyses`` row or a
``scout_watch_posts`` row carrying dimension results), serves the review queue,
computes agreement metrics per dimension and per prompt version, and exports
the labelled cases as JSONL.

Evaluations never change an analysis result, a lead status, or a scout post
status. Content is stored and exported verbatim (research-content-policy).
"""

from __future__ import annotations

import base64
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Optional

from sqlalchemy import and_, exists, select
from sqlalchemy.orm import Session, joinedload

from rediska_core.api.schemas.evaluations import (
    EVALUABLE_DIMENSIONS,
    REASON_TAGS,
    DimensionSummary,
    EvaluationCreate,
    EvaluationResponse,
    EvaluationSummary,
    GateResultItem,
    MissingInfoItem,
    PromptVersionMetrics,
    QueueItem,
    QueueResponse,
    TrendPoint,
    VerdictCounts,
)
from rediska_core.domain.models import (
    AnalysisDimension,
    AnalysisEvaluation,
    AuditLog,
    LeadAnalysis,
    LeadPost,
    ScoutWatchPost,
)
from rediska_core.domain.schemas.evaluation import EffectiveEvaluation, ModelInput
from rediska_core.domain.services.agent_prompt import AgentPromptService

logger = logging.getLogger(__name__)

__all__ = [
    "REASON_TAGS",
    "EVALUABLE_DIMENSIONS",
    "FINAL_KEY",
    "AnalysisEvaluationService",
    "EvaluationSubjectNotFound",
    "EvaluationValidationError",
]

# Key used for the final-verdict (dimension NULL) entry in effective maps.
FINAL_KEY = "final"

RECOMMENDATIONS = ("suitable", "not_recommended", "needs_review")

# Contradictions are only boosted to the front when this recent; older ones
# take their place in the newest-first order like everything else. (Only a
# small fraction of analyses will ever be evaluated, so recency matters more
# than exhaustiveness.)
CONTRADICTION_BOOST_DAYS = 30

QUEUE_SORTS = ("newest", "stratified")

REASON_CONTRADICTION_IGNORED = "contradiction_ignored_suitable"
REASON_CONTRADICTION_PROMOTED = "contradiction_promoted_not_suitable"
REASON_SAMPLE = "sample"


class EvaluationSubjectNotFound(ValueError):
    """The subject does not exist or carries no analysis to evaluate."""


class EvaluationValidationError(ValueError):
    """Request is well-formed but semantically invalid."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_naive(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _dim_key(dimension: Optional[str]) -> str:
    return dimension or FINAL_KEY


def _gate_counts(gate_verdict: Optional[dict[str, Any]]) -> tuple[int, int, list[GateResultItem]]:
    """(unclear_count, failed_count, gate items) from a stored gate verdict."""
    items: list[GateResultItem] = []
    unclear = failed = 0
    if not isinstance(gate_verdict, dict):
        return 0, 0, items
    for g in gate_verdict.get("gate_results") or []:
        if not isinstance(g, dict):
            continue
        status = str(g.get("status") or "")
        items.append(
            GateResultItem(
                gate=str(g.get("gate") or ""),
                status=status,
                reason=str(g.get("reason") or ""),
            )
        )
        if status == "unclear":
            unclear += 1
        elif status == "fail":
            failed += 1
    return unclear, failed, items


def model_input_from_row(row: Optional[AnalysisDimension]) -> ModelInput:
    """ModelInput for a dimension row (full prompt, excerpt, or unavailable)."""
    data = row.input_data_json if row is not None and isinstance(row.input_data_json, dict) else {}
    prompt = data.get("prompt")
    excerpt = data.get("prompt_excerpt")
    sections = [str(x) for x in (data.get("sections") or [])]
    attempt = data.get("attempt")
    if isinstance(prompt, str) and prompt.strip():
        return ModelInput(
            source="stored", prompt=prompt, sections=sections,
            total_chars=data.get("total_chars") or len(prompt), attempt=attempt,
        )
    if isinstance(excerpt, str) and excerpt.strip():
        return ModelInput(
            source="excerpt", prompt=excerpt, sections=sections,
            total_chars=data.get("total_chars"), attempt=attempt,
        )
    return ModelInput(source="unavailable", sections=sections, attempt=attempt)


def reconstructed_model_input(
    title: Optional[str], body: Optional[str], interests: Optional[str], character: Optional[str]
) -> ModelInput:
    """Best-effort rebuild of agent input for scout posts that kept no prompt."""
    parts = []
    names = []
    if title:
        parts.append(f"<title>{title}</title>"); names.append("title")
    if body:
        parts.append(f"<body>{body}</body>"); names.append("body")
    if interests:
        parts.append(f"<interests_summary>{interests}</interests_summary>"); names.append("interests_summary")
    if character:
        parts.append(f"<character_summary>{character}</character_summary>"); names.append("character_summary")
    if not parts:
        return ModelInput(source="unavailable")
    prompt = "\n\n".join(parts)
    return ModelInput(source="reconstructed", prompt=prompt, sections=names, total_chars=len(prompt))


def _encode_cursor(data: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


def _decode_cursor(cursor: Optional[str]) -> dict[str, Any]:
    if not cursor:
        return {}
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except Exception:
        return {}


def _verdict_counts(rows: list[AnalysisEvaluation]) -> VerdictCounts:
    counts = VerdictCounts()
    for r in rows:
        if r.human_verdict == "agree":
            counts.agree += 1
        elif r.human_verdict == "partial":
            counts.partial += 1
        elif r.human_verdict == "disagree":
            counts.disagree += 1
    counts.total = counts.agree + counts.partial + counts.disagree
    counts.agreement = (
        round((counts.agree + 0.5 * counts.partial) / counts.total, 4)
        if counts.total
        else None
    )
    return counts


@dataclass
class _Candidate:
    """A queue candidate before hydration."""

    subject_type: str
    subject_id: int
    recommendation: str
    reason: str
    score: float
    unclear_gates: int
    created_at: datetime
    watch_id: Optional[int] = None
    failed_dimensions: set[str] = field(default_factory=set)


class AnalysisEvaluationService:
    """Record and aggregate human verdicts on agent decisions."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # =========================================================================
    # Subject loading + snapshots
    # =========================================================================

    def _load_analysis(self, analysis_id: int) -> LeadAnalysis:
        analysis = (
            self.db.query(LeadAnalysis)
            .options(joinedload(LeadAnalysis.dimensions))
            .filter(LeadAnalysis.id == analysis_id)
            .first()
        )
        if not analysis:
            raise EvaluationSubjectNotFound(f"Analysis not found: {analysis_id}")
        if analysis.final_recommendation is None and not analysis.dimensions:
            raise EvaluationSubjectNotFound(
                f"Analysis {analysis_id} has no results to evaluate"
            )
        return analysis

    def _load_scout_post(self, post_id: int) -> ScoutWatchPost:
        post = self.db.query(ScoutWatchPost).filter(ScoutWatchPost.id == post_id).first()
        if not post:
            raise EvaluationSubjectNotFound(f"Scout post not found: {post_id}")
        if not post.dimension_results_json and not post.analysis_recommendation:
            raise EvaluationSubjectNotFound(
                f"Scout post {post_id} has no analysis results to evaluate"
            )
        return post

    @staticmethod
    def _analysis_dimension_output(
        analysis: LeadAnalysis, dimension: str
    ) -> tuple[Optional[dict[str, Any]], Optional[AnalysisDimension]]:
        """Parsed output for a dimension plus its latest dimension row."""
        column = getattr(analysis, f"{dimension}_json", None)
        rows = [d for d in (analysis.dimensions or []) if d.dimension == dimension]
        rows.sort(key=lambda d: d.id or 0)
        latest = rows[-1] if rows else None
        output = column if isinstance(column, dict) else (latest.output_json if latest else None)
        return output, latest

    def _snapshot_for_analysis(
        self, analysis: LeadAnalysis, dimension: Optional[str]
    ) -> tuple[dict[str, Any], dict[str, Any], Optional[str]]:
        """(agent_snapshot, prompt_versions, model_name) for a lead analysis."""
        meta = analysis.meta_analysis_json if isinstance(analysis.meta_analysis_json, dict) else {}
        model_name = None
        model_info = analysis.model_info_json if isinstance(analysis.model_info_json, dict) else {}
        if model_info.get("model"):
            model_name = str(model_info["model"])

        if dimension is None:
            snapshot = {
                "recommendation": analysis.final_recommendation,
                "confidence": analysis.confidence_score,
                "gate_verdict": meta.get("gate_verdict"),
                "reasoning": analysis.recommendation_reasoning,
                "meta_recommendation": meta.get("recommendation"),
            }
            if model_name is None:
                meta_row = next(
                    (d for d in analysis.dimensions or [] if d.dimension == "meta_analysis"),
                    None,
                )
                if meta_row and isinstance(meta_row.model_info_json, dict):
                    model_name = meta_row.model_info_json.get("model")
        else:
            output, row = self._analysis_dimension_output(analysis, dimension)
            snapshot = {
                "output": output,
                "status": row.status if row else ("completed" if output else "missing"),
                "error": row.error_detail if row else None,
                "prompt_version": row.prompt_version if row else None,
            }
            if model_name is None and row and isinstance(row.model_info_json, dict):
                model_name = row.model_info_json.get("model")

        versions = dict(analysis.prompt_versions_json or {})
        versions.setdefault("_source", "analysis")
        return snapshot, versions, model_name

    def _snapshot_for_scout_post(
        self, post: ScoutWatchPost, dimension: Optional[str]
    ) -> tuple[dict[str, Any], dict[str, Any], Optional[str]]:
        """(agent_snapshot, prompt_versions, model_name) for a scout post."""
        results = post.dimension_results_json if isinstance(post.dimension_results_json, dict) else {}
        raw_meta = results.get("meta_analysis")
        meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}

        if dimension is None:
            snapshot = {
                "recommendation": post.analysis_recommendation,
                "confidence": post.analysis_confidence,
                "gate_verdict": results.get("gate_verdict"),
                "reasoning": post.analysis_reasoning,
                "meta_recommendation": meta.get("recommendation"),
            }
        else:
            output = results.get(dimension)
            snapshot = {
                "output": output if isinstance(output, dict) else None,
                "status": "completed" if isinstance(output, dict) else "missing",
                "error": None,
                "prompt_version": None,
            }

        # Scout posts do not record prompt versions. Prefer the linked lead
        # analysis when the post was promoted; otherwise record the versions
        # active now (documented approximation).
        versions: dict[str, Any] = {}
        model_name: Optional[str] = None
        if post.analysis_id:
            linked = self.db.query(LeadAnalysis).filter(LeadAnalysis.id == post.analysis_id).first()
            if linked and linked.prompt_versions_json:
                versions = dict(linked.prompt_versions_json)
                versions["_source"] = "linked_analysis"
                mi = linked.model_info_json if isinstance(linked.model_info_json, dict) else {}
                model_name = mi.get("model")
        if not versions:
            try:
                active = AgentPromptService(self.db).get_all_active_prompts()
                versions = {dim: p.version for dim, p in active.items()}
            except Exception:  # pragma: no cover - defensive
                versions = {}
            versions["_source"] = "active_at_evaluation"
        if dimension is not None and versions.get(dimension) is not None:
            snapshot["prompt_version"] = versions.get(dimension)
        if model_name is None:
            try:
                from rediska_core.config import get_settings

                model_name = get_settings().inference_model
            except Exception:  # pragma: no cover - defensive
                model_name = None
        return snapshot, versions, model_name

    # =========================================================================
    # Record
    # =========================================================================

    def record(
        self, payload: EvaluationCreate, created_by: str = "user"
    ) -> AnalysisEvaluation:
        """Append a human verdict. Never mutates the analysis, lead, or post.

        Raises:
            EvaluationSubjectNotFound: unknown subject or no analysis on it.
            EvaluationValidationError: semantic validation failure.
        """
        for tag in payload.reason_tags:
            if tag not in REASON_TAGS:
                raise EvaluationValidationError(f"Unknown reason tag: {tag}")
        if payload.dimension is not None and payload.dimension not in EVALUABLE_DIMENSIONS:
            raise EvaluationValidationError(f"Unknown dimension: {payload.dimension}")
        if "missing_context" in payload.reason_tags and not payload.missing_info:
            raise EvaluationValidationError(
                "missing_info is required when 'missing_context' is tagged"
            )

        account_id: Optional[int] = None
        scout_post: Optional[ScoutWatchPost] = None

        if payload.subject_type == "lead_analysis":
            analysis = self._load_analysis(payload.subject_id)
            snapshot, versions, model_name = self._snapshot_for_analysis(
                analysis, payload.dimension
            )
            account_id = analysis.account_id
        elif payload.subject_type == "scout_post":
            scout_post = self._load_scout_post(payload.subject_id)
            snapshot, versions, model_name = self._snapshot_for_scout_post(
                scout_post, payload.dimension
            )
            if scout_post.lead_id:
                lead = self.db.query(LeadPost).filter(LeadPost.id == scout_post.lead_id).first()
                account_id = lead.author_account_id if lead else None
        else:  # pragma: no cover - guarded by the schema literal
            raise EvaluationValidationError(f"Unknown subject_type: {payload.subject_type}")

        row = AnalysisEvaluation(
            subject_type=payload.subject_type,
            subject_id=payload.subject_id,
            account_id=account_id,
            dimension=payload.dimension,
            human_verdict=payload.human_verdict,
            corrected_value_json=payload.corrected_value,
            reason_tags_json=list(payload.reason_tags),
            missing_info=payload.missing_info,
            notes=payload.notes,
            agent_snapshot_json=snapshot,
            prompt_versions_json=versions,
            model_name=model_name,
            created_at=_utcnow(),
            created_by=created_by,
        )
        self.db.add(row)
        self.db.flush()

        if scout_post is not None:
            scout_post.evaluated_at = row.created_at

        self.db.add(
            AuditLog(
                ts=datetime.now(timezone.utc),
                actor="user",
                action_type="evaluation.record",
                entity_type="analysis_evaluation",
                entity_id=row.id,
                request_json={
                    "subject_type": payload.subject_type,
                    "subject_id": payload.subject_id,
                    "dimension": payload.dimension,
                    "human_verdict": payload.human_verdict,
                    "reason_tags": list(payload.reason_tags),
                    "corrected_value": payload.corrected_value,
                },
                response_json={"evaluation_id": row.id},
                result="ok",
            )
        )
        self.db.flush()
        return row

    # =========================================================================
    # Read models
    # =========================================================================

    @staticmethod
    def to_effective(row: AnalysisEvaluation) -> EffectiveEvaluation:
        return EffectiveEvaluation(
            id=row.id,
            human_verdict=row.human_verdict,
            reason_tags=list(row.reason_tags_json or []),
            corrected_value=row.corrected_value_json,
            missing_info=row.missing_info,
            notes=row.notes,
            created_at=row.created_at,
        )

    @staticmethod
    def to_response(row: AnalysisEvaluation) -> EvaluationResponse:
        return EvaluationResponse(
            id=row.id,
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            account_id=row.account_id,
            dimension=row.dimension,
            human_verdict=row.human_verdict,
            corrected_value=row.corrected_value_json,
            reason_tags=list(row.reason_tags_json or []),
            missing_info=row.missing_info,
            notes=row.notes,
            agent_snapshot=row.agent_snapshot_json or {},
            prompt_versions=row.prompt_versions_json or {},
            model_name=row.model_name,
            created_at=row.created_at,
            created_by=row.created_by,
        )

    def list_for_subject(self, subject_type: str, subject_id: int) -> list[AnalysisEvaluation]:
        stmt = (
            select(AnalysisEvaluation)
            .where(
                AnalysisEvaluation.subject_type == subject_type,
                AnalysisEvaluation.subject_id == subject_id,
            )
            .order_by(AnalysisEvaluation.created_at.desc(), AnalysisEvaluation.id.desc())
        )
        return list(self.db.scalars(stmt).all())

    def effective_for_subject(
        self, subject_type: str, subject_id: int
    ) -> dict[str, AnalysisEvaluation]:
        """Latest row per dimension for one subject, keyed by dimension or 'final'."""
        return self.effective_for_subjects(subject_type, [subject_id]).get(subject_id, {})

    def effective_for_subjects(
        self, subject_type: str, subject_ids: list[int]
    ) -> dict[int, dict[str, AnalysisEvaluation]]:
        """Latest row per (subject, dimension) for many subjects of one type."""
        if not subject_ids:
            return {}
        stmt = (
            select(AnalysisEvaluation)
            .where(
                AnalysisEvaluation.subject_type == subject_type,
                AnalysisEvaluation.subject_id.in_(subject_ids),
            )
            .order_by(AnalysisEvaluation.created_at.desc(), AnalysisEvaluation.id.desc())
        )
        result: dict[int, dict[str, AnalysisEvaluation]] = defaultdict(dict)
        for row in self.db.scalars(stmt).all():
            key = _dim_key(row.dimension)
            if key not in result[row.subject_id]:
                result[row.subject_id][key] = row
        return dict(result)

    def effective_map(
        self, subject_type: str, subject_id: int
    ) -> dict[str, Optional[EffectiveEvaluation]]:
        """Effective evaluations as read-model objects, with None for gaps."""
        rows = self.effective_for_subject(subject_type, subject_id)
        out: dict[str, Optional[EffectiveEvaluation]] = {FINAL_KEY: None}
        for dim in EVALUABLE_DIMENSIONS:
            out[dim] = None
        for key, row in rows.items():
            out[key] = self.to_effective(row)
        return out

    def attach_to_analysis_response(self, response: Any) -> Any:
        """Fill ``evaluation`` on a MultiAgentAnalysisResponse and its dimensions."""
        rows = self.effective_for_subject("lead_analysis", response.id)
        final = rows.get(FINAL_KEY)
        response.evaluation = self.to_effective(final) if final else None
        for dim in EVALUABLE_DIMENSIONS:
            dim_result = getattr(response, dim, None)
            if dim_result is None:
                continue
            row = rows.get(dim)
            dim_result.evaluation = self.to_effective(row) if row else None
        return response

    def attach_to_analysis_summaries(self, summaries: list[Any]) -> list[Any]:
        """Fill ``evaluation`` (final verdict) on MultiAgentAnalysisSummary items."""
        by_id = self.effective_for_subjects("lead_analysis", [s.id for s in summaries])
        for s in summaries:
            final = by_id.get(s.id, {}).get(FINAL_KEY)
            s.evaluation = self.to_effective(final) if final else None
        return summaries

    def attach_to_scout_posts(self, post_responses: list[Any]) -> list[Any]:
        """Fill ``evaluations`` on ScoutWatchPostResponse items."""
        ids = [p.id for p in post_responses]
        by_id = self.effective_for_subjects("scout_post", ids)
        for p in post_responses:
            rows = by_id.get(p.id, {})
            evals: dict[str, Optional[EffectiveEvaluation]] = {}
            if p.analysis_dimensions or p.analysis_recommendation:
                evals[FINAL_KEY] = None
                for dim in EVALUABLE_DIMENSIONS:
                    evals[dim] = None
            for key, row in rows.items():
                evals[key] = self.to_effective(row)
            p.evaluations = evals
        return post_responses

    # =========================================================================
    # Review queue
    # =========================================================================

    def _final_evaluated_subquery(self, subject_type: str, subject_id_col):
        return exists().where(
            and_(
                AnalysisEvaluation.subject_type == subject_type,
                AnalysisEvaluation.subject_id == subject_id_col,
                AnalysisEvaluation.dimension.is_(None),
            )
        )

    def _lead_candidates(
        self, since: Optional[datetime], watch_id: Optional[int]
    ) -> list[_Candidate]:
        """Latest completed analysis per non-deleted lead without a final evaluation."""
        stmt = (
            select(
                LeadAnalysis.id,
                LeadAnalysis.final_recommendation,
                LeadAnalysis.confidence_score,
                LeadAnalysis.meta_analysis_json,
                LeadAnalysis.completed_at,
                LeadAnalysis.created_at,
                LeadAnalysis.demographics_json,
                LeadAnalysis.preferences_json,
                LeadAnalysis.relationship_goals_json,
                LeadAnalysis.risk_flags_json,
                LeadAnalysis.sexual_preferences_json,
                LeadPost.status,
                LeadPost.scout_watch_id,
            )
            .join(LeadPost, LeadPost.latest_analysis_id == LeadAnalysis.id)
            .where(
                LeadAnalysis.status == "completed",
                LeadAnalysis.final_recommendation.isnot(None),
                LeadPost.deleted_at.is_(None),
                ~self._final_evaluated_subquery("lead_analysis", LeadAnalysis.id),
            )
        )
        if watch_id is not None:
            stmt = stmt.where(LeadPost.scout_watch_id == watch_id)
        stmt = stmt.add_columns(LeadPost.id)

        rows = self.db.execute(stmt).all()
        if not rows:
            return []

        # Scout-promoted analyses only write analysis_dimensions rows, never the
        # <dim>_json columns, so "has output" must consult the rows too.
        # NB: a failed row stores output_json as JSON ``null`` (not SQL NULL), so
        # "IS NOT NULL" is true for it; check the status and the value instead.
        analysis_ids = [r[0] for r in rows]
        rows_with_output: dict[int, set[str]] = defaultdict(set)
        for aid, dim, output in self.db.execute(
            select(
                AnalysisDimension.analysis_id,
                AnalysisDimension.dimension,
                AnalysisDimension.output_json,
            ).where(
                AnalysisDimension.analysis_id.in_(analysis_ids),
                AnalysisDimension.status == "completed",
            )
        ).all():
            if isinstance(output, dict):
                rows_with_output[aid].add(dim)

        # Leads the user promoted by hand from a non-suitable scout verdict.
        promoted_lead_ids = {
            r[0]
            for r in self.db.execute(
                select(ScoutWatchPost.lead_id).where(
                    ScoutWatchPost.lead_id.isnot(None),
                    ScoutWatchPost.analysis_id.is_(None),
                    ScoutWatchPost.analysis_recommendation.in_(("not_recommended", "needs_review")),
                )
            ).all()
        }

        out: list[_Candidate] = []
        for row in rows:
            (
                analysis_id, rec, score, meta, completed_at, created_at,
                demo, prefs, goals, risk, sexual, lead_status, lead_watch_id, lead_id,
            ) = row
            gate = meta.get("gate_verdict") if isinstance(meta, dict) else None
            unclear = _gate_counts(gate)[0]
            ts = _as_naive(completed_at or created_at) or _utcnow()

            column_outputs = {
                d for d, v in (
                    ("demographics", demo),
                    ("preferences", prefs),
                    ("relationship_goals", goals),
                    ("risk_flags", risk),
                    ("sexual_preferences", sexual),
                )
                if isinstance(v, dict)
            }
            has_output = column_outputs | rows_with_output.get(analysis_id, set())
            if not has_output:
                # Every agent failed: nothing a human can judge beyond "the
                # pipeline broke", which is not an agent decision.
                continue
            failed_dims = set(EVALUABLE_DIMENSIONS) - has_output

            if since is not None and ts < since:
                continue
            reason = REASON_SAMPLE
            if rec == "suitable" and lead_status == "ignored":
                reason = REASON_CONTRADICTION_IGNORED
            elif rec != "suitable" and lead_id in promoted_lead_ids:
                reason = REASON_CONTRADICTION_PROMOTED
            out.append(
                _Candidate(
                    subject_type="lead_analysis",
                    subject_id=analysis_id,
                    recommendation=rec,
                    reason=reason,
                    score=float(score or 0.0),
                    unclear_gates=unclear,
                    created_at=ts,
                    watch_id=lead_watch_id,
                    failed_dimensions=failed_dims,
                )
            )
        return out

    def _scout_candidates(
        self, since: Optional[datetime], watch_id: Optional[int]
    ) -> list[_Candidate]:
        """Analysed scout posts without a final evaluation.

        Posts promoted to a lead are covered by the lead's analysis in the
        sample pass and only appear here as contradictions (a non-suitable
        verdict that was manually promoted).
        """
        stmt = select(
            ScoutWatchPost.id,
            ScoutWatchPost.analysis_recommendation,
            ScoutWatchPost.analysis_confidence,
            ScoutWatchPost.dimension_results_json,
            ScoutWatchPost.first_seen_at,
            ScoutWatchPost.lead_id,
            ScoutWatchPost.watch_id,
        ).where(
            ScoutWatchPost.analysis_recommendation.in_(RECOMMENDATIONS),
            ScoutWatchPost.dimension_results_json.isnot(None),
            ~self._final_evaluated_subquery("scout_post", ScoutWatchPost.id),
        )
        if watch_id is not None:
            stmt = stmt.where(ScoutWatchPost.watch_id == watch_id)

        out: list[_Candidate] = []
        for row in self.db.execute(stmt).all():
            post_id, rec, score, results, first_seen, lead_id, post_watch_id = row
            results = results if isinstance(results, dict) else {}
            has_output = {d for d in EVALUABLE_DIMENSIONS if isinstance(results.get(d), dict)}
            if not has_output:
                # `{}` (pre-migration-011 posts) or gate-only results (every
                # agent failed): nothing to judge.
                continue
            unclear = _gate_counts(results.get("gate_verdict"))[0]
            ts = _as_naive(first_seen) or _utcnow()
            if since is not None and ts < since:
                continue
            if lead_id is not None:
                if rec in ("not_recommended", "needs_review"):
                    reason = REASON_CONTRADICTION_PROMOTED
                else:
                    continue  # promoted suitable post: judged via its lead analysis
            else:
                reason = REASON_SAMPLE
            failed_dims = set(EVALUABLE_DIMENSIONS) - has_output
            out.append(
                _Candidate(
                    subject_type="scout_post",
                    subject_id=post_id,
                    recommendation=rec,
                    reason=reason,
                    score=float(score or 0.0),
                    unclear_gates=unclear,
                    created_at=ts,
                    watch_id=post_watch_id,
                    failed_dimensions=failed_dims,
                )
            )
        return out

    @staticmethod
    def _order_candidates(candidates: list[_Candidate], sort: str = "newest") -> list[_Candidate]:
        """Recent contradictions first, then newest-first (or round-robin by class)."""
        boost_cutoff = _utcnow() - timedelta(days=CONTRADICTION_BOOST_DAYS)
        contradictions = [
            c for c in candidates if c.reason != REASON_SAMPLE and c.created_at >= boost_cutoff
        ]
        contradictions.sort(key=lambda c: (c.created_at, c.subject_id), reverse=True)
        boosted = {(c.subject_type, c.subject_id) for c in contradictions}
        rest = [c for c in candidates if (c.subject_type, c.subject_id) not in boosted]

        if sort != "stratified":
            rest.sort(key=lambda c: (c.created_at, c.subject_id), reverse=True)
            return contradictions + rest

        by_class: dict[str, list[_Candidate]] = {r: [] for r in RECOMMENDATIONS}
        for c in rest:
            if c.recommendation in by_class:
                by_class[c.recommendation].append(c)
        # needs_review: highest score, then fewest unclear gates (near misses first)
        by_class["needs_review"].sort(
            key=lambda c: (-c.score, c.unclear_gates, -c.created_at.timestamp(), -c.subject_id)
        )
        for rec in ("suitable", "not_recommended"):
            by_class[rec].sort(key=lambda c: (c.created_at, c.subject_id), reverse=True)

        # needs_review sits between the two confident classes: it is the class
        # a human can actually settle, so it must never be starved.
        interleaved: list[_Candidate] = []
        queues = [by_class[r] for r in ("suitable", "needs_review", "not_recommended")]
        while any(queues):
            for q in queues:
                if q:
                    interleaved.append(q.pop(0))
        return contradictions + interleaved

    def queue(
        self,
        recommendation: Optional[str] = None,
        dimension_failed: Optional[str] = None,
        watch_id: Optional[int] = None,
        since: Optional[datetime] = None,
        limit: int = 10,
        cursor: Optional[str] = None,
        sort: str = "newest",
    ) -> QueueResponse:
        """Unevaluated subjects: recent contradictions first, then newest first.

        ``sort="stratified"`` interleaves the three recommendation classes
        round-robin instead of pure recency. ``since`` bounds the whole set;
        with no ``since`` every unevaluated subject is a candidate.
        """
        limit = max(1, min(limit, 100))
        window = _as_naive(since)

        candidates = self._lead_candidates(window, watch_id) + self._scout_candidates(
            window, watch_id
        )
        if recommendation:
            candidates = [c for c in candidates if c.recommendation == recommendation]
        if dimension_failed:
            candidates = [c for c in candidates if dimension_failed in c.failed_dimensions]

        ordered = self._order_candidates(candidates, sort=sort)
        offset = int(_decode_cursor(cursor).get("offset", 0) or 0)
        page = ordered[offset : offset + limit]
        next_cursor = (
            _encode_cursor({"offset": offset + limit}) if offset + limit < len(ordered) else None
        )

        items = [self._hydrate(c) for c in page]
        return QueueResponse(
            items=[i for i in items if i is not None],
            next_cursor=next_cursor,
            total_remaining=len(ordered),
        )

    def _hydrate(self, c: _Candidate) -> Optional[QueueItem]:
        if c.subject_type == "lead_analysis":
            return self._hydrate_analysis(c)
        return self._hydrate_scout_post(c)

    def _hydrate_analysis(self, c: _Candidate) -> Optional[QueueItem]:
        analysis = (
            self.db.query(LeadAnalysis)
            .options(joinedload(LeadAnalysis.dimensions))
            .filter(LeadAnalysis.id == c.subject_id)
            .first()
        )
        if not analysis:
            return None
        lead = self.db.query(LeadPost).filter(LeadPost.id == analysis.lead_id).first()
        meta = analysis.meta_analysis_json if isinstance(analysis.meta_analysis_json, dict) else {}
        unclear, failed, gate_items = _gate_counts(meta.get("gate_verdict"))

        dims: dict[str, Any] = {}
        model_inputs: dict[str, ModelInput] = {}
        for dim in EVALUABLE_DIMENSIONS:
            output, row = self._analysis_dimension_output(analysis, dim)
            if isinstance(output, dict):
                dims[dim] = output
            else:
                dims[dim] = {"error": (row.error_detail if row else None) or "no output"}
            model_inputs[dim] = model_input_from_row(row)
        if all(m.source == "unavailable" for m in model_inputs.values()) and lead is not None:
            rebuilt = reconstructed_model_input(
                lead.title, lead.body_text, lead.user_interests_summary, lead.user_character_summary
            )
            model_inputs = {dim: rebuilt for dim in EVALUABLE_DIMENSIONS}

        author = None
        if lead and lead.author_account:
            author = lead.author_account.external_username

        evals = self.effective_map("lead_analysis", analysis.id)
        evals.pop(FINAL_KEY, None)

        return QueueItem(
            subject_type="lead_analysis",
            subject_id=analysis.id,
            reason=c.reason,
            recommendation=analysis.final_recommendation,
            confidence=analysis.confidence_score,
            gate_results=gate_items,
            unclear_gate_count=unclear,
            failed_gate_count=failed,
            lead_id=analysis.lead_id,
            lead_status=lead.status if lead else None,
            analysis_id=analysis.id,
            watch_id=lead.scout_watch_id if lead else None,
            account_id=analysis.account_id,
            author=author,
            title=lead.title if lead else None,
            body=lead.body_text if lead else None,
            post_url=lead.post_url if lead else None,
            interests_summary=lead.user_interests_summary if lead else None,
            character_summary=lead.user_character_summary if lead else None,
            reasoning=analysis.recommendation_reasoning,
            dimensions=dims,
            meta_analysis={k: v for k, v in meta.items() if k != "gate_verdict"} or None,
            prompt_versions=dict(analysis.prompt_versions_json or {}),
            analyzed_at=analysis.completed_at or analysis.created_at,
            posted_at=(lead.post_created_at or lead.created_at) if lead else None,
            posted_at_kind=("posted" if lead and lead.post_created_at else "first_seen") if lead else None,
            evaluations=evals,
            model_inputs=model_inputs,
        )

    def _hydrate_scout_post(self, c: _Candidate) -> Optional[QueueItem]:
        post = self.db.query(ScoutWatchPost).filter(ScoutWatchPost.id == c.subject_id).first()
        if not post:
            return None
        results = post.dimension_results_json if isinstance(post.dimension_results_json, dict) else {}
        unclear, failed, gate_items = _gate_counts(results.get("gate_verdict"))
        dims: dict[str, Any] = {}
        for dim in EVALUABLE_DIMENSIONS:
            output = results.get(dim)
            dims[dim] = output if isinstance(output, dict) else {"error": "no output"}
        meta = results.get("meta_analysis") if isinstance(results.get("meta_analysis"), dict) else None

        lead = None
        if post.lead_id:
            lead = self.db.query(LeadPost).filter(LeadPost.id == post.lead_id).first()

        evals = self.effective_map("scout_post", post.id)
        evals.pop(FINAL_KEY, None)

        rebuilt = reconstructed_model_input(
            post.post_title, post.post_body, post.user_interests, post.user_character
        )
        model_inputs = {dim: rebuilt for dim in EVALUABLE_DIMENSIONS}

        return QueueItem(
            subject_type="scout_post",
            subject_id=post.id,
            reason=c.reason,
            recommendation=post.analysis_recommendation,
            confidence=post.analysis_confidence,
            gate_results=gate_items,
            unclear_gate_count=unclear,
            failed_gate_count=failed,
            lead_id=post.lead_id,
            lead_status=lead.status if lead else None,
            analysis_id=post.analysis_id,
            scout_post_id=post.id,
            watch_id=post.watch_id,
            account_id=lead.author_account_id if lead else None,
            author=post.post_author,
            title=post.post_title,
            body=post.post_body,
            post_url=f"https://reddit.com/comments/{post.external_post_id}",
            interests_summary=post.user_interests,
            character_summary=post.user_character,
            reasoning=post.analysis_reasoning,
            dimensions=dims,
            meta_analysis=meta,
            prompt_versions={},
            analyzed_at=post.first_seen_at,
            posted_at=post.first_seen_at,
            posted_at_kind="first_seen",
            evaluations=evals,
            model_inputs=model_inputs,
        )

    # =========================================================================
    # Summary metrics
    # =========================================================================

    def _effective_rows(
        self,
        since: Optional[datetime] = None,
        watch_id: Optional[int] = None,
        dimension: Optional[str] = None,
        only_dimension: bool = False,
    ) -> list[AnalysisEvaluation]:
        """Effective (latest per subject+dimension) rows, optionally filtered.

        ``since`` applies to the *effective* row's timestamp. ``watch_id``
        resolves each subject to the scout watch it came from.
        """
        stmt = select(AnalysisEvaluation).order_by(
            AnalysisEvaluation.created_at.desc(), AnalysisEvaluation.id.desc()
        )
        if only_dimension:
            if dimension is None:
                stmt = stmt.where(AnalysisEvaluation.dimension.is_(None))
            else:
                stmt = stmt.where(AnalysisEvaluation.dimension == dimension)
        seen: set[tuple[str, int, str]] = set()
        effective: list[AnalysisEvaluation] = []
        for row in self.db.scalars(stmt).all():
            key = (row.subject_type, row.subject_id, _dim_key(row.dimension))
            if key in seen:
                continue
            seen.add(key)
            effective.append(row)

        since_naive = _as_naive(since)
        if since_naive is not None:
            effective = [r for r in effective if r.created_at >= since_naive]

        if watch_id is not None:
            effective = [r for r in effective if self._watch_for_subject(r) == watch_id]
        return effective

    def _watch_for_subject(self, row: AnalysisEvaluation) -> Optional[int]:
        if row.subject_type == "scout_post":
            return self.db.execute(
                select(ScoutWatchPost.watch_id).where(ScoutWatchPost.id == row.subject_id)
            ).scalar()
        return self.db.execute(
            select(LeadPost.scout_watch_id)
            .join(LeadAnalysis, LeadAnalysis.lead_id == LeadPost.id)
            .where(LeadAnalysis.id == row.subject_id)
        ).scalar()

    @staticmethod
    def _version_for(row: AnalysisEvaluation) -> Optional[str]:
        versions = row.prompt_versions_json or {}
        if row.dimension is None:
            v = versions.get("meta_analysis")
        else:
            snap = row.agent_snapshot_json or {}
            v = snap.get("prompt_version") or versions.get(row.dimension)
        return str(v) if v is not None else None

    def summary(
        self, since: Optional[datetime] = None, watch_id: Optional[int] = None
    ) -> EvaluationSummary:
        """Aggregate agreement, tags, confusion matrix, trend and missing info."""
        rows = self._effective_rows(since=since, watch_id=watch_id)

        by_dim: dict[str, list[AnalysisEvaluation]] = defaultdict(list)
        for r in rows:
            by_dim[_dim_key(r.dimension)].append(r)

        dim_order = [FINAL_KEY] + list(EVALUABLE_DIMENSIONS)
        dimensions: list[DimensionSummary] = []
        for key in dim_order + sorted(k for k in by_dim if k not in dim_order):
            drows = by_dim.get(key, [])
            if not drows and key not in dim_order:
                continue
            tags: dict[str, int] = defaultdict(int)
            by_version: dict[str, list[AnalysisEvaluation]] = defaultdict(list)
            for r in drows:
                for t in r.reason_tags_json or []:
                    tags[str(t)] += 1
                v = self._version_for(r)
                if v is not None:
                    by_version[v].append(r)
            dimensions.append(
                DimensionSummary(
                    dimension=key,
                    counts=_verdict_counts(drows),
                    tags=dict(sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))),
                    by_prompt_version={
                        v: _verdict_counts(vrows)
                        for v, vrows in sorted(
                            by_version.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0
                        )
                    },
                )
            )

        # Confusion matrix (final verdicts only)
        matrix: dict[str, dict[str, int]] = {
            a: {h: 0 for h in RECOMMENDATIONS} for a in RECOMMENDATIONS
        }
        for r in by_dim.get(FINAL_KEY, []):
            agent = (r.agent_snapshot_json or {}).get("recommendation")
            corrected = (r.corrected_value_json or {}).get("recommendation")
            human = corrected or (agent if r.human_verdict == "agree" else None)
            if agent in matrix and human in RECOMMENDATIONS:
                matrix[agent][human] += 1

        # Weekly trend per dimension
        by_week: dict[tuple[str, str], list[AnalysisEvaluation]] = defaultdict(list)
        for r in rows:
            iso = r.created_at.isocalendar()
            week = f"{iso[0]}-W{iso[1]:02d}"
            by_week[(week, _dim_key(r.dimension))].append(r)
        trend = [
            TrendPoint(week=week, dimension=dim, counts=_verdict_counts(wrows))
            for (week, dim), wrows in sorted(by_week.items())
        ]

        # Missing information statements
        missing: dict[str, dict[str, Any]] = {}
        for r in rows:
            if not r.missing_info:
                continue
            norm = " ".join(r.missing_info.strip().lower().split())
            if not norm:
                continue
            entry = missing.setdefault(
                norm,
                {"text": " ".join(r.missing_info.split()), "count": 0, "dimensions": set()},
            )
            entry["count"] += 1
            entry["dimensions"].add(_dim_key(r.dimension))
        missing_items = [
            MissingInfoItem(text=e["text"], count=e["count"], dimensions=sorted(e["dimensions"]))
            for e in sorted(missing.values(), key=lambda e: (-e["count"], e["text"]))
        ]

        return EvaluationSummary(
            total_evaluations=len(rows),
            overall=_verdict_counts(rows),
            dimensions=dimensions,
            confusion_matrix=matrix,
            trend=trend,
            missing_info=missing_items,
            period_since=since,
            watch_id=watch_id,
        )

    def prompt_version_metrics(self, dimension: str) -> dict[int, PromptVersionMetrics]:
        """Effective-evaluation count and agreement per prompt version of a dimension."""
        dim: Optional[str] = None if dimension == "meta_analysis" else dimension
        rows = self._effective_rows(dimension=dim, only_dimension=True)
        by_version: dict[int, list[AnalysisEvaluation]] = defaultdict(list)
        for r in rows:
            v = self._version_for(r)
            if v is None or not v.isdigit():
                continue
            by_version[int(v)].append(r)
        return {
            v: PromptVersionMetrics(
                evaluations=len(vrows), agreement=_verdict_counts(vrows).agreement
            )
            for v, vrows in by_version.items()
        }

    # =========================================================================
    # Labelled dataset export
    # =========================================================================

    def _case_input(self, row: AnalysisEvaluation) -> tuple[Optional[dict[str, Any]], str]:
        """(model input, source) for an evaluated case.

        Lead analyses store the assembled prompt on the dimension row; scout
        posts that were promoted borrow their linked analysis; otherwise the
        input is reconstructed from the stored post text and summaries.
        """
        analysis_id: Optional[int] = None
        if row.subject_type == "lead_analysis":
            analysis_id = row.subject_id
        else:
            post = self.db.query(ScoutWatchPost).filter(ScoutWatchPost.id == row.subject_id).first()
            if post is None:
                return None, "missing"
            if post.analysis_id:
                analysis_id = post.analysis_id
            else:
                return (
                    {
                        "title": post.post_title,
                        "body": post.post_body,
                        "interests_summary": post.user_interests,
                        "character_summary": post.user_character,
                    },
                    "reconstructed",
                )

        if row.dimension is None:
            analysis = self.db.query(LeadAnalysis).filter(LeadAnalysis.id == analysis_id).first()
            if analysis is None:
                return None, "missing"
            return (
                {
                    dim: getattr(analysis, f"{dim}_json", None) for dim in EVALUABLE_DIMENSIONS
                },
                "dimension_outputs",
            )

        dim_row = (
            self.db.query(AnalysisDimension)
            .filter(
                AnalysisDimension.analysis_id == analysis_id,
                AnalysisDimension.dimension == row.dimension,
            )
            .order_by(AnalysisDimension.id.desc())
            .first()
        )
        if dim_row is None or not dim_row.input_data_json:
            return None, "missing"
        return dict(dim_row.input_data_json), "stored"

    def export_rows(self, dimension: Optional[str]) -> list[dict[str, Any]]:
        """Labelled cases for one dimension (None = final verdict), verbatim."""
        rows = self._effective_rows(dimension=dimension, only_dimension=True)
        out: list[dict[str, Any]] = []
        for r in rows:
            model_input, source = self._case_input(r)
            snap = r.agent_snapshot_json or {}
            out.append(
                {
                    "evaluation_id": r.id,
                    "subject_type": r.subject_type,
                    "subject_id": r.subject_id,
                    "dimension": _dim_key(r.dimension),
                    "input": model_input,
                    "input_source": source,
                    "agent_output": snap.get("output") if r.dimension else snap,
                    "prompt_version": self._version_for(r),
                    "prompt_versions": r.prompt_versions_json or {},
                    "model_name": r.model_name,
                    "human_verdict": r.human_verdict,
                    "corrected_value": r.corrected_value_json,
                    "reason_tags": list(r.reason_tags_json or []),
                    "missing_info": r.missing_info,
                    "notes": r.notes,
                    "created_at": r.created_at.isoformat(),
                }
            )
        return out

    def export_jsonl(self, dimension: Optional[str]) -> Iterator[str]:
        """Yield JSONL lines for the labelled dataset and audit the export."""
        rows = self.export_rows(dimension)
        self.db.add(
            AuditLog(
                ts=datetime.now(timezone.utc),
                actor="user",
                action_type="evaluation.export",
                entity_type="analysis_evaluation",
                entity_id=None,
                request_json={"dimension": _dim_key(dimension)},
                response_json={"count": len(rows)},
                result="ok",
            )
        )
        self.db.flush()
        for row in rows:
            yield json.dumps(row, ensure_ascii=False, default=str) + "\n"
