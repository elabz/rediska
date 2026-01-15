"""Unit tests for multi-agent analysis ORM models.

Tests the database layer including:
- AgentPrompt model and relationships
- LeadAnalysis model and relationships
- AnalysisDimension model and relationships
- Enum fields and constraints
- Timestamp handling
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    AgentPrompt,
    AnalysisDimension,
    AnalysisStatus,
    DimensionStatus,
    ExternalAccount,
    LeadAnalysis,
    LeadPost,
    Provider,
    RecommendationStatus,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def setup_provider_and_account(db_session: Session):
    """Set up provider and account for testing."""
    provider = Provider(provider_id="reddit", display_name="Reddit")
    db_session.add(provider)
    db_session.flush()

    account = ExternalAccount(
        provider_id="reddit",
        external_username="test_user",
        external_user_id="t2_test123",
        remote_status="active",
    )
    db_session.add(account)
    db_session.flush()

    return provider, account


@pytest.fixture
def setup_lead(db_session: Session, setup_provider_and_account):
    """Set up a lead post for testing."""
    provider, account = setup_provider_and_account

    lead = LeadPost(
        provider_id="reddit",
        source_location="r/personals",
        external_post_id="post_abc123",
        author_account_id=account.id,
        title="Test Post",
        body_text="Test body",
        external_created_at=datetime.now(timezone.utc),
        local_saved_at=datetime.now(timezone.utc),
    )
    db_session.add(lead)
    db_session.flush()

    return lead


# =============================================================================
# TESTS: AgentPrompt Model
# =============================================================================


def test_agent_prompt_creation(db_session: Session):
    """Test creating an AgentPrompt record."""
    prompt = AgentPrompt(
        agent_dimension="demographics",
        version=1,
        system_prompt="Analyze demographics data.",
        output_schema_json={"type": "object", "properties": {}},
        temperature=0.7,
        max_tokens=2048,
        is_active=True,
        created_by="system",
        notes="Initial seed",
    )
    db_session.add(prompt)
    db_session.commit()

    stored = db_session.query(AgentPrompt).filter(
        AgentPrompt.id == prompt.id
    ).first()

    assert stored is not None
    assert stored.agent_dimension == "demographics"
    assert stored.version == 1
    assert stored.is_active is True


def test_agent_prompt_version_uniqueness(db_session: Session):
    """Test that dimension + version combination is unique."""
    prompt1 = AgentPrompt(
        agent_dimension="demographics",
        version=1,
        system_prompt="v1",
        output_schema_json={},
        temperature=0.7,
        max_tokens=2048,
        is_active=True,
        created_by="system",
    )
    db_session.add(prompt1)
    db_session.commit()

    # Try to create duplicate - should fail
    prompt2 = AgentPrompt(
        agent_dimension="demographics",
        version=1,
        system_prompt="v2",
        output_schema_json={},
        temperature=0.7,
        max_tokens=2048,
        is_active=False,
        created_by="system",
    )
    db_session.add(prompt2)

    # Commit should fail due to unique constraint
    with pytest.raises(Exception):  # SQLAlchemy integrity error
        db_session.commit()


def test_agent_prompt_different_versions_allowed(db_session: Session):
    """Test that different versions of same dimension are allowed."""
    for v in range(1, 4):
        prompt = AgentPrompt(
            agent_dimension="demographics",
            version=v,
            system_prompt=f"Version {v}",
            output_schema_json={},
            temperature=0.7,
            max_tokens=2048,
            is_active=(v == 3),
            created_by="system",
        )
        db_session.add(prompt)

    db_session.commit()

    prompts = db_session.query(AgentPrompt).filter(
        AgentPrompt.agent_dimension == "demographics"
    ).all()

    assert len(prompts) == 3
    assert {p.version for p in prompts} == {1, 2, 3}


def test_agent_prompt_default_values(db_session: Session):
    """Test default values for AgentPrompt fields."""
    prompt = AgentPrompt(
        agent_dimension="test",
        version=1,
        system_prompt="Test",
        output_schema_json={},
        created_by="test",
    )
    db_session.add(prompt)
    db_session.flush()

    assert prompt.temperature == 0.7
    assert prompt.max_tokens == 2048
    assert prompt.is_active is False  # Default is inactive
    assert prompt.created_at is not None


def test_agent_prompt_nullable_fields(db_session: Session):
    """Test nullable fields in AgentPrompt."""
    prompt = AgentPrompt(
        agent_dimension="test",
        version=1,
        system_prompt="Test",
        output_schema_json={},
        temperature=0.5,
        max_tokens=1000,
        is_active=False,
        created_by="test",
        notes=None,  # Explicitly NULL
    )
    db_session.add(prompt)
    db_session.commit()

    stored = db_session.query(AgentPrompt).filter(
        AgentPrompt.id == prompt.id
    ).first()

    assert stored.notes is None


def test_agent_prompt_json_field_storage(db_session: Session):
    """Test storing complex JSON in output_schema_json."""
    complex_schema = {
        "type": "object",
        "properties": {
            "field1": {"type": "string"},
            "field2": {"type": "number"},
            "nested": {
                "type": "object",
                "properties": {
                    "inner1": {"type": "array", "items": {"type": "string"}},
                    "inner2": {"type": "boolean"},
                },
            },
        },
        "required": ["field1"],
    }

    prompt = AgentPrompt(
        agent_dimension="test",
        version=1,
        system_prompt="Test",
        output_schema_json=complex_schema,
        temperature=0.7,
        max_tokens=2048,
        is_active=False,
        created_by="test",
    )
    db_session.add(prompt)
    db_session.commit()

    stored = db_session.query(AgentPrompt).filter(
        AgentPrompt.id == prompt.id
    ).first()

    assert stored.output_schema_json == complex_schema
    assert stored.output_schema_json["properties"]["nested"]["properties"]["inner2"]["type"] == "boolean"


# =============================================================================
# TESTS: LeadAnalysis Model
# =============================================================================


def test_lead_analysis_creation(db_session: Session, setup_lead: LeadPost):
    """Test creating a LeadAnalysis record."""
    analysis = LeadAnalysis(
        lead_id=setup_lead.id,
        account_id=setup_lead.author_account_id,
        status=AnalysisStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(analysis)
    db_session.commit()

    stored = db_session.query(LeadAnalysis).filter(
        LeadAnalysis.id == analysis.id
    ).first()

    assert stored is not None
    assert stored.lead_id == setup_lead.id
    assert stored.status == AnalysisStatus.RUNNING


def test_lead_analysis_relationship_to_lead(
    db_session: Session, setup_lead: LeadPost
):
    """Test LeadAnalysis relationship to LeadPost."""
    analysis = LeadAnalysis(
        lead_id=setup_lead.id,
        account_id=setup_lead.author_account_id,
        status=AnalysisStatus.PENDING,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(analysis)
    db_session.commit()

    # Verify relationship works
    stored_lead = db_session.query(LeadPost).filter(
        LeadPost.id == setup_lead.id
    ).first()
    # Should be able to access analysis through relationship if it exists


def test_lead_analysis_complete_results(
    db_session: Session, setup_lead: LeadPost
):
    """Test storing complete analysis results."""
    now = datetime.now(timezone.utc)

    analysis = LeadAnalysis(
        lead_id=setup_lead.id,
        account_id=setup_lead.author_account_id,
        status=AnalysisStatus.COMPLETED,
        started_at=now,
        completed_at=now,
        final_recommendation=RecommendationStatus.SUITABLE,
        recommendation_reasoning="Good fit based on criteria",
        confidence_score=0.85,
        demographics_json={"age": 25, "gender": "M"},
        preferences_json={"hobbies": ["hiking", "reading"]},
        relationship_goals_json={"intent": "serious"},
        risk_flags_json={"flags": []},
        sexual_preferences_json={"orientation": "straight"},
        meta_analysis_json={"score": 0.85},
        prompt_versions_json={"demographics": 1, "preferences": 1},
    )
    db_session.add(analysis)
    db_session.commit()

    stored = db_session.query(LeadAnalysis).filter(
        LeadAnalysis.id == analysis.id
    ).first()

    assert stored.status == AnalysisStatus.COMPLETED
    assert stored.final_recommendation == RecommendationStatus.SUITABLE
    assert stored.confidence_score == 0.85
    assert stored.demographics_json["age"] == 25


def test_lead_analysis_status_enum(db_session: Session, setup_lead: LeadPost):
    """Test all LeadAnalysis status values."""
    statuses = [
        AnalysisStatus.PENDING,
        AnalysisStatus.RUNNING,
        AnalysisStatus.COMPLETED,
        AnalysisStatus.FAILED,
    ]

    for status in statuses:
        analysis = LeadAnalysis(
            lead_id=setup_lead.id,
            account_id=setup_lead.author_account_id,
            status=status,
            started_at=datetime.now(timezone.utc),
        )
        db_session.add(analysis)

    db_session.commit()

    stored_analyses = db_session.query(LeadAnalysis).all()
    stored_statuses = {a.status for a in stored_analyses}

    assert len(stored_statuses) == 4


def test_lead_analysis_recommendation_enum(
    db_session: Session, setup_lead: LeadPost
):
    """Test all recommendation values."""
    recommendations = [
        RecommendationStatus.SUITABLE,
        RecommendationStatus.NOT_RECOMMENDED,
        RecommendationStatus.NEEDS_REVIEW,
    ]

    for rec in recommendations:
        analysis = LeadAnalysis(
            lead_id=setup_lead.id,
            account_id=setup_lead.author_account_id,
            status=AnalysisStatus.COMPLETED,
            started_at=datetime.now(timezone.utc),
            final_recommendation=rec,
            recommendation_reasoning="Test",
            confidence_score=0.8,
        )
        db_session.add(analysis)

    db_session.commit()

    stored_analyses = db_session.query(LeadAnalysis).all()
    stored_recs = {a.final_recommendation for a in stored_analyses}

    assert len(stored_recs) == 3


def test_lead_analysis_error_detail_field(
    db_session: Session, setup_lead: LeadPost
):
    """Test storing error details."""
    error_msg = "Inference service timeout after 120 seconds"

    analysis = LeadAnalysis(
        lead_id=setup_lead.id,
        account_id=setup_lead.author_account_id,
        status=AnalysisStatus.FAILED,
        started_at=datetime.now(timezone.utc),
        error_detail=error_msg,
    )
    db_session.add(analysis)
    db_session.commit()

    stored = db_session.query(LeadAnalysis).filter(
        LeadAnalysis.id == analysis.id
    ).first()

    assert stored.error_detail == error_msg


# =============================================================================
# TESTS: AnalysisDimension Model
# =============================================================================


def test_analysis_dimension_creation(
    db_session: Session, setup_lead: LeadPost
):
    """Test creating an AnalysisDimension record."""
    analysis = LeadAnalysis(
        lead_id=setup_lead.id,
        account_id=setup_lead.author_account_id,
        status=AnalysisStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(analysis)
    db_session.flush()

    dimension = AnalysisDimension(
        analysis_id=analysis.id,
        dimension="demographics",
        status=DimensionStatus.COMPLETED,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        output_json={"age": 25, "gender": "M"},
        prompt_version=1,
    )
    db_session.add(dimension)
    db_session.commit()

    stored = db_session.query(AnalysisDimension).filter(
        AnalysisDimension.id == dimension.id
    ).first()

    assert stored is not None
    assert stored.dimension == "demographics"
    assert stored.output_json["age"] == 25


def test_analysis_dimension_relationship_to_analysis(
    db_session: Session, setup_lead: LeadPost
):
    """Test AnalysisDimension relationship to LeadAnalysis."""
    analysis = LeadAnalysis(
        lead_id=setup_lead.id,
        account_id=setup_lead.author_account_id,
        status=AnalysisStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(analysis)
    db_session.flush()

    # Create multiple dimensions for one analysis
    for dim in ["demographics", "preferences", "relationship_goals"]:
        dimension = AnalysisDimension(
            analysis_id=analysis.id,
            dimension=dim,
            status=DimensionStatus.COMPLETED,
            started_at=datetime.now(timezone.utc),
            output_json={},
            prompt_version=1,
        )
        db_session.add(dimension)

    db_session.commit()

    stored_analysis = db_session.query(LeadAnalysis).filter(
        LeadAnalysis.id == analysis.id
    ).first()

    dimensions = db_session.query(AnalysisDimension).filter(
        AnalysisDimension.analysis_id == analysis.id
    ).all()

    assert len(dimensions) == 3


def test_analysis_dimension_status_enum(db_session: Session, setup_lead: LeadPost):
    """Test all dimension status values."""
    analysis = LeadAnalysis(
        lead_id=setup_lead.id,
        account_id=setup_lead.author_account_id,
        status=AnalysisStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(analysis)
    db_session.flush()

    statuses = [
        DimensionStatus.PENDING,
        DimensionStatus.RUNNING,
        DimensionStatus.COMPLETED,
        DimensionStatus.FAILED,
    ]

    for i, status in enumerate(statuses):
        dimension = AnalysisDimension(
            analysis_id=analysis.id,
            dimension=f"test_dim_{i}",
            status=status,
            started_at=datetime.now(timezone.utc),
            output_json={},
            prompt_version=1,
        )
        db_session.add(dimension)

    db_session.commit()

    dimensions = db_session.query(AnalysisDimension).filter(
        AnalysisDimension.analysis_id == analysis.id
    ).all()

    stored_statuses = {d.status for d in dimensions}
    assert len(stored_statuses) == 4


def test_analysis_dimension_cascade_delete(db_session: Session, setup_lead: LeadPost):
    """Test that AnalysisDimension records cascade delete with LeadAnalysis."""
    analysis = LeadAnalysis(
        lead_id=setup_lead.id,
        account_id=setup_lead.author_account_id,
        status=AnalysisStatus.COMPLETED,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(analysis)
    db_session.flush()

    # Create dimensions
    for dim in ["demographics", "preferences"]:
        dimension = AnalysisDimension(
            analysis_id=analysis.id,
            dimension=dim,
            status=DimensionStatus.COMPLETED,
            started_at=datetime.now(timezone.utc),
            output_json={},
            prompt_version=1,
        )
        db_session.add(dimension)

    db_session.commit()
    analysis_id = analysis.id

    # Delete analysis
    db_session.delete(analysis)
    db_session.commit()

    # Verify dimensions are cascade deleted
    remaining = db_session.query(AnalysisDimension).filter(
        AnalysisDimension.analysis_id == analysis_id
    ).all()

    assert len(remaining) == 0


# =============================================================================
# TESTS: LeadPost Relationship Updates
# =============================================================================


def test_lead_post_latest_analysis_relationship(
    db_session: Session, setup_lead: LeadPost
):
    """Test LeadPost latest_analysis relationship."""
    assert setup_lead.latest_analysis_id is None

    analysis = LeadAnalysis(
        lead_id=setup_lead.id,
        account_id=setup_lead.author_account_id,
        status=AnalysisStatus.COMPLETED,
        started_at=datetime.now(timezone.utc),
        final_recommendation=RecommendationStatus.SUITABLE,
        recommendation_reasoning="Test",
        confidence_score=0.8,
    )
    db_session.add(analysis)
    db_session.flush()

    # Update lead with latest analysis
    setup_lead.latest_analysis_id = analysis.id
    setup_lead.analysis_recommendation = RecommendationStatus.SUITABLE
    setup_lead.analysis_confidence = 0.8
    db_session.commit()

    stored_lead = db_session.query(LeadPost).filter(
        LeadPost.id == setup_lead.id
    ).first()

    assert stored_lead.latest_analysis_id == analysis.id
    assert stored_lead.analysis_recommendation == RecommendationStatus.SUITABLE
    assert stored_lead.analysis_confidence == 0.8


def test_lead_post_multiple_analyses(db_session: Session, setup_lead: LeadPost):
    """Test lead can have multiple analyses over time."""
    analyses = []

    for i in range(3):
        analysis = LeadAnalysis(
            lead_id=setup_lead.id,
            account_id=setup_lead.author_account_id,
            status=AnalysisStatus.COMPLETED,
            started_at=datetime.now(timezone.utc),
            final_recommendation=RecommendationStatus.SUITABLE,
            recommendation_reasoning=f"Analysis {i+1}",
            confidence_score=0.75 + (i * 0.05),
        )
        db_session.add(analysis)
        analyses.append(analysis)

    db_session.commit()

    # Verify all analyses are stored
    stored_analyses = db_session.query(LeadAnalysis).filter(
        LeadAnalysis.lead_id == setup_lead.id
    ).all()

    assert len(stored_analyses) == 3


# =============================================================================
# TESTS: Timestamp Fields
# =============================================================================


def test_model_timestamps_in_utc(db_session: Session, setup_lead: LeadPost):
    """Test that all timestamps are in UTC."""
    now = datetime.now(timezone.utc)

    analysis = LeadAnalysis(
        lead_id=setup_lead.id,
        account_id=setup_lead.author_account_id,
        status=AnalysisStatus.RUNNING,
        started_at=now,
    )
    db_session.add(analysis)
    db_session.flush()

    assert analysis.started_at.tzinfo == timezone.utc
    assert analysis.created_at.tzinfo == timezone.utc


def test_analysis_created_at_auto_set(db_session: Session, setup_lead: LeadPost):
    """Test that created_at is automatically set."""
    analysis = LeadAnalysis(
        lead_id=setup_lead.id,
        account_id=setup_lead.author_account_id,
        status=AnalysisStatus.PENDING,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(analysis)
    db_session.flush()

    assert analysis.created_at is not None


def test_analysis_updated_at_auto_set(db_session: Session, setup_lead: LeadPost):
    """Test that updated_at is automatically managed."""
    analysis = LeadAnalysis(
        lead_id=setup_lead.id,
        account_id=setup_lead.author_account_id,
        status=AnalysisStatus.PENDING,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(analysis)
    db_session.flush()

    original_updated_at = analysis.updated_at

    # Modify and check updated_at changes
    analysis.status = AnalysisStatus.RUNNING
    db_session.flush()

    # Note: Updated at behavior depends on database configuration
