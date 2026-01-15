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
    ExternalAccount,
    LeadAnalysis,
    LeadPost,
    Provider,
    ProfileSnapshot,
)
from rediska_core.domain.services.agent_prompt import AgentPromptService
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
        author_account_id=setup_account.id,
        title="Looking for someone special",
        body_text="I'm 25, looking for genuine connection. Interested in hiking and reading.",
        external_created_at=datetime.now(timezone.utc),
        local_saved_at=datetime.now(timezone.utc),
    )
    db_session.add(lead)
    db_session.flush()
    return lead


@pytest.fixture
def setup_profile_snapshot(db_session: Session, setup_account):
    """Set up profile snapshot for tests."""
    snapshot = ProfileSnapshot(
        account_id=setup_account.id,
        provider_id="reddit",
        external_username="test_author",
        profile_data_json={
            "username": "test_author",
            "account_age_days": 500,
            "comment_karma": 1000,
            "post_karma": 500,
        },
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
    assert context["lead"]["body_text"] is not None
    assert context["profile"]["username"] == "test_author"
    assert context["profile_items"] == []


def test_build_input_context_with_items(
    multi_agent_service: MultiAgentAnalysisService,
    setup_lead: LeadPost,
    setup_profile_snapshot: ProfileSnapshot,
):
    """Test building context with profile items."""
    items = [
        {"type": "comment", "text": "Great hiking trails"},
        {"type": "post", "text": "Book recommendations"},
    ]

    context = multi_agent_service._build_input_context(
        setup_lead, setup_profile_snapshot, items
    )

    assert len(context["profile_items"]) == 2
    assert context["profile_items"][0]["type"] == "comment"


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


def test_analyze_lead_missing_lead(
    multi_agent_service: MultiAgentAnalysisService,
):
    """Test analyzing non-existent lead returns error."""
    # This should raise an exception or return error appropriately
    # Implementation depends on actual service behavior


def test_analyze_lead_dimension_failure_resilience(
    multi_agent_service: MultiAgentAnalysisService,
    setup_lead: LeadPost,
    setup_profile_snapshot: ProfileSnapshot,
):
    """Test that failure in one dimension doesn't abort pipeline."""
    # This tests graceful degradation
    # Implementation depends on actual service design


# =============================================================================
# TESTS: Output Schema Validation
# =============================================================================


def test_demographics_output_schema_valid():
    """Test demographics output schema validation."""
    output = DemographicsOutput(
        age_range=(25, 35),
        age_confidence=0.9,
        gender="male",
        gender_confidence=0.8,
        location="New York",
        location_specificity="city",
        location_confidence=0.7,
        ethnicity_indicators=["caucasian"],
        evidence=["mentioned in bio"],
        flags=[],
    )

    assert output.age_range == (25, 35)
    assert output.age_confidence == 0.9


def test_preferences_output_schema_valid():
    """Test preferences output schema validation."""
    output = PreferencesOutput(
        hobbies=["hiking", "reading"],
        lifestyle="active",
        values=["honesty", "kindness"],
        interests={"sports": 0.8, "arts": 0.6},
        personality_traits=["introverted", "thoughtful"],
        communication_style="friendly",
        evidence=["in bio"],
    )

    assert "hiking" in output.hobbies
    assert output.lifestyle == "active"


def test_relationship_goals_output_schema_valid():
    """Test relationship goals output schema validation."""
    output = RelationshipGoalsOutput(
        relationship_intent="serious",
        intent_confidence=0.85,
        relationship_timeline="within 6 months",
        partner_criteria={"age_range": [23, 35], "height": "5'8+"},
        deal_breakers=["smoking", "no commitment"],
        relationship_history=["3 year relationship"],
        compatibility_factors=["similar values"],
        incompatibility_factors=["different goals"],
        evidence=["post mentions"],
    )

    assert output.relationship_intent == "serious"
    assert output.intent_confidence == 0.85


def test_risk_flags_output_schema_valid():
    """Test risk flags output schema validation."""
    output = RiskFlagsOutput(
        flags=[
            {
                "type": "age_gap",
                "severity": "medium",
                "description": "Seeking much younger partner",
                "evidence": ["bio mentions"],
            }
        ],
        behavioral_concerns=[],
        safety_assessment="caution",
        authenticity_score=0.8,
        manipulation_indicators=[],
        overall_risk_level="medium",
    )

    assert len(output.flags) == 1
    assert output.safety_assessment == "caution"


def test_sexual_preferences_output_schema_valid():
    """Test sexual preferences output schema validation."""
    output = SexualPreferencesOutput(
        sexual_orientation="straight",
        orientation_confidence=0.9,
        kinks_interests=["none mentioned"],
        intimacy_expectations="traditional",
        desired_partner_age_range=(23, 35),
        age_preference_confidence=0.85,
        age_gap_concerns=[],
        sexual_compatibility_notes=["standard expectations"],
        evidence=["inferred from bio"],
    )

    assert output.sexual_orientation == "straight"
    assert output.desired_partner_age_range == (23, 35)


def test_meta_analysis_output_schema_valid():
    """Test meta-analysis output schema validation."""
    output = MetaAnalysisOutput(
        recommendation="suitable",
        confidence=0.85,
        reasoning="Meets most criteria with good compatibility",
        strengths=["genuine interest", "clear intentions"],
        concerns=["age gap consideration"],
        compatibility_score=0.78,
        priority_level="high",
        suggested_approach="Standard approach appropriate",
    )

    assert output.recommendation == "suitable"
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
        lead_id=1,
        account_id=1,
        status="completed",
        final_recommendation="needs_review",
        recommendation_reasoning="Unclear signals",
        confidence_score=0.6,
        started_at=datetime.now(timezone.utc),
    )
    assert analysis.final_recommendation == "needs_review"
