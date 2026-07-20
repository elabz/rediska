"""Unit tests for deterministic lead gates (lead_gates.py).

Covers per-gate pass/fail/unclear semantics, verdict combination rules,
score banding/determinism, and the service-level wiring (gates decide,
meta agent is advisory, failed dimensions retry once).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    ExternalAccount,
    LeadPost,
    Provider,
    ProfileSnapshot,
    AgentPrompt,
)
from rediska_core.domain.services.lead_gates import (
    GATE_AGE,
    GATE_AUTHENTICITY,
    GATE_DS,
    GATE_GENDER,
    GATE_LOCATION,
    SCORE_BANDS,
    GateVerdict,
    UserConstraints,
    compute_score,
    evaluate_gates,
)


CONSTRAINTS = UserConstraints(age=45, ds_orientation="dominant")


def dim(output: dict) -> dict:
    return {"success": True, "parsed_output": output}


def failed_dim() -> dict:
    return {"success": False, "parsed_output": None, "error": "boom"}


def all_pass_results(**overrides) -> dict:
    results = {
        "demographics": dim(
            {
                "gender": "female",
                "location_state": "near",
                "gender_confidence": 0.9,
                "location_confidence": 0.9,
            }
        ),
        "preferences": dim({"compatibility_score": 0.9}),
        "relationship_goals": dim(
            {"partner_max_age": "no_max_age", "intent_confidence": 0.8}
        ),
        "risk_flags": dim(
            {"is_authentic": True, "red_flags": [], "scam_indicators": []}
        ),
        "sexual_preferences": dim(
            {"ds_orientation": "submissive", "ds_orientation_confidence": 0.9}
        ),
    }
    results.update(overrides)
    return results


def gate(verdict: GateVerdict, name: str):
    return next(g for g in verdict.gate_results if g.gate == name)


# =============================================================================
# Gender gate
# =============================================================================


@pytest.mark.parametrize(
    "gender,expected",
    [
        ("female", "pass"),
        ("Female", "pass"),
        ("non-binary", "pass"),
        ("male", "fail"),
        ("unclear", "unclear"),
        ("attack helicopter", "unclear"),
        (None, "unclear"),
        ("", "unclear"),
    ],
)
def test_gender_gate(gender, expected):
    results = all_pass_results()
    results["demographics"]["parsed_output"]["gender"] = gender
    verdict = evaluate_gates(results, CONSTRAINTS)
    assert gate(verdict, GATE_GENDER).status == expected


def test_gender_gate_missing_dimension():
    results = all_pass_results()
    del results["demographics"]
    verdict = evaluate_gates(results, CONSTRAINTS)
    assert gate(verdict, GATE_GENDER).status == "unclear"
    assert gate(verdict, GATE_LOCATION).status == "unclear"


def test_gender_gate_failed_dimension():
    results = all_pass_results(demographics=failed_dim())
    verdict = evaluate_gates(results, CONSTRAINTS)
    assert gate(verdict, GATE_GENDER).status == "unclear"


# =============================================================================
# Location gate
# =============================================================================


@pytest.mark.parametrize(
    "state,expected",
    [
        ("near", "pass"),
        ("far", "fail"),
        ("unclear", "unclear"),
        (None, "unclear"),
        ("bogus-state", "unclear"),
    ],
)
def test_location_gate(state, expected):
    results = all_pass_results()
    results["demographics"]["parsed_output"]["location_state"] = state
    verdict = evaluate_gates(results, CONSTRAINTS)
    assert gate(verdict, GATE_LOCATION).status == expected


# =============================================================================
# D/s gate
# =============================================================================


@pytest.mark.parametrize(
    "orientation,expected",
    [
        ("submissive", "pass"),
        ("switch", "pass"),
        ("Dominant", "fail"),
        (None, "unclear"),
        ("vanilla", "unclear"),
    ],
)
def test_ds_gate_dominant_user(orientation, expected):
    results = all_pass_results()
    results["sexual_preferences"]["parsed_output"]["ds_orientation"] = orientation
    verdict = evaluate_gates(results, CONSTRAINTS)
    assert gate(verdict, GATE_DS).status == expected


def test_ds_gate_submissive_user():
    results = all_pass_results()
    results["sexual_preferences"]["parsed_output"]["ds_orientation"] = "dominant"
    verdict = evaluate_gates(results, UserConstraints(age=45, ds_orientation="submissive"))
    assert gate(verdict, GATE_DS).status == "pass"


def test_ds_gate_missing_dimension():
    results = all_pass_results(sexual_preferences=failed_dim())
    verdict = evaluate_gates(results, CONSTRAINTS)
    assert gate(verdict, GATE_DS).status == "unclear"


# =============================================================================
# Age acceptance gate
# =============================================================================


@pytest.mark.parametrize(
    "max_age,expected",
    [
        ("no_max_age", "pass"),
        ("NO_MAX_AGE", "pass"),
        ("50", "pass"),
        (50, "pass"),
        ("45", "pass"),
        (45, "pass"),
        ("44", "fail"),
        (30, "fail"),
        ("30ish", "unclear"),
        ("whatever", "unclear"),
        (None, "unclear"),
        ("-5", "unclear"),
    ],
)
def test_age_gate(max_age, expected):
    results = all_pass_results()
    results["relationship_goals"]["parsed_output"]["partner_max_age"] = max_age
    verdict = evaluate_gates(results, CONSTRAINTS)
    assert gate(verdict, GATE_AGE).status == expected


def test_age_gate_failed_dimension_is_unclear_not_pass():
    """A failed relationship_goals no longer silently passes the age gate."""
    results = all_pass_results(relationship_goals=failed_dim())
    verdict = evaluate_gates(results, CONSTRAINTS)
    assert gate(verdict, GATE_AGE).status == "unclear"
    assert verdict.recommendation == "needs_review"


def test_age_gate_respects_configured_user_age():
    results = all_pass_results()
    results["relationship_goals"]["parsed_output"]["partner_max_age"] = "35"
    verdict = evaluate_gates(results, UserConstraints(age=30, ds_orientation="dominant"))
    assert gate(verdict, GATE_AGE).status == "pass"


# =============================================================================
# Authenticity gate
# =============================================================================


@pytest.mark.parametrize(
    "risk,expected",
    [
        ({"is_authentic": True, "red_flags": []}, "pass"),
        ({"is_authentic": True}, "pass"),
        ({"is_authentic": False, "red_flags": []}, "fail"),
        ({"is_authentic": True, "red_flags": ["OF mention"]}, "fail"),
        ({"red_flags": []}, "unclear"),
        ({"is_authentic": "yes"}, "unclear"),
    ],
)
def test_authenticity_gate(risk, expected):
    results = all_pass_results(risk_flags=dim(risk))
    verdict = evaluate_gates(results, CONSTRAINTS)
    assert gate(verdict, GATE_AUTHENTICITY).status == expected


def test_authenticity_gate_missing_dimension():
    results = all_pass_results(risk_flags=failed_dim())
    verdict = evaluate_gates(results, CONSTRAINTS)
    assert gate(verdict, GATE_AUTHENTICITY).status == "unclear"


# =============================================================================
# Verdict combination rules
# =============================================================================


def test_all_pass_is_suitable():
    verdict = evaluate_gates(all_pass_results(), CONSTRAINTS)
    assert verdict.recommendation == "suitable"
    assert all(g.status == "pass" for g in verdict.gate_results)


def test_any_fail_is_not_recommended_even_with_unclear():
    results = all_pass_results(relationship_goals=failed_dim())
    results["demographics"]["parsed_output"]["gender"] = "male"
    verdict = evaluate_gates(results, CONSTRAINTS)
    assert verdict.recommendation == "not_recommended"


def test_any_unclear_without_fail_is_needs_review():
    results = all_pass_results()
    results["demographics"]["parsed_output"]["location_state"] = "unclear"
    verdict = evaluate_gates(results, CONSTRAINTS)
    assert verdict.recommendation == "needs_review"


def test_all_dimensions_missing_is_needs_review():
    verdict = evaluate_gates({}, CONSTRAINTS)
    assert verdict.recommendation == "needs_review"
    assert all(g.status == "unclear" for g in verdict.gate_results)


def test_verdict_serialization():
    verdict = evaluate_gates(all_pass_results(), CONSTRAINTS)
    d = verdict.to_dict()
    assert d["recommendation"] == "suitable"
    assert isinstance(d["score"], float)
    assert len(d["gate_results"]) == 5
    assert {"gate", "status", "reason"} <= set(d["gate_results"][0].keys())


# =============================================================================
# Score banding and determinism
# =============================================================================


def test_score_bands():
    suitable = evaluate_gates(all_pass_results(), CONSTRAINTS)
    lo, hi = SCORE_BANDS["suitable"]
    assert lo <= suitable.score <= hi

    review_results = all_pass_results(relationship_goals=failed_dim())
    review = evaluate_gates(review_results, CONSTRAINTS)
    lo, hi = SCORE_BANDS["needs_review"]
    assert lo <= review.score <= hi

    reject_results = all_pass_results()
    reject_results["demographics"]["parsed_output"]["gender"] = "male"
    reject = evaluate_gates(reject_results, CONSTRAINTS)
    lo, hi = SCORE_BANDS["not_recommended"]
    assert lo <= reject.score <= hi


def test_score_is_deterministic():
    results = all_pass_results()
    scores = {evaluate_gates(results, CONSTRAINTS).score for _ in range(5)}
    assert len(scores) == 1


def test_score_monotonic_in_compatibility():
    low = all_pass_results()
    low["preferences"]["parsed_output"]["compatibility_score"] = 0.1
    high = all_pass_results()
    high["preferences"]["parsed_output"]["compatibility_score"] = 0.9
    assert (
        evaluate_gates(high, CONSTRAINTS).score
        > evaluate_gates(low, CONSTRAINTS).score
    )


def test_score_missing_confidences_no_default():
    """Missing confidences contribute nothing — score sits at band base + clean margin."""
    results = {
        "demographics": dim({"gender": "female", "location_state": "near"}),
        "relationship_goals": dim({"partner_max_age": "no_max_age"}),
        "risk_flags": dim({"is_authentic": True}),
        "sexual_preferences": dim({"ds_orientation": "submissive"}),
    }
    verdict = evaluate_gates(results, CONSTRAINTS)
    assert verdict.recommendation == "suitable"
    # Only the authenticity-cleanliness margin applies; no 0.5/0.7 defaults.
    bare = compute_score("suitable", {"risk_flags": dim({"is_authentic": True})})
    assert verdict.score == bare
    assert verdict.score < 0.75


def test_red_flags_reduce_score_margin():
    clean = all_pass_results()
    flagged = all_pass_results(
        risk_flags=dim({"is_authentic": True, "red_flags": [], "scam_indicators": ["TG"]})
    )
    assert (
        evaluate_gates(clean, CONSTRAINTS).score
        > evaluate_gates(flagged, CONSTRAINTS).score
    )


# =============================================================================
# Service-level wiring
# =============================================================================


@pytest.fixture
def setup_provider(db_session: Session):
    provider = Provider(provider_id="reddit", display_name="Reddit")
    db_session.add(provider)
    db_session.flush()
    return provider


@pytest.fixture
def setup_account(db_session: Session, setup_provider):
    account = ExternalAccount(
        provider_id="reddit",
        external_username="test_author",
        external_user_id="t2_abc123",
        remote_status="active",
    )
    db_session.add(account)
    db_session.flush()
    return account


@pytest.fixture
def setup_lead(db_session: Session, setup_provider, setup_account):
    lead = LeadPost(
        provider_id="reddit",
        source_location="r/personals",
        external_post_id="post_abc123",
        author_account_id=setup_account.id,
        title="Looking for someone special",
        body_text="I'm 25, looking for genuine connection.",
        external_created_at=datetime.now(timezone.utc),
        local_saved_at=datetime.now(timezone.utc),
    )
    db_session.add(lead)
    db_session.flush()
    return lead


@pytest.fixture
def setup_profile_snapshot(db_session: Session, setup_account):
    snapshot = ProfileSnapshot(
        account_id=setup_account.id,
        provider_id="reddit",
        external_username="test_author",
        profile_data_json={"username": "test_author"},
        fetched_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(snapshot)
    db_session.flush()
    return snapshot


@pytest.fixture
def setup_prompts(db_session: Session):
    for dimension in [
        "demographics",
        "preferences",
        "relationship_goals",
        "risk_flags",
        "sexual_preferences",
        "meta_analysis",
    ]:
        db_session.add(
            AgentPrompt(
                agent_dimension=dimension,
                version=1,
                system_prompt=f"Analyze {dimension}.",
                output_schema_json={"type": "object"},
                temperature=0.7,
                max_tokens=2048,
                is_active=True,
                created_by="system",
            )
        )
    db_session.flush()


@pytest.fixture
def service(db_session: Session):
    from rediska_core.domain.services.agent_prompt import AgentPromptService
    from rediska_core.domain.services.multi_agent_analysis import (
        MultiAgentAnalysisService,
    )

    return MultiAgentAnalysisService(
        db=db_session,
        inference_client=AsyncMock(),
        prompt_service=AgentPromptService(db_session),
    )


async def test_meta_disagreement_cannot_flip_verdict(
    db_session: Session,
    service,
    setup_lead,
    setup_profile_snapshot,
    setup_prompts,
):
    """The gate verdict wins even when the advisory meta output says suitable."""
    results = all_pass_results()
    results["demographics"]["parsed_output"]["gender"] = "male"  # gate fails

    service._run_dimension_agents = AsyncMock(return_value=results)
    service._run_meta_analysis = AsyncMock(
        return_value={
            "success": True,
            "parsed_output": {
                "recommendation": "suitable",
                "confidence": 0.99,
                "reasoning": "Model disagrees",
            },
        }
    )

    analysis = await service.analyze_lead(setup_lead.id)

    assert analysis.final_recommendation == "not_recommended"
    lo, hi = SCORE_BANDS["not_recommended"]
    assert lo <= analysis.confidence_score <= hi
    # Advisory output preserved alongside the gate verdict
    assert analysis.meta_analysis_json["recommendation"] == "suitable"
    assert (
        analysis.meta_analysis_json["gate_verdict"]["recommendation"]
        == "not_recommended"
    )


async def test_failed_relationship_goals_yields_needs_review(
    db_session: Session,
    service,
    setup_lead,
    setup_profile_snapshot,
    setup_prompts,
):
    """A relationship_goals failure (after retry) fail-closes to needs_review."""
    results = all_pass_results(relationship_goals=failed_dim())
    service._run_dimension_agents = AsyncMock(return_value=results)
    service._run_meta_analysis = AsyncMock(
        return_value={"success": False, "error": "boom", "parsed_output": None}
    )

    analysis = await service.analyze_lead(setup_lead.id)

    assert analysis.final_recommendation == "needs_review"
    assert analysis.status == "completed"  # meta failure does not block
    lo, hi = SCORE_BANDS["needs_review"]
    assert lo <= analysis.confidence_score <= hi


async def test_dimension_retry_runs_failed_dimension_twice(service):
    """A failed dimension agent is re-run once; the retry's result is used."""
    calls: dict[str, int] = {}

    class StubAgent:
        def __init__(self, client, chat_template=None):
            self.attempt = 1

        async def analyze(self, dimension, input_context, prompt, analysis_id, db):
            calls[dimension] = calls.get(dimension, 0) + 1
            if dimension == "relationship_goals" and calls[dimension] == 1:
                return {"success": False, "error": "transient", "parsed_output": None}
            return {"success": True, "parsed_output": {"ok": True}}

    from unittest.mock import patch

    service.prompt_service = MagicMock()
    service.prompt_service.get_active_prompt.return_value = MagicMock(version=1)

    with (
        patch(
            "rediska_core.domain.services.agents.demographics.DemographicsAgent",
            StubAgent,
        ),
        patch(
            "rediska_core.domain.services.agents.agent_implementations.PreferencesAgent",
            StubAgent,
        ),
        patch(
            "rediska_core.domain.services.agents.agent_implementations.RelationshipGoalsAgent",
            StubAgent,
        ),
        patch(
            "rediska_core.domain.services.agents.agent_implementations.RiskFlagsAgent",
            StubAgent,
        ),
        patch(
            "rediska_core.domain.services.agents.agent_implementations.SexualPreferencesAgent",
            StubAgent,
        ),
    ):
        results = await service._run_dimension_agents(
            analysis_id=None,
            input_context={},
            dimensions=service.DIMENSIONS,
        )

    assert calls["relationship_goals"] == 2  # retried once
    assert all(calls[d] == 1 for d in calls if d != "relationship_goals")
    assert results["relationship_goals"]["success"] is True  # retry recovered


def test_normalize_meta_output_no_default_confidence(service):
    """Missing model confidence stays missing — no 0.7/0.5-style defaults."""
    normalized = service._normalize_meta_output({"recommendation": "suitable"})
    assert normalized["confidence"] is None

    normalized = service._normalize_meta_output({"recommendation": "needs_review"})
    assert normalized["confidence"] is None

    normalized = service._normalize_meta_output(
        {"recommendation": "suitable", "confidence": 0.42}
    )
    assert normalized["confidence"] == 0.42
