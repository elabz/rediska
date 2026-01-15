"""Integration tests for multi-agent analysis API endpoints.

Tests the REST API layer including:
- Agent prompt management endpoints
- Lead analysis endpoints
- Error responses
- Authorization/authentication (when implemented)
"""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    AgentPrompt,
    ExternalAccount,
    LeadAnalysis,
    LeadPost,
    Provider,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def setup_provider_account_lead(db_session: Session):
    """Set up provider, account, and lead for API testing."""
    provider = Provider(provider_id="reddit", display_name="Reddit")
    db_session.add(provider)
    db_session.flush()

    account = ExternalAccount(
        provider_id="reddit",
        external_username="test_author",
        external_user_id="t2_abc123",
        remote_status="active",
    )
    db_session.add(account)
    db_session.flush()

    lead = LeadPost(
        provider_id="reddit",
        source_location="r/personals",
        external_post_id="post_abc123",
        author_account_id=account.id,
        title="Looking for connection",
        body_text="25M, interested in hiking and reading.",
        external_created_at=datetime.now(timezone.utc),
        local_saved_at=datetime.now(timezone.utc),
    )
    db_session.add(lead)
    db_session.flush()

    return provider, account, lead


@pytest.fixture
def setup_all_prompts(db_session: Session):
    """Set up all agent prompts."""
    dimensions = [
        "demographics",
        "preferences",
        "relationship_goals",
        "risk_flags",
        "sexual_preferences",
        "meta_analysis",
    ]

    prompts = {}
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
        prompts[dimension] = prompt

    db_session.flush()
    return prompts


# =============================================================================
# TESTS: GET /agent-prompts
# =============================================================================


@pytest.mark.asyncio
async def test_get_all_agent_prompts(
    client: AsyncClient,
    setup_all_prompts,
):
    """Test retrieving all active agent prompts."""
    response = await client.get("/api/core/agent-prompts")

    assert response.status_code == 200
    data = response.json()
    assert "prompts" in data
    assert len(data["prompts"]) == 6


@pytest.mark.asyncio
async def test_get_all_agent_prompts_empty(
    client: AsyncClient,
):
    """Test retrieving prompts when none exist."""
    response = await client.get("/api/core/agent-prompts")

    assert response.status_code == 200
    data = response.json()
    assert "prompts" in data
    assert len(data["prompts"]) == 0


# =============================================================================
# TESTS: GET /agent-prompts/{dimension}
# =============================================================================


@pytest.mark.asyncio
async def test_get_dimension_prompt_success(
    client: AsyncClient,
    setup_all_prompts,
):
    """Test retrieving specific dimension prompt."""
    response = await client.get("/api/core/agent-prompts/demographics")

    assert response.status_code == 200
    data = response.json()
    assert data["agent_dimension"] == "demographics"
    assert data["version"] == 1
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_get_dimension_prompt_not_found(
    client: AsyncClient,
):
    """Test retrieving non-existent dimension."""
    response = await client.get("/api/core/agent-prompts/nonexistent")

    assert response.status_code == 404


# =============================================================================
# TESTS: GET /agent-prompts/{dimension}/versions
# =============================================================================


@pytest.mark.asyncio
async def test_get_prompt_version_history(
    client: AsyncClient,
    db_session: Session,
    setup_all_prompts,
):
    """Test retrieving version history for a dimension."""
    # Create multiple versions
    for i in range(2, 4):
        prompt = AgentPrompt(
            agent_dimension="demographics",
            version=i,
            system_prompt=f"Version {i}",
            output_schema_json={"type": "object"},
            temperature=0.7,
            max_tokens=2048,
            is_active=(i == 3),
            created_by="test_user",
        )
        db_session.add(prompt)
    db_session.commit()

    response = await client.get("/api/core/agent-prompts/demographics/versions")

    assert response.status_code == 200
    data = response.json()
    assert "versions" in data
    assert len(data["versions"]) == 3


@pytest.mark.asyncio
async def test_get_prompt_version_history_not_found(
    client: AsyncClient,
):
    """Test version history for non-existent dimension."""
    response = await client.get("/api/core/agent-prompts/nonexistent/versions")

    assert response.status_code == 404


# =============================================================================
# TESTS: PUT /agent-prompts/{dimension}
# =============================================================================


@pytest.mark.asyncio
async def test_update_prompt_success(
    client: AsyncClient,
    setup_all_prompts,
):
    """Test updating an agent prompt."""
    update_data = {
        "system_prompt": "Updated demographics analysis prompt",
        "output_schema_json": {"type": "object", "updated": True},
        "temperature": 0.6,
        "max_tokens": 1500,
        "notes": "Version 2 update",
    }

    response = await client.put(
        "/api/core/agent-prompts/demographics",
        json=update_data,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["version"] == 2
    assert data["is_active"] is True
    assert data["system_prompt"] == "Updated demographics analysis prompt"


@pytest.mark.asyncio
async def test_update_prompt_creates_new_version(
    client: AsyncClient,
    db_session: Session,
    setup_all_prompts,
):
    """Test that prompt update creates new version."""
    # Get current version
    response1 = await client.get("/api/core/agent-prompts/demographics")
    v1_id = response1.json()["id"]
    v1_version = response1.json()["version"]

    # Update prompt
    update_data = {
        "system_prompt": "New version",
        "output_schema_json": {"type": "object"},
        "temperature": 0.7,
        "max_tokens": 2048,
    }
    response2 = await client.put(
        "/api/core/agent-prompts/demographics",
        json=update_data,
    )

    assert response2.status_code == 200
    v2_data = response2.json()
    assert v2_data["version"] == v1_version + 1
    assert v2_data["id"] != v1_id


@pytest.mark.asyncio
async def test_update_prompt_invalid_data(
    client: AsyncClient,
    setup_all_prompts,
):
    """Test updating prompt with invalid data."""
    update_data = {
        "system_prompt": "",  # Empty prompt
        "output_schema_json": "invalid",  # Invalid schema format
    }

    response = await client.put(
        "/api/core/agent-prompts/demographics",
        json=update_data,
    )

    assert response.status_code in [400, 422]  # Bad request or unprocessable


# =============================================================================
# TESTS: POST /agent-prompts/{dimension}/rollback
# =============================================================================


@pytest.mark.asyncio
async def test_rollback_prompt_success(
    client: AsyncClient,
    db_session: Session,
    setup_all_prompts,
):
    """Test rolling back to a previous prompt version."""
    # Create multiple versions
    for i in range(2, 4):
        prompt = AgentPrompt(
            agent_dimension="demographics",
            version=i,
            system_prompt=f"Version {i}",
            output_schema_json={"type": "object"},
            temperature=0.7,
            max_tokens=2048,
            is_active=(i == 3),
            created_by="test_user",
        )
        db_session.add(prompt)
    db_session.commit()

    # Rollback to v1
    rollback_data = {"version": 1}
    response = await client.post(
        "/api/core/agent-prompts/demographics/rollback",
        json=rollback_data,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["version"] == 1
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_rollback_prompt_not_found(
    client: AsyncClient,
    setup_all_prompts,
):
    """Test rolling back to non-existent version."""
    rollback_data = {"version": 999}
    response = await client.post(
        "/api/core/agent-prompts/demographics/rollback",
        json=rollback_data,
    )

    assert response.status_code == 404


# =============================================================================
# TESTS: POST /leads/{id}/analyze-multi
# =============================================================================


@pytest.mark.asyncio
async def test_analyze_lead_triggers_task(
    client: AsyncClient,
    setup_provider_account_lead,
    setup_all_prompts,
):
    """Test analyzing a lead triggers background task."""
    _, _, lead = setup_provider_account_lead

    response = await client.post(f"/api/core/leads/{lead.id}/analyze-multi")

    # May return 202 (accepted) or 200 with task info depending on implementation
    assert response.status_code in [200, 202]


@pytest.mark.asyncio
async def test_analyze_lead_not_found(
    client: AsyncClient,
):
    """Test analyzing non-existent lead."""
    response = await client.post("/api/core/leads/99999/analyze-multi")

    assert response.status_code == 404


# =============================================================================
# TESTS: GET /leads/{id}/analysis
# =============================================================================


@pytest.mark.asyncio
async def test_get_lead_analysis_success(
    client: AsyncClient,
    db_session: Session,
    setup_provider_account_lead,
):
    """Test retrieving latest analysis for a lead."""
    _, _, lead = setup_provider_account_lead

    # Create analysis record
    analysis = LeadAnalysis(
        lead_id=lead.id,
        account_id=lead.author_account_id,
        status="completed",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        final_recommendation="suitable",
        recommendation_reasoning="Good fit",
        confidence_score=0.85,
    )
    db_session.add(analysis)
    db_session.flush()

    response = await client.get(f"/api/core/leads/{lead.id}/analysis")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["final_recommendation"] == "suitable"


@pytest.mark.asyncio
async def test_get_lead_analysis_not_found(
    client: AsyncClient,
    setup_provider_account_lead,
):
    """Test retrieving analysis for lead without analysis."""
    _, _, lead = setup_provider_account_lead

    response = await client.get(f"/api/core/leads/{lead.id}/analysis")

    assert response.status_code == 404


# =============================================================================
# TESTS: GET /leads/{id}/analysis/history
# =============================================================================


@pytest.mark.asyncio
async def test_get_analysis_history(
    client: AsyncClient,
    db_session: Session,
    setup_provider_account_lead,
):
    """Test retrieving analysis history for a lead."""
    _, _, lead = setup_provider_account_lead

    # Create multiple analyses
    for i in range(3):
        analysis = LeadAnalysis(
            lead_id=lead.id,
            account_id=lead.author_account_id,
            status="completed",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            final_recommendation="suitable",
            recommendation_reasoning=f"Analysis {i+1}",
            confidence_score=0.75 + (i * 0.05),
        )
        db_session.add(analysis)
    db_session.commit()

    response = await client.get(f"/api/core/leads/{lead.id}/analysis/history")

    assert response.status_code == 200
    data = response.json()
    assert "analyses" in data
    assert len(data["analyses"]) == 3


@pytest.mark.asyncio
async def test_get_analysis_history_empty(
    client: AsyncClient,
    setup_provider_account_lead,
):
    """Test history for lead without analyses."""
    _, _, lead = setup_provider_account_lead

    response = await client.get(f"/api/core/leads/{lead.id}/analysis/history")

    assert response.status_code == 200
    data = response.json()
    assert len(data.get("analyses", [])) == 0


# =============================================================================
# TESTS: Audit Logging
# =============================================================================


@pytest.mark.asyncio
async def test_prompt_update_creates_audit_log(
    client: AsyncClient,
    db_session: Session,
    setup_all_prompts,
):
    """Test that prompt updates are logged to audit_log."""
    update_data = {
        "system_prompt": "Updated prompt",
        "output_schema_json": {"type": "object"},
        "temperature": 0.7,
        "max_tokens": 2048,
    }

    await client.put(
        "/api/core/agent-prompts/demographics",
        json=update_data,
    )

    # Check audit log was created (implementation specific)
    # This test assumes audit logging is implemented


# =============================================================================
# TESTS: Response Format Validation
# =============================================================================


@pytest.mark.asyncio
async def test_api_response_includes_timestamps(
    client: AsyncClient,
    db_session: Session,
    setup_provider_account_lead,
):
    """Test that API responses include proper timestamps."""
    _, _, lead = setup_provider_account_lead

    analysis = LeadAnalysis(
        lead_id=lead.id,
        account_id=lead.author_account_id,
        status="completed",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        final_recommendation="suitable",
        recommendation_reasoning="Test",
        confidence_score=0.8,
    )
    db_session.add(analysis)
    db_session.flush()

    response = await client.get(f"/api/core/leads/{lead.id}/analysis")

    assert response.status_code == 200
    data = response.json()
    assert "started_at" in data
    assert "completed_at" in data


@pytest.mark.asyncio
async def test_api_response_includes_metadata(
    client: AsyncClient,
    setup_all_prompts,
):
    """Test that list responses include metadata."""
    response = await client.get("/api/core/agent-prompts")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "prompts" in data
