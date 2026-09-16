"""Unit tests for run_replay with a fake agent (no inference, nothing persisted)."""

from datetime import datetime, timezone
from typing import Any

import pytest

from rediska_core.api.schemas.evaluations import EvaluationCreate
from rediska_core.domain.models import (
    AgentPrompt,
    AnalysisDimension,
    ExternalAccount,
    Job,
    LeadAnalysis,
    LeadPost,
    Provider,
    PromptReplay,
    ScoutWatch,
    ScoutWatchPost,
)
from rediska_core.domain.services.analysis_evaluation import AnalysisEvaluationService
from rediska_core.domain.services.prompt_replay import create_replay, run_replay


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FakeAgent:
    """Stands in for a dimension agent; records what it was asked to do."""

    def __init__(self, outputs: dict[str, Any]):
        self.outputs = outputs  # keyed by input prompt
        self.calls: list[dict[str, Any]] = []
        self.input_prompt_override = None
        self.attempt = 1

    async def analyze(self, dimension, input_context, prompt, analysis_id, db):
        self.calls.append({
            "dimension": dimension,
            "prompt_text": prompt.system_prompt,
            "analysis_id": analysis_id,
            "db": db,
            "override": self.input_prompt_override,
        })
        out = self.outputs.get(self.input_prompt_override or "")
        if isinstance(out, Exception):
            raise out
        return {"success": out is not None, "parsed_output": out, "error": None}


@pytest.fixture
def seeded(db_session):
    db_session.add(Provider(provider_id="reddit", display_name="Reddit", enabled=True))
    db_session.flush()
    account = ExternalAccount(provider_id="reddit", external_username="test_author", remote_status="active")
    db_session.add(account)
    db_session.flush()
    db_session.add(AgentPrompt(
        agent_dimension="demographics", version=1, system_prompt="active prompt",
        output_schema_json={"type": "object"}, temperature=0.3, max_tokens=512,
        is_active=True, created_by="test",
    ))
    db_session.flush()

    svc = AnalysisEvaluationService(db_session)
    analyses = []
    for i, (age, corrected) in enumerate(((30, None), (30, {"age": 45}), (30, None))):
        lead = LeadPost(
            provider_id="reddit", source_location="r/t", external_post_id=f"p{i}",
            post_url=f"https://example.invalid/{i}", author_account_id=account.id,
            title="t", body_text="b",
        )
        db_session.add(lead)
        db_session.flush()
        a = LeadAnalysis(
            lead_id=lead.id, account_id=account.id, started_at=_now(), completed_at=_now(),
            status="completed", demographics_json={"age": age, "gender": "female", "location_state": "near"},
            final_recommendation="suitable", confidence_score=0.7, prompt_versions_json={"demographics": 1},
        )
        db_session.add(a)
        db_session.flush()
        db_session.add(AnalysisDimension(
            analysis_id=a.id, dimension="demographics", started_at=_now(), completed_at=_now(),
            status="completed", input_data_json={"prompt": f"input {i}"},
            output_json=a.demographics_json, prompt_version=1,
        ))
        lead.latest_analysis_id = a.id
        db_session.flush()
        analyses.append(a)
        svc.record(EvaluationCreate(
            subject_type="lead_analysis", subject_id=a.id, dimension="demographics",
            human_verdict="disagree" if corrected else "agree",
            corrected_value=corrected, reason_tags=["wrong_age"] if corrected else [],
        ))

    # A scout-only subject with no stored input → skipped_no_input
    watch = ScoutWatch(provider_id="reddit", source_location="r/t", sort_by="new", time_filter="day")
    db_session.add(watch)
    db_session.flush()
    post = ScoutWatchPost(
        watch_id=watch.id, external_post_id="sc", first_seen_at=_now(), analysis_status="analyzed",
        analysis_recommendation="needs_review", analysis_confidence=0.5,
        dimension_results_json={"demographics": {"age": 22, "gender": "female"}},
    )
    db_session.add(post)
    db_session.flush()
    svc.record(EvaluationCreate(
        subject_type="scout_post", subject_id=post.id, dimension="demographics", human_verdict="agree"))
    db_session.commit()
    return {"analyses": analyses, "post": post}


@pytest.mark.asyncio
async def test_run_replay_computes_agreement_and_persists_nothing_else(db_session, seeded):
    replay = create_replay(db_session, "demographics", "candidate prompt", None, None, None, 50)
    db_session.commit()
    assert replay.case_count == 4

    outputs = {
        "input 0": {"age": 31, "gender": "female", "location_state": "near"},   # agree (±2)
        "input 1": {"age": 30, "gender": "female", "location_state": "near"},   # expected 45 → disagree
        "input 2": {"age": 30, "gender": "male", "location_state": "near"},     # gender wrong
    }
    agent = FakeAgent(outputs)
    before_dims = db_session.query(AnalysisDimension).count()
    before_prompts = db_session.query(AgentPrompt).count()

    result = await run_replay(
        db_session, replay.id, inference_client=None, max_cases=50, agent_factory=lambda d: agent,
    )

    assert result.status == "completed"
    assert result.case_count == 4
    assert result.completed_count == 4
    assert result.skipped_no_input == 1
    assert result.agreed_count == 1
    assert result.agreement == round(1 / 3, 4)
    rows = result.results_json
    assert [r.get("skipped") for r in rows].count("no_input") == 1
    disagreeing = [r for r in rows if r.get("agreed") is False]
    assert len(disagreeing) == 2
    case1 = next(r for r in rows if r.get("expected", {}).get("age") == 45)
    assert case1["field_results"]["age"] is False
    assert case1["produced"]["age"] == 30

    # The agent ran with the candidate text, no analysis id, and no db
    assert {c["prompt_text"] for c in agent.calls} == {"candidate prompt"}
    assert all(c["analysis_id"] is None and c["db"] is None for c in agent.calls)
    assert {c["override"] for c in agent.calls} == {"input 0", "input 1", "input 2"}
    assert agent.input_prompt_override is None

    # Nothing persisted to analyses or prompts
    assert db_session.query(AnalysisDimension).count() == before_dims
    assert db_session.query(AgentPrompt).count() == before_prompts
    active = db_session.query(AgentPrompt).filter(AgentPrompt.is_active.is_(True)).one()
    assert active.system_prompt == "active prompt"


@pytest.mark.asyncio
async def test_run_replay_honours_cancellation_between_cases(db_session, seeded):
    replay = create_replay(db_session, "demographics", "candidate", None, None, None, 50)
    job = Job(queue_name="multi_agent_analysis", job_type="evaluation.replay_prompt",
              payload_json={"replay_id": replay.id}, dedupe_key=f"evaluation.replay_prompt:{replay.id}",
              status="running")
    db_session.add(job)
    db_session.commit()

    class CancellingAgent(FakeAgent):
        async def analyze(self, *a, **kw):
            r = await super().analyze(*a, **kw)
            # cancel via the jobs ledger after the first inference
            job.status = "cancelled"
            db_session.commit()
            return r

    agent = CancellingAgent({"input 0": {"age": 30}, "input 1": {"age": 30}, "input 2": {"age": 30}})
    result = await run_replay(db_session, replay.id, inference_client=None, job_id=job.id,
                              agent_factory=lambda d: agent)
    assert result.status == "cancelled"
    assert len(agent.calls) == 1
    assert db_session.get(PromptReplay, replay.id).finished_at is not None


@pytest.mark.asyncio
async def test_run_replay_one_bad_case_does_not_fail_replay(db_session, seeded):
    replay = create_replay(db_session, "demographics", "candidate", None, None, None, 50)
    db_session.commit()
    agent = FakeAgent({"input 0": RuntimeError("boom"), "input 1": {"age": 45}, "input 2": {"age": 30, "gender": "female", "location_state": "near"}})
    result = await run_replay(db_session, replay.id, inference_client=None, agent_factory=lambda d: agent)
    assert result.status == "completed"
    errored = [r for r in result.results_json if r.get("error") == "boom"]
    assert len(errored) == 1 and errored[0]["agreed"] is False
    assert result.agreed_count == 1  # input 1 (age 45 matches corrected) — gender/location missing in produced
    # input 2 agrees on all three fields
