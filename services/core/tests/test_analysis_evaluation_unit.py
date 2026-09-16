"""Unit tests for AnalysisEvaluationService and prompt replay comparison.

All fixtures are synthetic (no real scraped content). Runs against the SQLite
in-memory ``db_session`` fixture from conftest.
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from rediska_core.api.schemas.evaluations import EvaluationCreate
from rediska_core.domain.models import (
    AgentPrompt,
    AnalysisDimension,
    AnalysisEvaluation,
    AuditLog,
    ExternalAccount,
    LeadAnalysis,
    LeadPost,
    Provider,
    ScoutWatch,
    ScoutWatchPost,
)
from rediska_core.domain.services.analysis_evaluation import (
    FINAL_KEY,
    AnalysisEvaluationService,
    EvaluationSubjectNotFound,
)
from rediska_core.domain.services.prompt_replay import (
    compare_fields,
    create_replay,
    expected_value,
    labelled_cases,
    resolve_case_input,
    ReplayError,
)


# =============================================================================
# Fixtures
# =============================================================================


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _gate_verdict(recommendation: str, score: float, unclear: list[str], failed: list[str] | None = None):
    failed = failed or []
    gates = ["gender", "location", "ds_compatibility", "age_acceptance", "authenticity"]
    results = []
    for g in gates:
        if g in unclear:
            results.append({"gate": g, "status": "unclear", "reason": f"{g} is unclear"})
        elif g in failed:
            results.append({"gate": g, "status": "fail", "reason": f"{g} failed"})
        else:
            results.append({"gate": g, "status": "pass", "reason": "ok"})
    return {"recommendation": recommendation, "score": score, "gate_results": results}


@pytest.fixture
def provider(db_session):
    p = Provider(provider_id="reddit", display_name="Reddit", enabled=True)
    db_session.add(p)
    db_session.flush()
    return p


@pytest.fixture
def account(db_session, provider):
    a = ExternalAccount(
        provider_id="reddit",
        external_username="test_author",
        external_user_id="t2_test",
        remote_status="active",
    )
    db_session.add(a)
    db_session.flush()
    return a


@pytest.fixture
def prompts(db_session):
    rows = []
    for dim in ("demographics", "preferences", "relationship_goals", "risk_flags",
                "sexual_preferences", "meta_analysis"):
        p = AgentPrompt(
            agent_dimension=dim,
            version=3,
            system_prompt=f"synthetic {dim} prompt",
            output_schema_json={},
            is_active=True,
            created_by="test",
        )
        db_session.add(p)
        rows.append(p)
    db_session.flush()
    return rows


def make_lead(db_session, account, *, status="new", ext_id="p1", watch_id=None):
    lead = LeadPost(
        provider_id="reddit",
        source_location="r/test_sub",
        external_post_id=ext_id,
        post_url=f"https://example.invalid/{ext_id}",
        author_account_id=account.id,
        title="test title",
        body_text="test body",
        status=status,
        user_interests_summary="likes testing",
        user_character_summary="thorough",
        scout_watch_id=watch_id,
    )
    db_session.add(lead)
    db_session.flush()
    return lead


def make_analysis(
    db_session,
    lead,
    *,
    recommendation="suitable",
    score=0.7,
    unclear=(),
    failed=(),
    versions=None,
    completed_at=None,
    demographics=None,
    store_prompt=True,
):
    demo = demographics or {"age": 30, "gender": "female", "location_state": "near"}
    analysis = LeadAnalysis(
        lead_id=lead.id,
        account_id=lead.author_account_id,
        started_at=_now(),
        completed_at=completed_at or _now(),
        status="completed",
        demographics_json=demo,
        preferences_json={"kinks": ["a", "b"], "hobbies": ["x"]},
        relationship_goals_json={"relationship_intent": "ltr", "partner_max_age": "50"},
        risk_flags_json={"is_authentic": True, "red_flags": []},
        sexual_preferences_json={"ds_orientation": "submissive", "kinks_interests": ["a"]},
        meta_analysis_json={
            "recommendation": recommendation,
            "gate_verdict": _gate_verdict(recommendation, score, list(unclear), list(failed)),
        },
        final_recommendation=recommendation,
        recommendation_reasoning="synthetic reasoning",
        confidence_score=score,
        prompt_versions_json=versions or {"demographics": 3, "meta_analysis": 3},
        model_info_json={"model": "test-model"},
    )
    db_session.add(analysis)
    db_session.flush()
    for dim, out in (
        ("demographics", demo),
        ("preferences", analysis.preferences_json),
        ("relationship_goals", analysis.relationship_goals_json),
        ("risk_flags", analysis.risk_flags_json),
        ("sexual_preferences", analysis.sexual_preferences_json),
    ):
        db_session.add(
            AnalysisDimension(
                analysis_id=analysis.id,
                dimension=dim,
                started_at=_now(),
                completed_at=_now(),
                status="completed",
                input_data_json=(
                    {"prompt": f"Analyze this user content: {dim}", "sections": ["title"]}
                    if store_prompt
                    else {"prompt_excerpt": "x"}
                ),
                output_json=out,
                prompt_version=(versions or {}).get(dim, 3),
            )
        )
    lead.latest_analysis_id = analysis.id
    lead.analysis_recommendation = recommendation
    lead.analysis_confidence = score
    db_session.flush()
    return analysis


@pytest.fixture
def watch(db_session, provider):
    w = ScoutWatch(provider_id="reddit", source_location="r/test_sub", sort_by="new", time_filter="day")
    db_session.add(w)
    db_session.flush()
    return w


def make_scout_post(
    db_session, watch, *, ext_id, recommendation, score, unclear=(), failed=(), lead_id=None,
    first_seen=None,
):
    post = ScoutWatchPost(
        watch_id=watch.id,
        external_post_id=ext_id,
        post_title=f"scout {ext_id}",
        post_body="scout body",
        post_author="test_scout_author",
        first_seen_at=first_seen or _now(),
        analysis_status="analyzed",
        analysis_recommendation=recommendation,
        analysis_confidence=score,
        analysis_reasoning="scout reasoning",
        dimension_results_json={
            "demographics": {"age": 28, "gender": "female", "location_state": "unclear"},
            "gate_verdict": _gate_verdict(recommendation, score, list(unclear), list(failed)),
            "meta_analysis": {"recommendation": recommendation},
        },
        lead_id=lead_id,
    )
    db_session.add(post)
    db_session.flush()
    return post


# =============================================================================
# Schema validation
# =============================================================================


class TestEvaluationCreateSchema:
    def test_missing_context_requires_missing_info(self):
        with pytest.raises(ValidationError) as exc:
            EvaluationCreate(
                subject_type="lead_analysis",
                subject_id=1,
                dimension="demographics",
                human_verdict="disagree",
                reason_tags=["missing_context"],
            )
        assert "missing_info" in str(exc.value)

    def test_unknown_tag_rejected(self):
        with pytest.raises(ValidationError):
            EvaluationCreate(
                subject_type="lead_analysis",
                subject_id=1,
                human_verdict="agree",
                reason_tags=["not_a_tag"],
            )

    def test_final_correction_must_be_recommendation(self):
        with pytest.raises(ValidationError):
            EvaluationCreate(
                subject_type="lead_analysis",
                subject_id=1,
                human_verdict="disagree",
                corrected_value={"recommendation": "maybe"},
            )

    def test_tags_deduped(self):
        e = EvaluationCreate(
            subject_type="lead_analysis",
            subject_id=1,
            human_verdict="agree",
            reason_tags=["other", "other"],
        )
        assert e.reason_tags == ["other"]


# =============================================================================
# record()
# =============================================================================


class TestRecord:
    def test_disagree_final_verdict_snapshots_and_audits(self, db_session, account, prompts):
        lead = make_lead(db_session, account)
        analysis = make_analysis(db_session, lead, recommendation="not_recommended", score=0.2)
        svc = AnalysisEvaluationService(db_session)

        row = svc.record(
            EvaluationCreate(
                subject_type="lead_analysis",
                subject_id=analysis.id,
                human_verdict="disagree",
                corrected_value={"recommendation": "suitable"},
                reason_tags=["too_strict"],
            )
        )

        assert row.dimension is None
        assert row.human_verdict == "disagree"
        assert row.corrected_value_json == {"recommendation": "suitable"}
        assert row.reason_tags_json == ["too_strict"]
        assert row.agent_snapshot_json["recommendation"] == "not_recommended"
        assert row.agent_snapshot_json["confidence"] == 0.2
        assert row.agent_snapshot_json["gate_verdict"]["recommendation"] == "not_recommended"
        assert row.prompt_versions_json["demographics"] == 3
        assert row.model_name == "test-model"
        assert row.account_id == account.id

        audit = db_session.query(AuditLog).filter(AuditLog.action_type == "evaluation.record").one()
        assert audit.entity_id == row.id
        assert audit.request_json["human_verdict"] == "disagree"

        # Nothing else changed
        db_session.refresh(analysis)
        db_session.refresh(lead)
        assert analysis.final_recommendation == "not_recommended"
        assert lead.status == "new"

    def test_dimension_snapshot_uses_parsed_output(self, db_session, account, prompts):
        lead = make_lead(db_session, account)
        analysis = make_analysis(db_session, lead)
        svc = AnalysisEvaluationService(db_session)

        row = svc.record(
            EvaluationCreate(
                subject_type="lead_analysis",
                subject_id=analysis.id,
                dimension="risk_flags",
                human_verdict="partial",
                reason_tags=["risk_overcalled"],
            )
        )
        assert row.agent_snapshot_json["output"] == {"is_authentic": True, "red_flags": []}
        assert row.agent_snapshot_json["prompt_version"] == 3

    def test_reevaluation_keeps_history_and_latest_is_effective(self, db_session, account, prompts):
        lead = make_lead(db_session, account)
        analysis = make_analysis(db_session, lead)
        svc = AnalysisEvaluationService(db_session)

        first = svc.record(
            EvaluationCreate(
                subject_type="lead_analysis", subject_id=analysis.id,
                dimension="demographics", human_verdict="agree",
            )
        )
        first.created_at = _now() - timedelta(minutes=5)
        db_session.flush()
        second = svc.record(
            EvaluationCreate(
                subject_type="lead_analysis", subject_id=analysis.id,
                dimension="demographics", human_verdict="disagree",
                corrected_value={"age": 41}, reason_tags=["wrong_age"],
            )
        )

        rows = svc.list_for_subject("lead_analysis", analysis.id)
        assert {r.id for r in rows} == {first.id, second.id}
        effective = svc.effective_for_subject("lead_analysis", analysis.id)
        assert effective["demographics"].id == second.id
        assert FINAL_KEY not in effective

    def test_scout_post_without_lead(self, db_session, watch, prompts):
        post = make_scout_post(
            db_session, watch, ext_id="s1", recommendation="not_recommended", score=0.2,
            failed=["gender"],
        )
        svc = AnalysisEvaluationService(db_session)
        row = svc.record(
            EvaluationCreate(
                subject_type="scout_post", subject_id=post.id, human_verdict="disagree",
                corrected_value={"recommendation": "needs_review"}, reason_tags=["wrong_gender"],
            )
        )
        assert row.subject_type == "scout_post"
        assert row.agent_snapshot_json["recommendation"] == "not_recommended"
        assert row.agent_snapshot_json["gate_verdict"]["gate_results"][0]["status"] == "fail"
        # Versions come from the active prompts (approximation) and say so
        assert row.prompt_versions_json["_source"] == "active_at_evaluation"
        assert row.prompt_versions_json["demographics"] == 3
        db_session.refresh(post)
        assert post.evaluated_at is not None
        assert post.analysis_recommendation == "not_recommended"

    def test_scout_dimension_snapshot(self, db_session, watch, prompts):
        post = make_scout_post(db_session, watch, ext_id="s2", recommendation="needs_review", score=0.5)
        svc = AnalysisEvaluationService(db_session)
        row = svc.record(
            EvaluationCreate(
                subject_type="scout_post", subject_id=post.id, dimension="demographics",
                human_verdict="disagree", corrected_value={"location_state": "near"},
                reason_tags=["missed_location"],
            )
        )
        assert row.agent_snapshot_json["output"]["location_state"] == "unclear"

    def test_unknown_subject(self, db_session, prompts):
        svc = AnalysisEvaluationService(db_session)
        with pytest.raises(EvaluationSubjectNotFound):
            svc.record(
                EvaluationCreate(subject_type="lead_analysis", subject_id=999, human_verdict="agree")
            )
        with pytest.raises(EvaluationSubjectNotFound):
            svc.record(EvaluationCreate(subject_type="scout_post", subject_id=999, human_verdict="agree"))


# =============================================================================
# Attach helpers
# =============================================================================


class TestAttach:
    def test_attach_to_analysis_response(self, db_session, account, prompts):
        from rediska_core.api.routes.leads import _build_analysis_response

        lead = make_lead(db_session, account)
        analysis = make_analysis(db_session, lead)
        svc = AnalysisEvaluationService(db_session)
        svc.record(
            EvaluationCreate(
                subject_type="lead_analysis", subject_id=analysis.id, dimension="risk_flags",
                human_verdict="partial", reason_tags=["risk_overcalled"],
            )
        )
        svc.record(
            EvaluationCreate(
                subject_type="lead_analysis", subject_id=analysis.id, human_verdict="disagree",
                corrected_value={"recommendation": "needs_review"},
            )
        )
        db_session.expire_all()
        analysis = db_session.get(LeadAnalysis, analysis.id)
        response = svc.attach_to_analysis_response(_build_analysis_response(analysis))

        assert response.evaluation.human_verdict == "disagree"
        assert response.risk_flags.evaluation.human_verdict == "partial"
        assert response.risk_flags.evaluation.reason_tags == ["risk_overcalled"]
        assert response.demographics.evaluation is None

    def test_effective_map_has_all_keys(self, db_session, account, prompts):
        lead = make_lead(db_session, account)
        analysis = make_analysis(db_session, lead)
        svc = AnalysisEvaluationService(db_session)
        m = svc.effective_map("lead_analysis", analysis.id)
        assert set(m) == {FINAL_KEY, "demographics", "preferences", "relationship_goals",
                          "risk_flags", "sexual_preferences"}
        assert all(v is None for v in m.values())


# =============================================================================
# queue()
# =============================================================================


class TestQueue:
    def test_contradictions_first(self, db_session, account, prompts):
        # Recent plain suitable lead
        plain = make_lead(db_session, account, ext_id="plain")
        make_analysis(db_session, plain, recommendation="suitable", score=0.8)
        # Older suitable lead that the user ignored → contradiction
        ignored = make_lead(db_session, account, ext_id="ignored", status="ignored")
        make_analysis(
            db_session, ignored, recommendation="suitable", score=0.7,
            completed_at=_now() - timedelta(days=2),
        )
        svc = AnalysisEvaluationService(db_session)
        res = svc.queue(limit=10)
        # 2-day-old contradiction is within the boost window: served first
        assert res.items[0].lead_id == ignored.id
        assert res.items[0].reason == "contradiction_ignored_suitable"
        assert res.items[1].lead_id == plain.id
        assert res.items[1].reason == "sample"

    def test_promoted_not_suitable_scout_post_is_contradiction(self, db_session, account, watch, prompts):
        lead = make_lead(db_session, account, ext_id="promoted")
        post = make_scout_post(
            db_session, watch, ext_id="sp1", recommendation="not_recommended", score=0.2,
            failed=["location"], lead_id=lead.id,
        )
        svc = AnalysisEvaluationService(db_session)
        res = svc.queue(limit=10)
        assert res.items[0].subject_type == "scout_post"
        assert res.items[0].subject_id == post.id
        assert res.items[0].reason == "contradiction_promoted_not_suitable"
        assert res.items[0].failed_gate_count == 1

    def test_near_miss_needs_review_first(self, db_session, watch, prompts):
        low = make_scout_post(
            db_session, watch, ext_id="low", recommendation="needs_review", score=0.30,
            unclear=["gender", "location", "ds_compatibility", "age_acceptance"],
        )
        high = make_scout_post(
            db_session, watch, ext_id="high", recommendation="needs_review", score=0.57,
            unclear=["location"],
        )
        svc = AnalysisEvaluationService(db_session)
        res = svc.queue(limit=10, recommendation="needs_review")
        assert [i.subject_id for i in res.items] == [high.id, low.id]
        non_passing = [g for g in res.items[0].gate_results if g.status != "pass"]
        assert len(non_passing) == 1 and non_passing[0].gate == "location"
        assert res.items[0].unclear_gate_count == 1

    def test_classes_interleaved(self, db_session, account, watch, prompts):
        for i in range(3):
            lead = make_lead(db_session, account, ext_id=f"s{i}")
            make_analysis(db_session, lead, recommendation="suitable", score=0.8)
        for i in range(3):
            make_scout_post(
                db_session, watch, ext_id=f"nr{i}", recommendation="not_recommended", score=0.2,
                failed=["gender"],
            )
            make_scout_post(
                db_session, watch, ext_id=f"rv{i}", recommendation="needs_review", score=0.5,
                unclear=["location"],
            )
        svc = AnalysisEvaluationService(db_session)
        res = svc.queue(limit=6, sort="stratified")
        recs = [i.recommendation for i in res.items]
        assert set(recs) == {"suitable", "needs_review", "not_recommended"}
        assert recs[:3] == ["suitable", "needs_review", "not_recommended"]
        assert res.total_remaining == 9
        assert res.next_cursor is not None
        page2 = svc.queue(limit=6, cursor=res.next_cursor, sort="stratified")
        assert len(page2.items) == 3
        assert page2.next_cursor is None

    def test_default_order_is_newest_first(self, db_session, account, watch, prompts):
        old = make_lead(db_session, account, ext_id="old")
        make_analysis(db_session, old, recommendation="suitable", score=0.8,
                      completed_at=_now() - timedelta(days=200))
        mid = make_scout_post(db_session, watch, ext_id="mid", recommendation="not_recommended",
                              score=0.2, failed=["gender"], first_seen=_now() - timedelta(days=5))
        new = make_lead(db_session, account, ext_id="new")
        make_analysis(db_session, new, recommendation="needs_review", score=0.5, unclear=["location"])
        # An old contradiction is NOT boosted ahead of fresh items
        old_contra = make_lead(db_session, account, ext_id="oc", status="ignored")
        make_analysis(db_session, old_contra, recommendation="suitable", score=0.7,
                      completed_at=_now() - timedelta(days=120))
        items = AnalysisEvaluationService(db_session).queue(limit=10).items
        ids = [(i.subject_type, i.subject_id) for i in items]
        assert ids[0] == ("lead_analysis", new.latest_analysis_id)
        assert ids[1] == ("scout_post", mid.id)
        assert [i.reason for i in items][:2] == ["sample", "sample"]
        assert items[2].reason == "contradiction_ignored_suitable"  # 120d old, in recency order
        assert ids[-1] == ("lead_analysis", old.latest_analysis_id)

    def test_evaluated_items_leave_queue(self, db_session, account, prompts):
        lead = make_lead(db_session, account)
        analysis = make_analysis(db_session, lead)
        svc = AnalysisEvaluationService(db_session)
        assert len(svc.queue().items) == 1
        svc.record(
            EvaluationCreate(subject_type="lead_analysis", subject_id=analysis.id, human_verdict="agree")
        )
        assert svc.queue().items == []

    def test_dimension_evaluation_alone_keeps_item_queued(self, db_session, account, prompts):
        lead = make_lead(db_session, account)
        analysis = make_analysis(db_session, lead)
        svc = AnalysisEvaluationService(db_session)
        svc.record(
            EvaluationCreate(
                subject_type="lead_analysis", subject_id=analysis.id, dimension="demographics",
                human_verdict="agree",
            )
        )
        res = svc.queue()
        assert len(res.items) == 1
        assert res.items[0].evaluations["demographics"].human_verdict == "agree"

    def test_filters(self, db_session, account, watch, prompts):
        other_watch = ScoutWatch(provider_id="reddit", source_location="r/other", sort_by="new", time_filter="day")
        db_session.add(other_watch)
        db_session.flush()
        make_scout_post(db_session, watch, ext_id="w1", recommendation="needs_review", score=0.5, unclear=["location"])
        make_scout_post(db_session, other_watch, ext_id="w2", recommendation="needs_review", score=0.5, unclear=["location"])
        old = make_scout_post(
            db_session, watch, ext_id="old", recommendation="needs_review", score=0.5,
            unclear=["location"], first_seen=_now() - timedelta(days=60),
        )
        svc = AnalysisEvaluationService(db_session)
        assert {i.watch_id for i in svc.queue(watch_id=watch.id).items} == {watch.id}
        # No default window; `since` bounds the set
        assert old.id in {i.subject_id for i in svc.queue().items}
        assert old.id not in {i.subject_id for i in svc.queue(since=_now() - timedelta(days=30)).items}
        # dimension_failed: scout posts have only demographics output
        assert len(svc.queue(dimension_failed="risk_flags", watch_id=watch.id).items) == 2
        assert len(svc.queue(dimension_failed="demographics", watch_id=watch.id).items) == 0

    def test_item_context(self, db_session, account, prompts):
        lead = make_lead(db_session, account)
        make_analysis(db_session, lead, recommendation="needs_review", score=0.5, unclear=["location"])
        svc = AnalysisEvaluationService(db_session)
        item = svc.queue().items[0]
        assert item.title == "test title"
        assert item.body == "test body"
        assert item.author == "test_author"
        assert item.interests_summary == "likes testing"
        assert item.dimensions["demographics"]["age"] == 30
        assert item.prompt_versions["demographics"] == 3
        assert item.confidence == 0.5
        # The reviewer sees exactly what each agent received
        assert item.model_inputs["demographics"].source == "stored"
        assert item.model_inputs["demographics"].prompt == "Analyze this user content: demographics"

    def test_scout_item_model_input_is_reconstructed(self, db_session, watch, prompts):
        make_scout_post(db_session, watch, ext_id="mi", recommendation="needs_review", score=0.5, unclear=["location"])
        item = AnalysisEvaluationService(db_session).queue().items[0]
        mi = item.model_inputs["demographics"]
        assert mi.source == "reconstructed"
        assert "<title>scout mi</title>" in mi.prompt and "<body>scout body</body>" in mi.prompt

    def test_excerpt_only_row_is_labelled(self, db_session, account, prompts):
        lead = make_lead(db_session, account, ext_id="ex")
        make_analysis(db_session, lead, store_prompt=False)
        item = AnalysisEvaluationService(db_session).queue().items[0]
        assert item.model_inputs["demographics"].source == "excerpt"


# =============================================================================
# summary()
# =============================================================================


class TestSummary:
    def _eval(self, svc, analysis, dim, verdict, tags=(), corrected=None, missing=None):
        return svc.record(
            EvaluationCreate(
                subject_type="lead_analysis", subject_id=analysis.id, dimension=dim,
                human_verdict=verdict, reason_tags=list(tags), corrected_value=corrected,
                missing_info=missing,
            )
        )

    def test_agreement_per_prompt_version(self, db_session, account, prompts):
        svc = AnalysisEvaluationService(db_session)
        v3 = [("agree",)] * 7 + [("partial",)] * 2 + [("disagree",)]
        for i, (verdict,) in enumerate(v3):
            lead = make_lead(db_session, account, ext_id=f"v3_{i}")
            a = make_analysis(db_session, lead, versions={"demographics": 3, "meta_analysis": 3})
            self._eval(svc, a, "demographics", verdict)
        for i, verdict in enumerate(["agree", "agree", "disagree", "disagree"]):
            lead = make_lead(db_session, account, ext_id=f"v4_{i}")
            a = make_analysis(db_session, lead, versions={"demographics": 4, "meta_analysis": 3})
            self._eval(svc, a, "demographics", verdict)

        s = svc.summary()
        demo = next(d for d in s.dimensions if d.dimension == "demographics")
        assert demo.counts.total == 14
        assert demo.by_prompt_version["3"].total == 10
        assert demo.by_prompt_version["3"].agreement == 0.8
        assert demo.by_prompt_version["4"].total == 4
        assert demo.by_prompt_version["4"].agreement == 0.5

        metrics = svc.prompt_version_metrics("demographics")
        assert metrics[3].evaluations == 10 and metrics[3].agreement == 0.8
        assert metrics[4].evaluations == 4 and metrics[4].agreement == 0.5

    def test_confusion_matrix(self, db_session, account, prompts):
        svc = AnalysisEvaluationService(db_session)
        for i in range(3):
            lead = make_lead(db_session, account, ext_id=f"cm{i}")
            a = make_analysis(db_session, lead, recommendation="not_recommended", score=0.2)
            self._eval(svc, a, None, "disagree", ["too_strict"], {"recommendation": "suitable"})
        lead = make_lead(db_session, account, ext_id="cm_agree")
        a = make_analysis(db_session, lead, recommendation="suitable", score=0.8)
        self._eval(svc, a, None, "agree")

        s = svc.summary()
        assert s.confusion_matrix["not_recommended"]["suitable"] == 3
        assert s.confusion_matrix["suitable"]["suitable"] == 1
        assert s.confusion_matrix["suitable"]["not_recommended"] == 0
        final = next(d for d in s.dimensions if d.dimension == FINAL_KEY)
        assert final.tags == {"too_strict": 3}
        assert s.overall.total == 4

    def test_missing_info_aggregation(self, db_session, account, prompts):
        svc = AnalysisEvaluationService(db_session)
        texts = ["Needs age", "needs  AGE ", "Needs location", "Needs orientation", "Needs kinks"]
        for i, t in enumerate(texts):
            lead = make_lead(db_session, account, ext_id=f"mi{i}")
            a = make_analysis(db_session, lead)
            self._eval(svc, a, "demographics", "disagree", ["missing_context"], missing=t)
        s = svc.summary()
        assert len(s.missing_info) == 4
        top = s.missing_info[0]
        assert top.count == 2
        assert top.text.lower().startswith("needs age")

    def test_effective_only_and_trend(self, db_session, account, prompts):
        svc = AnalysisEvaluationService(db_session)
        lead = make_lead(db_session, account)
        a = make_analysis(db_session, lead)
        first = self._eval(svc, a, "demographics", "disagree")
        first.created_at = _now() - timedelta(minutes=1)
        db_session.flush()
        self._eval(svc, a, "demographics", "agree")
        s = svc.summary()
        assert s.total_evaluations == 1
        assert s.overall.agree == 1
        assert len(s.trend) == 1 and s.trend[0].dimension == "demographics"

    def test_since_and_watch_filters(self, db_session, account, watch, prompts):
        svc = AnalysisEvaluationService(db_session)
        lead = make_lead(db_session, account, ext_id="w", watch_id=watch.id)
        a = make_analysis(db_session, lead)
        self._eval(svc, a, None, "agree")
        lead2 = make_lead(db_session, account, ext_id="nw")
        a2 = make_analysis(db_session, lead2)
        old = self._eval(svc, a2, None, "agree")
        old.created_at = _now() - timedelta(days=10)
        db_session.flush()
        assert svc.summary(watch_id=watch.id).total_evaluations == 1
        assert svc.summary(since=_now() - timedelta(days=1)).total_evaluations == 1
        assert svc.summary().total_evaluations == 2

    def test_empty_summary(self, db_session):
        s = AnalysisEvaluationService(db_session).summary()
        assert s.total_evaluations == 0
        assert s.overall.agreement is None
        assert [d.dimension for d in s.dimensions][0] == FINAL_KEY


# =============================================================================
# export
# =============================================================================


class TestExport:
    def test_export_dimension_jsonl(self, db_session, account, prompts):
        import json

        svc = AnalysisEvaluationService(db_session)
        for i in range(3):
            lead = make_lead(db_session, account, ext_id=f"e{i}")
            a = make_analysis(db_session, lead)
            svc.record(
                EvaluationCreate(
                    subject_type="lead_analysis", subject_id=a.id, dimension="relationship_goals",
                    human_verdict="agree",
                )
            )
        lines = list(svc.export_jsonl("relationship_goals"))
        assert len(lines) == 3
        rec = json.loads(lines[0])
        assert rec["input"]["prompt"].startswith("Analyze this user content")
        assert rec["input_source"] == "stored"
        assert rec["agent_output"] == {"relationship_intent": "ltr", "partner_max_age": "50"}
        assert rec["prompt_version"] == "3"
        assert rec["human_verdict"] == "agree"
        assert "corrected_value" in rec and "reason_tags" in rec
        audit = db_session.query(AuditLog).filter(AuditLog.action_type == "evaluation.export").one()
        assert audit.request_json["dimension"] == "relationship_goals"
        assert audit.response_json["count"] == 3

    def test_export_final_and_scout_reconstruction(self, db_session, watch, prompts):
        import json

        svc = AnalysisEvaluationService(db_session)
        post = make_scout_post(db_session, watch, ext_id="ex", recommendation="needs_review", score=0.5)
        svc.record(EvaluationCreate(subject_type="scout_post", subject_id=post.id, human_verdict="agree"))
        svc.record(
            EvaluationCreate(
                subject_type="scout_post", subject_id=post.id, dimension="demographics",
                human_verdict="agree",
            )
        )
        final = [json.loads(l) for l in svc.export_jsonl(None)]
        assert len(final) == 1 and final[0]["dimension"] == FINAL_KEY
        assert final[0]["agent_output"]["recommendation"] == "needs_review"
        demo = [json.loads(l) for l in svc.export_jsonl("demographics")]
        assert demo[0]["input_source"] == "reconstructed"
        assert demo[0]["input"]["title"] == "scout ex"


# =============================================================================
# Replay: compare_fields / expected_value / case resolution / create
# =============================================================================


class TestCompareFields:
    def test_demographics_rules(self):
        expected = {"age": 30, "gender": "Female", "location_state": "near"}
        assert compare_fields("demographics", expected, {"age": 32, "gender": "female", "location_state": "near"}) == {
            "age": True, "gender": True, "location_state": True,
        }
        r = compare_fields("demographics", expected, {"age": 33, "gender": "male", "location_state": "far"})
        assert r == {"age": False, "gender": False, "location_state": False}

    def test_list_overlap_threshold(self):
        exp = {"kinks": ["a", "b", "c", "d"]}
        assert compare_fields("preferences", exp, {"kinks": ["a", "b", "c", "d"]})["kinks"] is True
        assert compare_fields("preferences", exp, {"kinks": ["A", "b", "c"]})["kinks"] is True  # 3/4
        assert compare_fields("preferences", exp, {"kinks": ["a"]})["kinks"] is False  # 1/4
        assert compare_fields("preferences", {"kinks": []}, {"kinks": None})["kinks"] is True

    def test_only_expected_fields_compared(self):
        assert compare_fields("risk_flags", {"is_authentic": True}, {"is_authentic": "true", "extra": 1}) == {
            "is_authentic": True
        }
        assert compare_fields("risk_flags", {}, {"is_authentic": True}) == {}

    def test_age_from_string(self):
        assert compare_fields("relationship_goals", {"partner_max_age": "50"}, {"partner_max_age": 52}) == {
            "partner_max_age": True
        }
        assert compare_fields("relationship_goals", {"partner_max_age": None}, {"partner_max_age": 52}) == {
            "partner_max_age": False
        }

    def test_expected_value_merges_correction(self):
        row = AnalysisEvaluation(
            subject_type="lead_analysis", subject_id=1, dimension="demographics",
            human_verdict="disagree", corrected_value_json={"age": 41},
            reason_tags_json=[], agent_snapshot_json={"output": {"age": 30, "gender": "female"}},
            prompt_versions_json={},
        )
        assert expected_value(row) == {"age": 41, "gender": "female"}
        row.human_verdict = "agree"
        assert expected_value(row) == {"age": 30, "gender": "female"}


class TestReplayCases:
    def test_labelled_cases_effective_and_capped(self, db_session, account, prompts):
        svc = AnalysisEvaluationService(db_session)
        analyses = []
        for i in range(3):
            lead = make_lead(db_session, account, ext_id=f"lc{i}")
            analyses.append(make_analysis(db_session, lead))
        for a in analyses:
            svc.record(EvaluationCreate(subject_type="lead_analysis", subject_id=a.id, dimension="demographics", human_verdict="agree"))
        # re-evaluate the first: still one case for that subject
        svc.record(EvaluationCreate(subject_type="lead_analysis", subject_id=analyses[0].id, dimension="demographics", human_verdict="disagree"))
        assert len(labelled_cases(db_session, "demographics", limit=50)) == 3
        assert len(labelled_cases(db_session, "demographics", limit=2)) == 2

    def test_resolve_case_input_sources(self, db_session, account, watch, prompts):
        svc = AnalysisEvaluationService(db_session)
        lead = make_lead(db_session, account, ext_id="ri")
        a = make_analysis(db_session, lead)
        stored = svc.record(EvaluationCreate(subject_type="lead_analysis", subject_id=a.id, dimension="demographics", human_verdict="agree"))
        assert resolve_case_input(db_session, stored).source == "stored"

        post = make_scout_post(db_session, watch, ext_id="ri_s", recommendation="needs_review", score=0.5)
        none = svc.record(EvaluationCreate(subject_type="scout_post", subject_id=post.id, dimension="demographics", human_verdict="agree"))
        case = resolve_case_input(db_session, none)
        assert case.source == "none" and not case.has_input

    def test_create_replay_preconditions(self, db_session, account, prompts):
        with pytest.raises(ReplayError, match="No labelled cases"):
            create_replay(db_session, "demographics", "draft", None, None, None, 50)
        with pytest.raises(ReplayError, match="dimension agents"):
            create_replay(db_session, "meta_analysis", "draft", None, None, None, 50)

        svc = AnalysisEvaluationService(db_session)
        lead = make_lead(db_session, account)
        a = make_analysis(db_session, lead)
        svc.record(EvaluationCreate(subject_type="lead_analysis", subject_id=a.id, dimension="demographics", human_verdict="agree"))

        replay = create_replay(db_session, "demographics", "draft prompt", None, None, None, 50)
        assert replay.status == "queued" and replay.case_count == 1
        assert replay.candidate_system_prompt == "draft prompt"
        with pytest.raises(ReplayError, match="already in progress"):
            create_replay(db_session, "demographics", "draft prompt", None, None, None, 50)
        replay.status = "completed"
        db_session.flush()
        by_version = create_replay(db_session, "demographics", None, 3, None, None, 50)
        assert by_version.candidate_version == 3
        assert by_version.candidate_system_prompt == "synthetic demographics prompt"


# =============================================================================
# Queue: subjects without any agent output, row-only analyses, promoted leads
# =============================================================================


class TestQueueOutputlessSubjects:
    def test_scout_post_with_empty_results_is_skipped(self, db_session, watch, prompts):
        post = ScoutWatchPost(
            watch_id=watch.id, external_post_id="empty", post_title="scout empty",
            first_seen_at=_now(), analysis_status="analyzed",
            analysis_recommendation="needs_review", analysis_confidence=0.5,
            dimension_results_json={},
        )
        gate_only = ScoutWatchPost(
            watch_id=watch.id, external_post_id="gateonly", post_title="scout gate only",
            first_seen_at=_now(), analysis_status="analyzed",
            analysis_recommendation="needs_review", analysis_confidence=0.3,
            dimension_results_json={"gate_verdict": _gate_verdict("needs_review", 0.3, ["gender"])},
        )
        db_session.add_all([post, gate_only])
        db_session.flush()
        assert AnalysisEvaluationService(db_session).queue().items == []

    def test_analysis_with_rows_only_is_queued_and_failed_dims_come_from_rows(
        self, db_session, account, prompts
    ):
        # Scout-promoted analyses write dimension rows but no <dim>_json columns.
        lead = make_lead(db_session, account, ext_id="rows")
        analysis = LeadAnalysis(
            lead_id=lead.id, account_id=account.id, started_at=_now(), completed_at=_now(),
            status="completed", final_recommendation="needs_review", confidence_score=0.5,
            meta_analysis_json={"gate_verdict": _gate_verdict("needs_review", 0.5, ["location"])},
            prompt_versions_json={},
        )
        db_session.add(analysis)
        db_session.flush()
        for dim, out in (("demographics", {"age": 30}), ("preferences", None), ("risk_flags", {"is_authentic": True})):
            db_session.add(AnalysisDimension(
                analysis_id=analysis.id, dimension=dim, started_at=_now(), completed_at=_now(),
                status="completed" if out else "failed", input_data_json={}, output_json=out,
                error_detail=None if out else "Invalid JSON: synthetic", prompt_version=3,
            ))
        lead.latest_analysis_id = analysis.id
        db_session.flush()

        svc = AnalysisEvaluationService(db_session)
        items = svc.queue().items
        assert [i.subject_id for i in items] == [analysis.id]
        assert items[0].dimensions["demographics"] == {"age": 30}
        assert items[0].dimensions["preferences"]["error"] == "Invalid JSON: synthetic"
        assert svc.queue(dimension_failed="preferences").items
        assert not svc.queue(dimension_failed="demographics").items

    def test_analysis_with_no_output_anywhere_is_skipped(self, db_session, account, prompts):
        lead = make_lead(db_session, account, ext_id="none")
        analysis = LeadAnalysis(
            lead_id=lead.id, account_id=account.id, started_at=_now(), completed_at=_now(),
            status="completed", final_recommendation="needs_review", confidence_score=0.3,
            meta_analysis_json={}, prompt_versions_json={},
        )
        db_session.add(analysis)
        db_session.flush()
        lead.latest_analysis_id = analysis.id
        db_session.flush()
        assert AnalysisEvaluationService(db_session).queue().items == []

    def test_manually_promoted_lead_with_non_suitable_analysis_is_contradiction(
        self, db_session, account, watch, prompts
    ):
        lead = make_lead(db_session, account, ext_id="promo")
        make_analysis(db_session, lead, recommendation="needs_review", score=0.5, unclear=["location"])
        # The scout post it came from: promoted by hand, results long gone
        db_session.add(ScoutWatchPost(
            watch_id=watch.id, external_post_id="promo", first_seen_at=_now(),
            analysis_status="analyzed", analysis_recommendation="needs_review",
            analysis_confidence=0.5, dimension_results_json={}, lead_id=lead.id,
        ))
        db_session.flush()
        items = AnalysisEvaluationService(db_session).queue().items
        assert len(items) == 1
        assert items[0].subject_type == "lead_analysis"
        assert items[0].reason == "contradiction_promoted_not_suitable"
