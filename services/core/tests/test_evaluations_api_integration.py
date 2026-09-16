"""Integration tests for the evaluation and prompt replay API routes.

Covers auth, validation, audit rows, evaluation fields on analysis payloads,
scout run detail, per-version prompt metrics, and replay preconditions.
All data is synthetic.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from rediska_core.api.deps import get_current_user
from rediska_core.domain.models import (
    AgentPrompt,
    AnalysisDimension,
    AuditLog,
    ExternalAccount,
    Job,
    LeadAnalysis,
    LeadPost,
    LocalUser,
    PromptReplay,
    Provider,
    ScoutWatch,
    ScoutWatchPost,
    ScoutWatchRun,
)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def user(db_session):
    u = LocalUser(username="test_reviewer", password_hash="not-a-real-hash")
    db_session.add(u)
    db_session.flush()
    return u


@pytest.fixture
async def auth_client(test_app, db_session, user):
    test_app.dependency_overrides[get_current_user] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        yield ac
    test_app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
async def anon_client(test_app, db_session):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def seed(db_session):
    """Provider, account, prompts, a lead with a completed analysis, a scout post."""
    db_session.add(Provider(provider_id="reddit", display_name="Reddit", enabled=True))
    db_session.flush()
    account = ExternalAccount(
        provider_id="reddit", external_username="test_author", external_user_id="t2_x",
        remote_status="active",
    )
    db_session.add(account)
    db_session.flush()
    for dim in ("demographics", "preferences", "relationship_goals", "risk_flags",
                "sexual_preferences", "meta_analysis"):
        db_session.add(AgentPrompt(
            agent_dimension=dim, version=2, system_prompt=f"synthetic {dim}",
            output_schema_json={}, is_active=True, created_by="test",
        ))
    db_session.flush()

    lead = LeadPost(
        provider_id="reddit", source_location="r/test_sub", external_post_id="l1",
        post_url="https://example.invalid/l1", author_account_id=account.id,
        title="t", body_text="b", status="new",
    )
    db_session.add(lead)
    db_session.flush()
    analysis = LeadAnalysis(
        lead_id=lead.id, account_id=account.id, started_at=_now(), completed_at=_now(),
        status="completed",
        demographics_json={"age": 30, "gender": "female", "location_state": "near"},
        risk_flags_json={"is_authentic": True, "red_flags": []},
        meta_analysis_json={"recommendation": "suitable", "gate_verdict": {
            "recommendation": "suitable", "score": 0.8, "gate_results": []}},
        final_recommendation="suitable", confidence_score=0.8,
        prompt_versions_json={"demographics": 2, "risk_flags": 2, "meta_analysis": 2},
        model_info_json={"model": "test-model"},
    )
    db_session.add(analysis)
    db_session.flush()
    for dim, out in (("demographics", analysis.demographics_json), ("risk_flags", analysis.risk_flags_json)):
        db_session.add(AnalysisDimension(
            analysis_id=analysis.id, dimension=dim, started_at=_now(), completed_at=_now(),
            status="completed", input_data_json={"prompt": f"input for {dim}"},
            output_json=out, prompt_version=2,
        ))
    lead.latest_analysis_id = analysis.id
    lead.analysis_recommendation = "suitable"
    lead.analysis_confidence = 0.8
    db_session.flush()

    watch = ScoutWatch(provider_id="reddit", source_location="r/test_sub", sort_by="new", time_filter="day")
    db_session.add(watch)
    db_session.flush()
    run = ScoutWatchRun(watch_id=watch.id, started_at=_now(), completed_at=_now(), status="completed")
    db_session.add(run)
    db_session.flush()
    post = ScoutWatchPost(
        watch_id=watch.id, run_id=run.id, external_post_id="s1", post_title="scout s1",
        post_body="scout body", post_author="test_scout", first_seen_at=_now(),
        analysis_status="analyzed", analysis_recommendation="needs_review",
        analysis_confidence=0.5,
        dimension_results_json={
            "demographics": {"age": 28, "location_state": "unclear"},
            "gate_verdict": {"recommendation": "needs_review", "score": 0.5, "gate_results": [
                {"gate": "location", "status": "unclear", "reason": "location is unclear"}]},
        },
    )
    db_session.add(post)
    db_session.commit()
    return {"lead": lead, "analysis": analysis, "watch": watch, "run": run, "post": post}


class TestAuth:
    async def test_endpoints_require_auth(self, anon_client):
        assert (await anon_client.get("/evaluations/queue")).status_code == 401
        assert (await anon_client.get("/evaluations/summary")).status_code == 401
        assert (await anon_client.get("/evaluations/export")).status_code == 401
        r = await anon_client.post("/evaluations", json={
            "subject_type": "lead_analysis", "subject_id": 1, "human_verdict": "agree"})
        assert r.status_code == 401


class TestRecordAndRead:
    async def test_record_final_verdict_and_audit(self, auth_client, db_session, seed):
        analysis = seed["analysis"]
        r = await auth_client.post("/evaluations", json={
            "subject_type": "lead_analysis", "subject_id": analysis.id,
            "human_verdict": "disagree",
            "corrected_value": {"recommendation": "needs_review"},
            "reason_tags": ["too_lenient"], "notes": "synthetic note",
        })
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["dimension"] is None
        assert body["agent_snapshot"]["recommendation"] == "suitable"
        assert body["prompt_versions"]["meta_analysis"] == 2
        assert body["created_by"] == "test_reviewer"

        audit = db_session.query(AuditLog).filter(AuditLog.action_type == "evaluation.record").one()
        assert audit.entity_id == body["id"]

        r = await auth_client.get("/evaluations", params={
            "subject_type": "lead_analysis", "subject_id": analysis.id})
        assert r.status_code == 200
        data = r.json()
        assert len(data["evaluations"]) == 1
        assert data["effective"]["final"]["human_verdict"] == "disagree"
        assert data["effective"]["demographics"] is None

    async def test_missing_info_validation(self, auth_client, seed):
        r = await auth_client.post("/evaluations", json={
            "subject_type": "lead_analysis", "subject_id": seed["analysis"].id,
            "dimension": "demographics", "human_verdict": "disagree",
            "reason_tags": ["missing_context"],
        })
        assert r.status_code == 422
        assert "missing_info" in r.text

    async def test_unknown_subject_404(self, auth_client, seed):
        r = await auth_client.post("/evaluations", json={
            "subject_type": "scout_post", "subject_id": 99999, "human_verdict": "agree"})
        assert r.status_code == 404

    async def test_vocabulary(self, auth_client):
        r = await auth_client.get("/evaluations/vocabulary")
        assert r.status_code == 200
        assert "missing_context" in r.json()["reason_tags"]
        assert "demographics" in r.json()["dimensions"]


class TestAnalysisPayloads:
    async def test_lead_analysis_carries_evaluation_fields(self, auth_client, seed):
        lead, analysis = seed["lead"], seed["analysis"]
        r = await auth_client.get(f"/leads/{lead.id}/analysis")
        assert r.status_code == 200
        assert r.json()["evaluation"] is None
        assert r.json()["risk_flags"]["evaluation"] is None
        assert r.json()["risk_flags"]["model_input"] == {
            "source": "stored", "prompt": "input for risk_flags", "sections": [],
            "total_chars": len("input for risk_flags"), "attempt": None,
        }

        await auth_client.post("/evaluations", json={
            "subject_type": "lead_analysis", "subject_id": analysis.id,
            "dimension": "risk_flags", "human_verdict": "partial",
            "reason_tags": ["risk_overcalled"],
        })
        await auth_client.post("/evaluations", json={
            "subject_type": "lead_analysis", "subject_id": analysis.id,
            "human_verdict": "disagree", "corrected_value": {"recommendation": "not_recommended"},
        })

        for url in (f"/leads/{lead.id}/analysis", f"/leads/{lead.id}/analysis/{analysis.id}"):
            r = await auth_client.get(url)
            assert r.status_code == 200, url
            data = r.json()
            assert data["evaluation"]["human_verdict"] == "disagree"
            assert data["risk_flags"]["evaluation"]["human_verdict"] == "partial"
            assert data["risk_flags"]["evaluation"]["reason_tags"] == ["risk_overcalled"]
            assert data["demographics"]["evaluation"] is None

        r = await auth_client.get(f"/leads/{lead.id}/analysis/history")
        assert r.status_code == 200
        assert r.json()[0]["evaluation"]["human_verdict"] == "disagree"

    async def test_scout_run_detail_carries_evaluations(self, auth_client, db_session, seed):
        watch, run, post = seed["watch"], seed["run"], seed["post"]
        r = await auth_client.get(f"/scout-watches/{watch.id}/runs/{run.id}")
        assert r.status_code == 200
        p = r.json()["posts"][0]
        assert p["evaluations"]["final"] is None
        assert p["evaluated_at"] is None

        r = await auth_client.post("/evaluations", json={
            "subject_type": "scout_post", "subject_id": post.id, "human_verdict": "agree"})
        assert r.status_code == 201, r.text

        r = await auth_client.get(f"/scout-watches/{watch.id}/runs/{run.id}")
        p = r.json()["posts"][0]
        assert p["evaluations"]["final"]["human_verdict"] == "agree"
        assert p["evaluated_at"] is not None


class TestQueueSummaryExport:
    async def test_queue_summary_export_flow(self, auth_client, db_session, seed):
        r = await auth_client.get("/evaluations/queue", params={"limit": 5})
        assert r.status_code == 200
        items = r.json()["items"]
        assert {i["subject_type"] for i in items} == {"lead_analysis", "scout_post"}
        scout_item = next(i for i in items if i["subject_type"] == "scout_post")
        assert scout_item["gate_results"][0]["gate"] == "location"
        assert scout_item["title"] == "scout s1"

        r = await auth_client.get("/evaluations/queue", params={"dimension_failed": "bogus"})
        assert r.status_code == 400

        r = await auth_client.get("/evaluations/summary")
        assert r.status_code == 200
        assert r.json()["total_evaluations"] == 0

        await auth_client.post("/evaluations", json={
            "subject_type": "lead_analysis", "subject_id": seed["analysis"].id,
            "dimension": "demographics", "human_verdict": "agree"})
        r = await auth_client.get("/evaluations/summary")
        assert r.json()["total_evaluations"] == 1
        demo = next(d for d in r.json()["dimensions"] if d["dimension"] == "demographics")
        assert demo["by_prompt_version"]["2"]["agreement"] == 1.0

        r = await auth_client.get("/evaluations/export", params={"dimension": "demographics"})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/x-ndjson")
        lines = [l for l in r.text.splitlines() if l.strip()]
        assert len(lines) == 1
        assert '"input for demographics"' in lines[0]
        audit = db_session.query(AuditLog).filter(AuditLog.action_type == "evaluation.export").one()
        assert audit.response_json["count"] == 1

        r = await auth_client.get("/evaluations/export", params={"dimension": "bogus"})
        assert r.status_code == 400


class TestPromptVersionsAndReplay:
    async def test_versions_include_metrics(self, auth_client, seed):
        await auth_client.post("/evaluations", json={
            "subject_type": "lead_analysis", "subject_id": seed["analysis"].id,
            "dimension": "risk_flags", "human_verdict": "partial"})
        r = await auth_client.get("/agent-prompts/risk_flags/versions")
        assert r.status_code == 200, r.text
        v2 = next(v for v in r.json()["versions"] if v["version"] == 2)
        assert v2["evaluations"] == 1 and v2["agreement"] == 0.5
        r = await auth_client.get("/agent-prompts/demographics/versions")
        assert r.json()["versions"][0]["evaluations"] == 0
        assert r.json()["versions"][0]["agreement"] is None

    async def test_replay_rejected_without_cases(self, auth_client, seed):
        r = await auth_client.post("/agent-prompts/demographics/replay", json={"system_prompt": "draft"})
        assert r.status_code == 409
        assert "No labelled cases" in r.json()["detail"]

    async def test_replay_lifecycle(self, auth_client, db_session, seed):
        await auth_client.post("/evaluations", json={
            "subject_type": "lead_analysis", "subject_id": seed["analysis"].id,
            "dimension": "demographics", "human_verdict": "agree"})

        with patch("rediska_core.api.routes.agent_prompts._enqueue_replay") as enqueue:
            r = await auth_client.post("/agent-prompts/demographics/replay",
                                       json={"system_prompt": "draft prompt", "max_cases": 5})
            assert r.status_code == 202, r.text
            enqueue.assert_called_once()
        body = r.json()
        assert body["status"] == "queued" and body["case_count"] == 1
        replay_id = body["id"]

        job = db_session.query(Job).filter(Job.dedupe_key == f"evaluation.replay_prompt:{replay_id}").one()
        assert job.job_type == "evaluation.replay_prompt" and job.status == "queued"
        assert db_session.query(AuditLog).filter(AuditLog.action_type == "prompt.replay").count() == 1

        # Active prompt unchanged
        r = await auth_client.get("/agent-prompts/demographics")
        assert r.json()["version"] == 2 and r.json()["system_prompt"] == "synthetic demographics"

        # A second replay is rejected while one is queued
        with patch("rediska_core.api.routes.agent_prompts._enqueue_replay"):
            r = await auth_client.post("/agent-prompts/demographics/replay", json={"version": 2})
            assert r.status_code == 409

        r = await auth_client.get("/agent-prompts/demographics/replays")
        assert r.status_code == 200
        assert [x["id"] for x in r.json()["replays"]] == [replay_id]

        r = await auth_client.get(f"/agent-prompts/demographics/replays/{replay_id}")
        assert r.status_code == 200
        assert r.json()["candidate_system_prompt"] == "draft prompt"

        r = await auth_client.post(f"/agent-prompts/demographics/replays/{replay_id}/cancel")
        assert r.status_code == 200 and r.json()["status"] == "cancelled"
        db_session.expire_all()
        assert db_session.get(PromptReplay, replay_id).status == "cancelled"
        assert db_session.get(Job, job.id).status == "cancelled"

        r = await auth_client.get("/agent-prompts/preferences/replays/999")
        assert r.status_code == 404
