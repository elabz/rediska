"""Unit tests for MultiAgentAnalysisService.

Tests the orchestration layer including:
- Lead analysis pipeline execution
- Parallel dimension agent execution
- Meta-analysis synthesis
- Database result storage
- Error handling and graceful degradation
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    AgentPrompt,
    AnalysisDimension,
    ExternalAccount,
    LeadAnalysis,
    LeadPost,
    Provider,
    ProfileItem,
    ProfileSnapshot,
)
from rediska_core.domain.services.agent_prompt import AgentPromptService
from rediska_core.domain.services.agents import BaseAnalysisAgent
from rediska_core.domain.services.multi_agent_analysis import (
    MultiAgentAnalysisService,
)
from rediska_core.domain.schemas.multi_agent_analysis import (
    DemographicsOutput,
    MetaAnalysisOutput,
    PreferencesOutput,
    RelationshipGoalsOutput,
    RiskFlagsOutput,
    SexualPreferencesOutput,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_inference_client():
    """Create a mock inference client."""
    return AsyncMock()


@pytest.fixture
def setup_provider(db_session: Session):
    """Set up provider for tests."""
    provider = Provider(provider_id="reddit", display_name="Reddit")
    db_session.add(provider)
    db_session.flush()
    return provider


@pytest.fixture
def setup_account(db_session: Session, setup_provider):
    """Set up external account for tests."""
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
    """Set up a lead post for tests."""
    lead = LeadPost(
        provider_id="reddit",
        source_location="r/personals",
        external_post_id="post_abc123",
        post_url="https://example.com/comments/post_abc123",
        author_account_id=setup_account.id,
        title="Looking for someone special",
        body_text="I'm 25, looking for genuine connection. Interested in hiking and reading.",
        post_created_at=datetime.now(timezone.utc),
    )
    db_session.add(lead)
    db_session.flush()
    return lead


@pytest.fixture
def setup_profile_snapshot(db_session: Session, setup_account):
    """Set up profile snapshot for tests."""
    snapshot = ProfileSnapshot(
        account_id=setup_account.id,
        fetched_at=datetime.now(timezone.utc),
        summary_text="Synthetic profile summary for analysis service tests.",
        # _build_input_context reads account metadata out of signals_json only
        # when it is a dict (the shape AnalysisService writes).
        signals_json={
            "username": "test_author",
            "account_age_days": 500,
            "comment_karma": 1000,
            "post_karma": 500,
        },
        risk_flags_json=[],
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(snapshot)
    db_session.flush()
    return snapshot


@pytest.fixture
def setup_prompts(db_session: Session):
    """Set up agent prompts for testing."""
    dimensions = [
        "demographics",
        "preferences",
        "relationship_goals",
        "risk_flags",
        "sexual_preferences",
        "meta_analysis",
    ]

    for dimension in dimensions:
        prompt = AgentPrompt(
            agent_dimension=dimension,
            version=1,
            system_prompt=f"Analyze {dimension}.",
            output_schema_json={"type": "object"},
            temperature=0.7,
            max_tokens=2048,
            is_active=True,
            created_by="system",
        )
        db_session.add(prompt)

    db_session.flush()


@pytest.fixture
def multi_agent_service(
    db_session: Session, mock_inference_client
) -> MultiAgentAnalysisService:
    """Create a MultiAgentAnalysisService instance for testing."""
    prompt_service = AgentPromptService(db_session)
    return MultiAgentAnalysisService(
        db=db_session,
        inference_client=mock_inference_client,
        prompt_service=prompt_service,
    )


# =============================================================================
# LLM BOUNDARY STUB (for the full-pipeline tests below)
# =============================================================================
#
# The single mock seam for the whole pipeline is
# `BaseAnalysisAgent._run_agent_harness` — the one method that constructs an
# AgentHarness and awaits a model round-trip. Every dimension agent and the
# meta agent inherit it unchanged, so patching it on the base class stands in
# for the LLM for all six agents at once while leaving everything above it
# real: each agent's own `analyze()` (prompt assembly, Pydantic output-model
# validation, DemographicsAgent's offline geocoding post-process,
# `_store_dimension_result`), `_run_dimension_agents` (asyncio.gather +
# exception capture + the one automatic retry), the deterministic gate
# evaluator, and the service's persistence/commit logic all execute for real.


# Valid-per-schema model outputs, keyed by AgentConfig.name. Tuned so all five
# hard gates in lead_gates.evaluate_gates pass: female, a location the offline
# geocoder resolves near the default home coords, submissive vs. a dominant
# user, no stated max partner age, authentic with no red flags.
FAKE_AGENT_OUTPUTS: dict[str, dict] = {
    "demographics": {
        "age": 34,
        "age_confidence": 0.9,
        "gender": "female",
        "gender_confidence": 0.95,
        # location_state is NOT taken from this output — DemographicsAgent
        # overwrites it from classify_location(location).
        "location": "Philadelphia, PA",
        "location_confidence": 0.9,
        "evidence": ["34F in Philly"],
        "flags": [],
    },
    "preferences": {
        "hobbies": ["hiking", "reading"],
        "preferred_hobbies_found": ["hiking", "reading"],
        "kinks": ["rope"],
        "preferred_kinks_found": ["rope"],
        "lifestyle": "active",
        "compatibility_score": 0.8,
        "evidence": ["mentions hiking"],
    },
    "relationship_goals": {
        "relationship_intent": "serious",
        "intent_confidence": 0.85,
        "relationship_timeline": "no rush",
        "relationship_goals": ["long-term partner"],
        "partner_max_age": "no_max_age",
        "partner_criteria": {},
        "deal_breakers": [],
        "relationship_history": [],
        "compatibility_factors": ["shared values"],
        "incompatibility_factors": [],
        "evidence": ["wants something lasting"],
    },
    "risk_flags": {
        "is_authentic": True,
        "red_flags": [],
        "scam_indicators": [],
        "assessment": "genuine",
        "evidence": ["no promotional links"],
    },
    "sexual_preferences": {
        "ds_orientation": "submissive",
        "ds_orientation_confidence": 0.9,
        "kinks_interests": ["rope"],
        "intimacy_expectations": "traditional",
        "sexual_compatibility_notes": ["compatible"],
        "evidence": ["describes herself as submissive"],
    },
    "meta_analysis": {
        # Advisory only. Deliberately contradicts the gate verdict below so the
        # tests prove the gate — not this output — owns the recommendation.
        "recommendation": "not_recommended",
        "confidence": 0.1,
        "reasoning": "Advisory synthesis from the stubbed meta agent.",
        "failed_rule": None,
        "strengths": ["local"],
        "concerns": [],
        "compatibility_score": 0.8,
        "priority_level": "high",
    },
}


def make_fake_harness(
    calls: list[tuple[str, int]],
    failures: dict[str, set[int]] | None = None,
):
    """Build a stand-in for `BaseAnalysisAgent._run_agent_harness`.

    Args:
        calls: appended to as ``(agent_name, attempt)`` for every invocation.
        failures: agent name -> set of attempt numbers that should raise.
            `_run_dimension_agents` sets ``agent.attempt`` to 1 on the first
            pass and 2 on the automatic retry, so this keys retry behaviour.
    """
    failures = failures or {}

    async def fake_run_agent_harness(agent_self, config, input_prompt):
        name = config.name
        attempt = getattr(agent_self, "attempt", 1)
        calls.append((name, attempt))

        if attempt in failures.get(name, set()):
            raise RuntimeError(f"simulated LLM failure: {name} attempt {attempt}")

        parsed = dict(FAKE_AGENT_OUTPUTS[name])
        return {
            "success": True,
            "output": f"stub output for {name}",
            "parsed_output": parsed,
            "error": None,
            "model_info": {"model": "stub-model"},
            "raw_response": f"stub output for {name}",
        }

    return fake_run_agent_harness


@pytest.fixture
def gate_settings(monkeypatch):
    """Pin the settings the deterministic gates and geocoder read.

    `get_settings` is lru_cached and the autouse `reset_settings_cache` fixture
    only clears it around the test, so clear it again after setting the env to
    guarantee these values win regardless of fixture ordering or a stray .env.
    """
    from rediska_core.config import get_settings

    monkeypatch.setenv("HOME_LATITUDE", "40.0")
    monkeypatch.setenv("HOME_LONGITUDE", "-75.2")
    monkeypatch.setenv("LOCATION_NEAR_THRESHOLD_MILES", "200")
    monkeypatch.setenv("USER_AGE", "45")
    monkeypatch.setenv("USER_DS_ORIENTATION", "dominant")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# =============================================================================
# TESTS: Initialization and Setup
# =============================================================================


def test_service_initialization(
    db_session: Session, mock_inference_client, multi_agent_service
):
    """Test service initializes correctly."""
    assert multi_agent_service.db is db_session
    assert multi_agent_service.inference_client is mock_inference_client
    assert multi_agent_service.prompt_service is not None


# =============================================================================
# TESTS: Input Context Building
# =============================================================================


def test_build_input_context_success(
    multi_agent_service: MultiAgentAnalysisService,
    setup_lead: LeadPost,
    setup_profile_snapshot: ProfileSnapshot,
):
    """Test building input context from lead and profile data."""
    context = multi_agent_service._build_input_context(
        setup_lead, setup_profile_snapshot, []
    )

    assert context["lead"]["id"] == setup_lead.id
    assert context["lead"]["title"] == "Looking for someone special"
    assert context["lead"]["body"] is not None
    assert context["profile"]["username"] == "test_author"
    # Profile items are grouped by type rather than exposed as a flat list.
    assert context["items_by_type"] == {"post": [], "comment": [], "image": []}


def test_build_input_context_with_items(
    multi_agent_service: MultiAgentAnalysisService,
    setup_lead: LeadPost,
    setup_profile_snapshot: ProfileSnapshot,
):
    """Test building context with profile items.

    The service reads ProfileItem model attributes, groups them by item_type,
    and folds the text into profile.post_text / profile.comment_text.
    """
    items = [
        ProfileItem(
            id=1,
            account_id=setup_profile_snapshot.account_id,
            item_type="comment",
            external_item_id="c1",
            text_content="Great hiking trails",
        ),
        ProfileItem(
            id=2,
            account_id=setup_profile_snapshot.account_id,
            item_type="post",
            external_item_id="p1",
            text_content="Book recommendations",
        ),
    ]

    context = multi_agent_service._build_input_context(
        setup_lead, setup_profile_snapshot, items
    )

    assert len(context["items_by_type"]["comment"]) == 1
    assert context["items_by_type"]["comment"][0]["text"] == "Great hiking trails"
    assert len(context["items_by_type"]["post"]) == 1
    assert context["profile"]["post_text"] == "Book recommendations"
    assert context["profile"]["comment_text"] == "Great hiking trails"


# =============================================================================
# TESTS: Database Result Storage
# =============================================================================


def test_store_analysis_results_success(
    db_session: Session,
    multi_agent_service: MultiAgentAnalysisService,
    setup_lead: LeadPost,
):
    """Test storing analysis results to database."""
    analysis = LeadAnalysis(
        prompt_versions_json={},
        lead_id=setup_lead.id,
        account_id=setup_lead.author_account_id,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(analysis)
    db_session.flush()

    # Update with results
    analysis.status = "completed"
    analysis.completed_at = datetime.now(timezone.utc)
    analysis.final_recommendation = "suitable"
    analysis.recommendation_reasoning = "Test reasoning"
    analysis.confidence_score = 0.85
    analysis.demographics_json = {"age": 25}
    db_session.commit()

    # Verify storage
    stored = db_session.query(LeadAnalysis).filter(
        LeadAnalysis.id == analysis.id
    ).first()
    assert stored.final_recommendation == "suitable"
    assert stored.confidence_score == 0.85


# =============================================================================
# TESTS: Error Handling
# =============================================================================


async def test_analyze_lead_missing_lead(
    multi_agent_service: MultiAgentAnalysisService,
):
    """analyze_lead rejects an unknown lead id before doing any work."""
    with pytest.raises(ValueError, match="Lead not found: 99999"):
        await multi_agent_service.analyze_lead(99999)


async def test_analyze_lead_requires_author_account(
    db_session: Session,
    multi_agent_service: MultiAgentAnalysisService,
    setup_provider,
):
    """A lead with no author account cannot be analyzed."""
    orphan = LeadPost(
        provider_id="reddit",
        source_location="r/personals",
        external_post_id="orphan_post",
        post_url="https://example.com/comments/orphan_post",
        author_account_id=None,
        title="No author",
        body_text="Body",
    )
    db_session.add(orphan)
    db_session.flush()

    with pytest.raises(ValueError, match="has no author account"):
        await multi_agent_service.analyze_lead(orphan.id)


async def test_analyze_lead_requires_profile_snapshot(
    multi_agent_service: MultiAgentAnalysisService,
    setup_lead: LeadPost,
):
    """Analysis needs a profile snapshot for the lead's author.

    `setup_profile_snapshot` is deliberately not requested here, so the author
    has no snapshot and the guard should fire.
    """
    with pytest.raises(ValueError, match="No profile snapshot for account"):
        await multi_agent_service.analyze_lead(setup_lead.id)


# =============================================================================
# TESTS: Full analyze_lead() pipeline
# =============================================================================
#
# These drive the real 6-agent orchestration end to end with only the LLM call
# stubbed (see `make_fake_harness`). Note throughout: the recommendation and
# confidence come from `lead_gates.evaluate_gates`, a pure deterministic
# function of the dimension outputs. The meta agent is advisory and its
# `recommendation` field is ignored — the stub returns "not_recommended" on
# purpose so a test that passed by reading meta output would fail.


async def test_analyze_lead_happy_path(
    db_session: Session,
    multi_agent_service: MultiAgentAnalysisService,
    setup_lead: LeadPost,
    setup_profile_snapshot: ProfileSnapshot,
    setup_prompts,
    gate_settings,
):
    """All six agents succeed: results stored, lead updated, gate owns verdict."""
    calls: list[tuple[str, int]] = []

    with patch.object(
        BaseAnalysisAgent, "_run_agent_harness", make_fake_harness(calls)
    ):
        analysis = await multi_agent_service.analyze_lead(setup_lead.id)

    # Six agents, one attempt each, no retries needed.
    assert sorted(calls) == [
        ("demographics", 1),
        ("meta_analysis", 1),
        ("preferences", 1),
        ("relationship_goals", 1),
        ("risk_flags", 1),
        ("sexual_preferences", 1),
    ]

    assert analysis.status == "completed"
    assert analysis.completed_at is not None
    assert analysis.error_detail is None

    # Every dimension column populated from the agent's validated parsed output.
    assert analysis.demographics_json["gender"] == "female"
    # DemographicsAgent's offline geocoder post-process, not the stub, sets this.
    assert analysis.demographics_json["location_state"] == "near"
    assert analysis.demographics_json["location_near"] is True
    assert analysis.preferences_json["compatibility_score"] == 0.8
    assert analysis.relationship_goals_json["partner_max_age"] == "no_max_age"
    assert analysis.risk_flags_json["is_authentic"] is True
    assert analysis.sexual_preferences_json["ds_orientation"] == "submissive"

    # All five hard gates pass -> "suitable", scored inside the suitable band.
    verdict = analysis.meta_analysis_json["gate_verdict"]
    assert verdict["recommendation"] == "suitable"
    assert {g["gate"]: g["status"] for g in verdict["gate_results"]} == {
        "gender": "pass",
        "location": "pass",
        "ds_compatibility": "pass",
        "age_acceptance": "pass",
        "authenticity": "pass",
    }
    assert analysis.final_recommendation == "suitable"
    assert 0.6 < analysis.confidence_score <= 1.0

    # The advisory meta output is stored but explicitly does NOT set the verdict:
    # the stub said "not_recommended" and the gate verdict still stands.
    assert analysis.meta_analysis_json["recommendation"] == "not_recommended"
    assert "Advisory:" in analysis.recommendation_reasoning
    assert analysis.recommendation_reasoning.startswith("All gates passed")

    # Prompt versions recorded for all five dimensions plus meta_analysis.
    assert analysis.prompt_versions_json == {
        "demographics": 1,
        "preferences": 1,
        "relationship_goals": 1,
        "risk_flags": 1,
        "sexual_preferences": 1,
        "meta_analysis": 1,
    }

    # One AnalysisDimension row per agent.
    dim_rows = (
        db_session.query(AnalysisDimension)
        .filter(AnalysisDimension.analysis_id == analysis.id)
        .all()
    )
    assert {r.dimension for r in dim_rows} == {
        "demographics",
        "preferences",
        "relationship_goals",
        "risk_flags",
        "sexual_preferences",
        "meta_analysis",
    }
    assert all(r.status == "completed" for r in dim_rows)

    # Lead row updated with the pointer and the gate's verdict/score.
    db_session.refresh(setup_lead)
    assert setup_lead.latest_analysis_id == analysis.id
    assert setup_lead.analysis_recommendation == "suitable"
    assert setup_lead.analysis_confidence == analysis.confidence_score
    # Priority tier derived in code: compatibility 0.8 with every gate passed.
    assert setup_lead.priority == "high"
    assert setup_lead.compatibility_score == 0.8


async def test_analyze_lead_survives_permanent_dimension_failure(
    db_session: Session,
    multi_agent_service: MultiAgentAnalysisService,
    setup_lead: LeadPost,
    setup_profile_snapshot: ProfileSnapshot,
    setup_prompts,
    gate_settings,
):
    """One dimension failing both attempts degrades gracefully, not silently.

    `risk_flags` is chosen because it feeds the authenticity gate, so this also
    pins the fail-closed rule: a missing gate input yields "unclear" (and thus
    "needs_review"), never a pass.
    """
    calls: list[tuple[str, int]] = []
    fake = make_fake_harness(calls, failures={"risk_flags": {1, 2}})

    with patch.object(BaseAnalysisAgent, "_run_agent_harness", fake):
        analysis = await multi_agent_service.analyze_lead(setup_lead.id)

    # The pipeline completed rather than raising.
    assert analysis.status == "completed"
    assert analysis.completed_at is not None

    # The four healthy dimensions still stored their results.
    assert analysis.demographics_json["gender"] == "female"
    assert analysis.preferences_json["compatibility_score"] == 0.8
    assert analysis.relationship_goals_json["partner_max_age"] == "no_max_age"
    assert analysis.sexual_preferences_json["ds_orientation"] == "submissive"
    # The failed one is stored as null, not as a fabricated pass.
    assert analysis.risk_flags_json is None

    # Only risk_flags was retried; it was attempted exactly twice.
    assert calls.count(("risk_flags", 1)) == 1
    assert calls.count(("risk_flags", 2)) == 1
    assert ("demographics", 2) not in calls

    # Both failed attempts are recorded, not dropped.
    risk_rows = (
        db_session.query(AnalysisDimension)
        .filter(
            AnalysisDimension.analysis_id == analysis.id,
            AnalysisDimension.dimension == "risk_flags",
        )
        .all()
    )
    assert len(risk_rows) == 2
    assert all(r.status == "failed" for r in risk_rows)
    assert all("simulated LLM failure" in (r.error_detail or "") for r in risk_rows)
    assert {r.input_data_json["attempt"] for r in risk_rows} == {1, 2}

    # Fail-closed: the authenticity gate has no input, so it is unclear and the
    # verdict drops to needs_review even though every other gate passed.
    verdict = analysis.meta_analysis_json["gate_verdict"]
    gate_status = {g["gate"]: g["status"] for g in verdict["gate_results"]}
    assert gate_status["authenticity"] == "unclear"
    assert analysis.final_recommendation == "needs_review"
    assert 0.3 <= analysis.confidence_score <= 0.6

    db_session.refresh(setup_lead)
    assert setup_lead.latest_analysis_id == analysis.id
    assert setup_lead.analysis_recommendation == "needs_review"
    # Unclear gate blocks promotion; the tier stays at the meta agent's level.
    assert setup_lead.priority == "high"
    assert setup_lead.compatibility_score == 0.8


async def test_analyze_lead_retries_failed_dimension_once(
    db_session: Session,
    multi_agent_service: MultiAgentAnalysisService,
    setup_lead: LeadPost,
    setup_profile_snapshot: ProfileSnapshot,
    setup_prompts,
    gate_settings,
):
    """A dimension that fails once and succeeds on retry ends up successful."""
    calls: list[tuple[str, int]] = []
    fake = make_fake_harness(calls, failures={"demographics": {1}})

    with patch.object(BaseAnalysisAgent, "_run_agent_harness", fake):
        analysis = await multi_agent_service.analyze_lead(setup_lead.id)

    assert analysis.status == "completed"

    # Attempt 1 failed, attempt 2 ran and produced the stored result.
    assert calls.count(("demographics", 1)) == 1
    assert calls.count(("demographics", 2)) == 1
    assert analysis.demographics_json is not None
    assert analysis.demographics_json["gender"] == "female"

    # Both attempts are recorded in analysis_dimensions.
    demo_rows = (
        db_session.query(AnalysisDimension)
        .filter(
            AnalysisDimension.analysis_id == analysis.id,
            AnalysisDimension.dimension == "demographics",
        )
        .order_by(AnalysisDimension.id)
        .all()
    )
    assert len(demo_rows) == 2
    assert [r.status for r in demo_rows] == ["failed", "completed"]
    assert [r.input_data_json["attempt"] for r in demo_rows] == [1, 2]
    assert demo_rows[0].output_json is None
    assert demo_rows[1].output_json["gender"] == "female"

    # The retry restored the gate inputs, so the verdict is unaffected.
    assert analysis.final_recommendation == "suitable"


async def test_analyze_lead_marks_analysis_failed_and_reraises(
    db_session: Session,
    multi_agent_service: MultiAgentAnalysisService,
    setup_lead: LeadPost,
    setup_profile_snapshot: ProfileSnapshot,
    setup_prompts,
    gate_settings,
):
    """A blowup after the analysis row exists marks it failed and propagates."""
    calls: list[tuple[str, int]] = []

    with patch.object(
        BaseAnalysisAgent, "_run_agent_harness", make_fake_harness(calls)
    ), patch(
        "rediska_core.domain.services.multi_agent_analysis.evaluate_gates",
        side_effect=RuntimeError("gate evaluation exploded"),
    ):
        with pytest.raises(RuntimeError, match="gate evaluation exploded"):
            await multi_agent_service.analyze_lead(setup_lead.id)

    # The dimension agents had already run before the gate stage blew up.
    assert len(calls) == 5

    analysis = (
        db_session.query(LeadAnalysis)
        .filter(LeadAnalysis.lead_id == setup_lead.id)
        .one()
    )
    assert analysis.status == "failed"
    assert analysis.error_detail == "gate evaluation exploded"
    assert analysis.completed_at is not None
    assert analysis.final_recommendation is None

    # The lead is never pointed at a failed analysis.
    db_session.refresh(setup_lead)
    assert setup_lead.latest_analysis_id is None
    assert setup_lead.analysis_recommendation is None


# =============================================================================
# TESTS: Output Schema Validation
# =============================================================================


def test_demographics_output_schema_valid():
    """Test demographics output schema validation."""
    output = DemographicsOutput(
        age=32,
        age_confidence=0.95,
        gender="female",
        gender_confidence=0.95,
        location="PA",
        location_near=True,
        location_confidence=0.9,
        evidence=["32[F4M] #PA"],
        flags=[],
    )

    assert output.age == 32
    assert output.gender == "female"
    assert output.location_near is True


def test_preferences_output_schema_valid():
    """Test preferences output schema validation."""
    output = PreferencesOutput(
        hobbies=["hiking", "reading", "cooking"],
        preferred_hobbies_found=["hiking", "reading"],
        kinks=["rope", "spanking", "blindfolds"],
        preferred_kinks_found=["rope", "spanking"],
        lifestyle="active",
        compatibility_score=0.9,
        evidence=["loves hiking and reading", "into rope play"],
    )

    assert "hiking" in output.hobbies
    assert "rope" in output.preferred_kinks_found
    assert output.compatibility_score == 0.9


def test_relationship_goals_output_schema_valid():
    """Test relationship goals output schema validation."""
    output = RelationshipGoalsOutput(
        relationship_intent="serious",
        intent_confidence=0.85,
        relationship_timeline="within 6 months",
        relationship_goals=["find long-term partner", "build family"],
        partner_max_age="35",
        partner_criteria={"height": "5'8+"},
        deal_breakers=["smoking", "no commitment"],
        relationship_history=["3 year relationship"],
        compatibility_factors=["similar values"],
        incompatibility_factors=["different goals"],
        evidence=["post mentions"],
    )

    assert output.relationship_intent == "serious"
    assert output.intent_confidence == 0.85
    assert output.partner_max_age == "35"


def test_risk_flags_output_schema_valid():
    """Test risk flags output schema validation."""
    output = RiskFlagsOutput(
        is_authentic=False,
        red_flags=["OF mention in bio", "asks for generous partner"],
        scam_indicators=["promotes Telegram"],
        assessment="likely_scam",
        evidence=["check out my OF for more"],
    )

    assert output.is_authentic is False
    assert output.assessment == "likely_scam"
    assert len(output.red_flags) == 2


def test_sexual_preferences_output_schema_valid():
    """Test sexual preferences output schema validation."""
    output = SexualPreferencesOutput(
        ds_orientation="submissive",
        ds_orientation_confidence=0.9,
        kinks_interests=["none mentioned"],
        intimacy_expectations="traditional",
        sexual_compatibility_notes=["standard expectations"],
        evidence=["inferred from bio"],
    )

    assert output.ds_orientation == "submissive"
    assert output.ds_orientation_confidence == 0.9


def test_meta_analysis_output_schema_valid():
    """Test meta-analysis output schema validation."""
    output = MetaAnalysisOutput(
        recommendation="suitable",
        confidence=0.85,
        reasoning="All rules passed - female, nearby, submissive, accepts 45+",
        failed_rule=None,
        strengths=["submissive orientation", "local", "compatible kinks"],
        concerns=[],
        compatibility_score=0.9,
        priority_level="high",
    )

    assert output.recommendation == "suitable"
    assert output.failed_rule is None
    assert output.confidence == 0.85


# =============================================================================
# TESTS: Configuration and Settings
# =============================================================================


def test_service_uses_active_prompts(
    multi_agent_service: MultiAgentAnalysisService, setup_prompts
):
    """Test that service retrieves active prompts."""
    demo_prompt = multi_agent_service.prompt_service.get_active_prompt(
        "demographics"
    )
    assert demo_prompt is not None
    assert demo_prompt.is_active is True


# =============================================================================
# TESTS: Timestamp Handling
# =============================================================================


def test_analysis_timestamps_utc(
    db_session: Session,
    setup_lead: LeadPost,
):
    """Test that analysis timestamps are stored in UTC."""
    now = datetime.now(timezone.utc)

    analysis = LeadAnalysis(
        prompt_versions_json={},
        lead_id=setup_lead.id,
        account_id=setup_lead.author_account_id,
        status="running",
        started_at=now,
    )
    db_session.add(analysis)
    db_session.flush()

    stored = db_session.query(LeadAnalysis).filter(
        LeadAnalysis.id == analysis.id
    ).first()

    assert stored.started_at is not None
    assert stored.started_at.tzinfo == timezone.utc


# =============================================================================
# TESTS: JSON Storage
# =============================================================================


def test_analysis_json_fields_storage(
    db_session: Session,
    setup_lead: LeadPost,
):
    """Test storing complex JSON in analysis fields."""
    json_data = {
        "age": 25,
        "gender": "male",
        "location": "NYC",
        "nested": {"key1": "value1", "key2": [1, 2, 3]},
    }

    analysis = LeadAnalysis(
        prompt_versions_json={},
        lead_id=setup_lead.id,
        account_id=setup_lead.author_account_id,
        status="completed",
        started_at=datetime.now(timezone.utc),
        demographics_json=json_data,
    )
    db_session.add(analysis)
    db_session.commit()

    stored = db_session.query(LeadAnalysis).filter(
        LeadAnalysis.id == analysis.id
    ).first()

    assert stored.demographics_json == json_data
    assert stored.demographics_json["nested"]["key1"] == "value1"


# =============================================================================
# TESTS: Recommendation Status Validation
# =============================================================================


def test_recommendation_status_suitable():
    """Test 'suitable' recommendation status."""
    analysis = LeadAnalysis(
        prompt_versions_json={},
        lead_id=1,
        account_id=1,
        status="completed",
        final_recommendation="suitable",
        recommendation_reasoning="Good fit",
        confidence_score=0.85,
        started_at=datetime.now(timezone.utc),
    )
    assert analysis.final_recommendation == "suitable"


def test_recommendation_status_not_recommended():
    """Test 'not_recommended' recommendation status."""
    analysis = LeadAnalysis(
        prompt_versions_json={},
        lead_id=1,
        account_id=1,
        status="completed",
        final_recommendation="not_recommended",
        recommendation_reasoning="Safety concerns",
        confidence_score=0.9,
        started_at=datetime.now(timezone.utc),
    )
    assert analysis.final_recommendation == "not_recommended"


def test_recommendation_status_needs_review():
    """Test 'needs_review' recommendation status."""
    analysis = LeadAnalysis(
        prompt_versions_json={},
        lead_id=1,
        account_id=1,
        status="completed",
        final_recommendation="needs_review",
        recommendation_reasoning="Unclear signals",
        confidence_score=0.6,
        started_at=datetime.now(timezone.utc),
    )
    assert analysis.final_recommendation == "needs_review"
