"""Replay a candidate prompt against human-labelled evaluation cases.

The replay re-runs one dimension agent, unchanged, on each labelled case's
stored model input (``analysis_dimensions.input_data_json['prompt']``) with a
transient prompt built from the candidate text, and compares the produced
output to the human-corrected value using per-dimension field rules.

Nothing is persisted to analyses, evaluations or prompts: agents run with
``db=None`` so ``_store_dimension_result`` is skipped, and the candidate
``AgentPrompt`` is never added to a session.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from rediska_core.api.schemas.evaluations import EVALUABLE_DIMENSIONS
from rediska_core.domain.models import (
    AgentPrompt,
    AnalysisDimension,
    AnalysisEvaluation,
    Job,
    LeadAnalysis,
    LeadPost,
    ProfileItem,
    ProfileSnapshot,
    PromptReplay,
    ScoutWatchPost,
)
from rediska_core.domain.services.agent_prompt import AgentPromptService

logger = logging.getLogger(__name__)

__all__ = [
    "COMPARE_RULES",
    "AGE_TOLERANCE",
    "LIST_OVERLAP_THRESHOLD",
    "ReplayCase",
    "compare_fields",
    "expected_value",
    "labelled_cases",
    "resolve_case_input",
    "create_replay",
    "run_replay",
    "ReplayError",
]

# Initial tolerances — revisit after the first replay runs (design open question).
AGE_TOLERANCE = 2
LIST_OVERLAP_THRESHOLD = 0.5

# Per-dimension canonical fields and their comparison rule.
#   categorical  — case-insensitive exact match on the string form
#   age          — integer within ±AGE_TOLERANCE
#   list         — Jaccard-style overlap of normalised strings ≥ threshold
#   bool         — exact
COMPARE_RULES: dict[str, dict[str, str]] = {
    "demographics": {
        "age": "age",
        "gender": "categorical",
        "location_state": "categorical",
    },
    "preferences": {
        "kinks": "list",
        "hobbies": "list",
        "lifestyle": "categorical",
    },
    "relationship_goals": {
        "relationship_intent": "categorical",
        "partner_max_age": "age",
        "deal_breakers": "list",
    },
    "risk_flags": {
        "is_authentic": "bool",
        "red_flags": "list",
        "scam_indicators": "list",
    },
    "sexual_preferences": {
        "ds_orientation": "categorical",
        "kinks_interests": "list",
    },
}


class ReplayError(ValueError):
    """Replay could not be created."""


def _norm_str(value: Any) -> str:
    return " ".join(str(value).strip().lower().split())


def _norm_list(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        parts = [p for p in (s.strip() for s in value.replace(";", ",").split(",")) if p]
        return {_norm_str(p) for p in parts}
    if isinstance(value, (list, tuple, set)):
        return {_norm_str(v) for v in value if v is not None and str(v).strip()}
    return {_norm_str(value)}


def _to_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits) if digits else None


def _to_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    s = _norm_str(value)
    if s in ("true", "yes", "1"):
        return True
    if s in ("false", "no", "0"):
        return False
    return None


def _compare_one(rule: str, expected: Any, produced: Any) -> bool:
    if rule == "categorical":
        if expected is None:
            return produced is None or _norm_str(produced) in ("", "none", "null", "unclear")
        return produced is not None and _norm_str(expected) == _norm_str(produced)
    if rule == "age":
        e, p = _to_int(expected), _to_int(produced)
        if e is None:
            return p is None
        return p is not None and abs(e - p) <= AGE_TOLERANCE
    if rule == "list":
        e, p = _norm_list(expected), _norm_list(produced)
        if not e and not p:
            return True
        union = e | p
        return (len(e & p) / len(union)) >= LIST_OVERLAP_THRESHOLD if union else True
    if rule == "bool":
        return _to_bool(expected) == _to_bool(produced)
    return _norm_str(expected) == _norm_str(produced)  # pragma: no cover


def compare_fields(
    dimension: str, expected: dict[str, Any] | None, produced: dict[str, Any] | None
) -> dict[str, bool]:
    """Per-field agreement for the dimension's canonical fields.

    Only canonical fields present in ``expected`` are compared; unknown fields
    are ignored so prompt edits that add output keys do not break comparison.
    An empty result means nothing comparable was labelled.
    """
    rules = COMPARE_RULES.get(dimension, {})
    expected = expected or {}
    produced = produced or {}
    out: dict[str, bool] = {}
    for field_name, rule in rules.items():
        if field_name not in expected:
            continue
        out[field_name] = _compare_one(rule, expected.get(field_name), produced.get(field_name))
    return out


def expected_value(row: AnalysisEvaluation) -> dict[str, Any]:
    """The value a replay must reproduce for a labelled dimension case.

    ``agree`` → the judged agent output; ``partial``/``disagree`` → the
    corrected fields merged over the judged output.
    """
    snapshot = row.agent_snapshot_json or {}
    raw_output = snapshot.get("output")
    expected: dict[str, Any] = dict(raw_output) if isinstance(raw_output, dict) else {}
    if row.human_verdict in ("partial", "disagree") and isinstance(row.corrected_value_json, dict):
        expected.update(row.corrected_value_json)
    return expected


class ReplayCase:
    """One labelled case resolved for replay."""

    __slots__ = ("evaluation", "input_prompt", "input_context", "source")

    def __init__(
        self,
        evaluation: AnalysisEvaluation,
        input_prompt: Optional[str],
        input_context: Optional[dict[str, Any]],
        source: str,
    ) -> None:
        self.evaluation = evaluation
        self.input_prompt = input_prompt
        self.input_context = input_context
        self.source = source

    @property
    def has_input(self) -> bool:
        return self.input_prompt is not None or self.input_context is not None


def labelled_cases(db: Session, dimension: str, limit: int) -> list[AnalysisEvaluation]:
    """Most recent effective evaluations for a dimension (newest first)."""
    stmt = (
        select(AnalysisEvaluation)
        .where(AnalysisEvaluation.dimension == dimension)
        .order_by(AnalysisEvaluation.created_at.desc(), AnalysisEvaluation.id.desc())
    )
    seen: set[tuple[str, int]] = set()
    out: list[AnalysisEvaluation] = []
    for row in db.scalars(stmt).all():
        key = (row.subject_type, row.subject_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def count_labelled_cases(db: Session, dimension: str) -> int:
    return len(labelled_cases(db, dimension, limit=10**9))


def _rebuild_context_from_lead(db: Session, lead_id: int) -> Optional[dict[str, Any]]:
    """Rebuild the agent input context from the lead's current stored data."""
    from rediska_core.domain.services.multi_agent_analysis import MultiAgentAnalysisService

    lead = db.query(LeadPost).filter(LeadPost.id == lead_id).first()
    if not lead or not lead.author_account_id:
        return None
    snapshot = (
        db.query(ProfileSnapshot)
        .filter(ProfileSnapshot.account_id == lead.author_account_id)
        .order_by(ProfileSnapshot.fetched_at.desc())
        .first()
    )
    if not snapshot:
        return None
    items = db.query(ProfileItem).filter(ProfileItem.account_id == lead.author_account_id).all()
    service = MultiAgentAnalysisService.__new__(MultiAgentAnalysisService)
    return service._build_input_context(
        lead,
        snapshot,
        items,
        user_interests_summary=lead.user_interests_summary or "",
        user_character_summary=lead.user_character_summary or "",
    )


def resolve_case_input(db: Session, row: AnalysisEvaluation) -> ReplayCase:
    """Find the model input for a labelled case.

    Preference order: the stored full prompt on the dimension row ("stored"),
    a context rebuilt from the lead ("rebuilt"), else no input ("none").
    """
    analysis_id: Optional[int] = None
    lead_id: Optional[int] = None

    if row.subject_type == "lead_analysis":
        analysis_id = row.subject_id
    else:
        post = db.query(ScoutWatchPost).filter(ScoutWatchPost.id == row.subject_id).first()
        if post is not None:
            analysis_id = post.analysis_id
            lead_id = post.lead_id

    if analysis_id is not None:
        dim_row = (
            db.query(AnalysisDimension)
            .filter(
                AnalysisDimension.analysis_id == analysis_id,
                AnalysisDimension.dimension == row.dimension,
            )
            .order_by(AnalysisDimension.id.desc())
            .first()
        )
        if dim_row and isinstance(dim_row.input_data_json, dict):
            prompt = dim_row.input_data_json.get("prompt")
            if isinstance(prompt, str) and prompt.strip():
                return ReplayCase(row, prompt, None, "stored")
        if lead_id is None:
            analysis = db.query(LeadAnalysis).filter(LeadAnalysis.id == analysis_id).first()
            lead_id = analysis.lead_id if analysis else None

    if lead_id is not None:
        context = _rebuild_context_from_lead(db, lead_id)
        if context is not None:
            return ReplayCase(row, None, context, "rebuilt")

    return ReplayCase(row, None, None, "none")


def create_replay(
    db: Session,
    dimension: str,
    system_prompt: Optional[str],
    version: Optional[int],
    temperature: Optional[float],
    max_tokens: Optional[int],
    max_cases: int,
) -> PromptReplay:
    """Create a queued replay row after validating preconditions.

    Raises:
        ReplayError: unknown dimension, no labelled cases, a replay already
            running, or the requested version does not exist.
    """
    if dimension not in EVALUABLE_DIMENSIONS:
        raise ReplayError(f"Replay is only available for dimension agents, not '{dimension}'")

    running = db.execute(
        select(PromptReplay.id).where(PromptReplay.status.in_(("queued", "running")))
    ).first()
    if running:
        raise ReplayError(f"A replay is already in progress (#{running[0]}); wait or cancel it")

    prompt_service = AgentPromptService(db)
    candidate_text = (system_prompt or "").strip()
    candidate_version: Optional[int] = None
    if version is not None:
        try:
            existing = prompt_service.get_prompt_by_version(dimension, version)
        except ValueError as e:
            raise ReplayError(str(e))
        candidate_text = existing.system_prompt
        candidate_version = existing.version
        temperature = temperature if temperature is not None else existing.temperature
        max_tokens = max_tokens if max_tokens is not None else existing.max_tokens
    if not candidate_text:
        raise ReplayError("A draft system_prompt or an existing version is required")

    case_count = len(labelled_cases(db, dimension, limit=max_cases))
    if case_count == 0:
        raise ReplayError(
            f"No labelled cases for '{dimension}'. Evaluate some analyses first."
        )

    replay = PromptReplay(
        dimension=dimension,
        candidate_system_prompt=candidate_text,
        candidate_version=candidate_version,
        temperature=temperature,
        max_tokens=max_tokens,
        status="queued",
        case_count=case_count,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(replay)
    db.flush()
    return replay


def _agent_class(dimension: str):
    from rediska_core.domain.services.agents.agent_implementations import (
        PreferencesAgent,
        RelationshipGoalsAgent,
        RiskFlagsAgent,
        SexualPreferencesAgent,
    )
    from rediska_core.domain.services.agents.demographics import DemographicsAgent

    return {
        "demographics": DemographicsAgent,
        "preferences": PreferencesAgent,
        "relationship_goals": RelationshipGoalsAgent,
        "risk_flags": RiskFlagsAgent,
        "sexual_preferences": SexualPreferencesAgent,
    }[dimension]


def _transient_prompt(db: Session, replay: PromptReplay) -> AgentPrompt:
    """A never-persisted AgentPrompt carrying the candidate text."""
    schema: dict[str, Any] = {}
    temperature = replay.temperature
    max_tokens = replay.max_tokens
    try:
        active = AgentPromptService(db).get_active_prompt(replay.dimension)
        schema = active.output_schema_json or {}
        temperature = temperature if temperature is not None else active.temperature
        max_tokens = max_tokens if max_tokens is not None else active.max_tokens
    except ValueError:
        pass
    return AgentPrompt(
        id=0,
        agent_dimension=replay.dimension,
        version=replay.candidate_version or 0,
        system_prompt=replay.candidate_system_prompt,
        output_schema_json=schema,
        temperature=temperature if temperature is not None else 0.7,
        max_tokens=max_tokens if max_tokens is not None else 8192,
        is_active=False,
        created_by="replay",
    )


def _reload(db: Session, replay_id: int) -> PromptReplay:
    replay = db.query(PromptReplay).filter(PromptReplay.id == replay_id).first()
    if replay is None:
        raise ReplayError(f"Replay not found: {replay_id}")
    return replay


def _is_cancelled(db: Session, replay_id: int, job_id: Optional[int]) -> bool:
    db.expire_all()
    replay = db.query(PromptReplay).filter(PromptReplay.id == replay_id).first()
    if replay is not None and replay.status == "cancelled":
        return True
    if job_id is not None:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is not None and job.status == "cancelled":
            return True
    return False


async def run_replay(
    db: Session,
    replay_id: int,
    inference_client: Any,
    chat_template: Optional[str] = None,
    max_cases: int = 50,
    job_id: Optional[int] = None,
    agent_factory: Optional[Callable[[str], Any]] = None,
) -> PromptReplay:
    """Execute a queued replay, writing per-case progress as it goes.

    Args:
        db: Session (committed after every case so the UI can poll).
        replay_id: ``prompt_replays.id``.
        inference_client: Local inference client (goes through the gate).
        chat_template: Chat template name for response parsing.
        max_cases: Hard cap on cases (``EVALUATION_REPLAY_MAX_CASES``).
        job_id: ``jobs.id`` checked for cancellation between cases.
        agent_factory: Test hook returning an agent for a dimension.
    """
    replay = _reload(db, replay_id)
    if replay.status == "cancelled":
        return replay

    replay.status = "running"
    replay.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    replay.completed_count = 0
    replay.agreed_count = 0
    replay.skipped_no_input = 0
    replay.results_json = []
    db.commit()

    cases = labelled_cases(db, replay.dimension, limit=max_cases)
    replay.case_count = len(cases)
    db.commit()

    prompt = _transient_prompt(db, replay)
    if agent_factory is not None:
        agent = agent_factory(replay.dimension)
    else:
        agent = _agent_class(replay.dimension)(inference_client, chat_template=chat_template)

    results: list[dict[str, Any]] = []
    compared = agreed = skipped = 0
    try:
        for row in cases:
            if _is_cancelled(db, replay_id, job_id):
                replay = _reload(db, replay_id)
                replay.status = "cancelled"
                replay.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                replay.results_json = results
                db.commit()
                return replay

            replay = _reload(db, replay_id)
            case = resolve_case_input(db, row)
            entry: dict[str, Any] = {
                "evaluation_id": row.id,
                "subject_type": row.subject_type,
                "subject_id": row.subject_id,
                "input_source": case.source,
            }
            if not case.has_input:
                skipped += 1
                entry["skipped"] = "no_input"
                results.append(entry)
            else:
                expected = expected_value(row)
                try:
                    agent.input_prompt_override = case.input_prompt
                    result = await agent.analyze(
                        dimension=replay.dimension,
                        input_context=case.input_context or {"lead": {}},
                        prompt=prompt,
                        analysis_id=None,
                        db=None,
                    )
                    produced = result.get("parsed_output") if isinstance(result, dict) else None
                    if not isinstance(produced, dict):
                        produced = None
                    fields = compare_fields(replay.dimension, expected, produced)
                    ok = bool(fields) and all(fields.values())
                    entry.update(
                        {
                            "agreed": ok,
                            "expected": {k: expected.get(k) for k in fields} or expected,
                            "produced": (
                                {k: produced.get(k) for k in fields} if produced else None
                            ),
                            "field_results": fields,
                            "error": None if produced is not None else (
                                (result or {}).get("error") if isinstance(result, dict) else "no output"
                            ),
                        }
                    )
                    compared += 1
                    if ok:
                        agreed += 1
                except Exception as e:  # one bad case must not sink the replay
                    logger.warning(f"Replay {replay.id} case {row.id} failed: {e}")
                    compared += 1
                    entry.update({"agreed": False, "error": str(e), "field_results": {}})
                finally:
                    agent.input_prompt_override = None
                results.append(entry)

            replay.completed_count = compared + skipped
            replay.agreed_count = agreed
            replay.skipped_no_input = skipped
            replay.agreement = round(agreed / compared, 4) if compared else None
            replay.results_json = list(results)
            db.commit()

        replay = _reload(db, replay_id)
        if replay.status != "cancelled":
            replay.status = "completed"
        replay.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        return replay
    except Exception as e:
        db.rollback()
        replay = _reload(db, replay_id)
        replay.status = "failed"
        replay.error = str(e)[:2000]
        replay.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        replay.results_json = results
        db.commit()
        raise


def replay_summary_by_field(results: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Per-field agree/disagree counts across a replay's results."""
    out: dict[str, dict[str, int]] = defaultdict(lambda: {"agree": 0, "disagree": 0})
    for r in results:
        for f, ok in (r.get("field_results") or {}).items():
            out[f]["agree" if ok else "disagree"] += 1
    return dict(out)
