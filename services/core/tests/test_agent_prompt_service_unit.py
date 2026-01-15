"""Unit tests for AgentPromptService.

Tests the prompt management layer including:
- Retrieving active prompts by dimension
- Creating new prompt versions
- Updating prompts (creates new version, sets as active)
- Listing version history
- Rolling back to previous versions
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from rediska_core.domain.models import AgentPrompt
from rediska_core.domain.services.agent_prompt import AgentPromptService


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def setup_prompts(db_session: Session):
    """Set up initial agent prompts for testing."""
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
            system_prompt=f"You are analyzing {dimension}.",
            output_schema_json={
                "type": "object",
                "properties": {"dimension": {"type": "string"}},
            },
            temperature=0.7,
            max_tokens=2048,
            is_active=True,
            created_by="system",
            notes="Initial seed prompt",
        )
        db_session.add(prompt)
        prompts[dimension] = prompt

    db_session.flush()
    return prompts


@pytest.fixture
def agent_prompt_service(db_session: Session) -> AgentPromptService:
    """Create an AgentPromptService instance for testing."""
    return AgentPromptService(db_session)


# =============================================================================
# TESTS: get_active_prompt
# =============================================================================


def test_get_active_prompt_success(
    agent_prompt_service: AgentPromptService, setup_prompts: dict
):
    """Test retrieving active prompt for a dimension."""
    prompt = agent_prompt_service.get_active_prompt("demographics")

    assert prompt is not None
    assert prompt.agent_dimension == "demographics"
    assert prompt.version == 1
    assert prompt.is_active is True
    assert prompt.system_prompt == "You are analyzing demographics."


def test_get_active_prompt_not_found(
    agent_prompt_service: AgentPromptService,
):
    """Test retrieving non-existent prompt returns None."""
    prompt = agent_prompt_service.get_active_prompt("nonexistent")
    assert prompt is None


def test_get_active_prompt_ignores_inactive(
    db_session: Session, agent_prompt_service: AgentPromptService, setup_prompts: dict
):
    """Test that inactive prompts are not returned."""
    # Mark all demographics prompts as inactive
    db_session.query(AgentPrompt).filter(
        AgentPrompt.agent_dimension == "demographics"
    ).update({"is_active": False})
    db_session.flush()

    prompt = agent_prompt_service.get_active_prompt("demographics")
    assert prompt is None


# =============================================================================
# TESTS: get_all_active_prompts
# =============================================================================


def test_get_all_active_prompts_success(
    agent_prompt_service: AgentPromptService, setup_prompts: dict
):
    """Test retrieving all active prompts."""
    prompts = agent_prompt_service.get_all_active_prompts()

    assert len(prompts) == 6
    dimensions = {p.agent_dimension for p in prompts}
    assert dimensions == {
        "demographics",
        "preferences",
        "relationship_goals",
        "risk_flags",
        "sexual_preferences",
        "meta_analysis",
    }


def test_get_all_active_prompts_excludes_inactive(
    db_session: Session, agent_prompt_service: AgentPromptService, setup_prompts: dict
):
    """Test that inactive prompts are excluded."""
    # Mark one prompt as inactive
    db_session.query(AgentPrompt).filter(
        AgentPrompt.agent_dimension == "demographics"
    ).update({"is_active": False})
    db_session.flush()

    prompts = agent_prompt_service.get_all_active_prompts()

    assert len(prompts) == 5
    dimensions = {p.agent_dimension for p in prompts}
    assert "demographics" not in dimensions


# =============================================================================
# TESTS: create_prompt
# =============================================================================


def test_create_prompt_success(
    db_session: Session, agent_prompt_service: AgentPromptService
):
    """Test creating a new prompt."""
    new_prompt = agent_prompt_service.create_prompt(
        dimension="demographics",
        system_prompt="New demographics prompt v2",
        output_schema_json={"type": "object"},
        temperature=0.5,
        max_tokens=1024,
        created_by="test_user",
        notes="Test version",
    )

    assert new_prompt is not None
    assert new_prompt.agent_dimension == "demographics"
    assert new_prompt.system_prompt == "New demographics prompt v2"
    assert new_prompt.temperature == 0.5
    assert new_prompt.max_tokens == 1024
    assert new_prompt.created_by == "test_user"
    assert new_prompt.notes == "Test version"
    assert new_prompt.is_active is False  # New prompts are not active by default


# =============================================================================
# TESTS: update_prompt
# =============================================================================


def test_update_prompt_creates_new_version(
    db_session: Session,
    agent_prompt_service: AgentPromptService,
    setup_prompts: dict,
):
    """Test updating a prompt creates new version and sets as active."""
    old_prompt = agent_prompt_service.get_active_prompt("demographics")
    assert old_prompt.version == 1

    new_prompt = agent_prompt_service.update_prompt(
        dimension="demographics",
        system_prompt="Updated demographics prompt",
        output_schema_json={"type": "object", "updated": True},
        temperature=0.6,
        max_tokens=1500,
        created_by="test_user",
        notes="Version 2 update",
    )

    assert new_prompt.version == 2
    assert new_prompt.is_active is True
    assert new_prompt.system_prompt == "Updated demographics prompt"

    # Verify old prompt is no longer active
    db_session.refresh(old_prompt)
    assert old_prompt.is_active is False


def test_update_prompt_first_creation(
    db_session: Session, agent_prompt_service: AgentPromptService
):
    """Test updating a dimension with no existing prompts creates v1."""
    new_prompt = agent_prompt_service.update_prompt(
        dimension="new_dimension",
        system_prompt="First prompt for new dimension",
        output_schema_json={"type": "object"},
        temperature=0.7,
        max_tokens=2048,
        created_by="test_user",
    )

    assert new_prompt.version == 1
    assert new_prompt.is_active is True


# =============================================================================
# TESTS: list_prompt_versions
# =============================================================================


def test_list_prompt_versions_empty(agent_prompt_service: AgentPromptService):
    """Test listing versions for non-existent dimension."""
    versions = agent_prompt_service.list_prompt_versions("nonexistent")
    assert versions == []


def test_list_prompt_versions_single(
    agent_prompt_service: AgentPromptService, setup_prompts: dict
):
    """Test listing single version."""
    versions = agent_prompt_service.list_prompt_versions("demographics")

    assert len(versions) == 1
    assert versions[0].version == 1
    assert versions[0].is_active is True


def test_list_prompt_versions_multiple(
    db_session: Session, agent_prompt_service: AgentPromptService, setup_prompts: dict
):
    """Test listing multiple versions."""
    # Create multiple versions
    agent_prompt_service.update_prompt(
        "demographics",
        "Version 2",
        {"type": "object"},
        created_by="user1",
    )
    agent_prompt_service.update_prompt(
        "demographics",
        "Version 3",
        {"type": "object"},
        created_by="user2",
    )

    versions = agent_prompt_service.list_prompt_versions("demographics")

    assert len(versions) == 3
    assert versions[0].version == 1
    assert versions[1].version == 2
    assert versions[2].version == 3
    assert versions[2].is_active is True
    assert versions[1].is_active is False
    assert versions[0].is_active is False


# =============================================================================
# TESTS: rollback_to_version
# =============================================================================


def test_rollback_to_version_success(
    db_session: Session,
    agent_prompt_service: AgentPromptService,
    setup_prompts: dict,
):
    """Test rolling back to a previous version."""
    # Create v2 and v3
    agent_prompt_service.update_prompt(
        "demographics",
        "Version 2",
        {"type": "object"},
        created_by="user1",
    )
    agent_prompt_service.update_prompt(
        "demographics",
        "Version 3",
        {"type": "object"},
        created_by="user2",
    )

    # Verify v3 is active
    current = agent_prompt_service.get_active_prompt("demographics")
    assert current.version == 3

    # Rollback to v1
    rolled_back = agent_prompt_service.rollback_to_version("demographics", 1)

    assert rolled_back.version == 1
    assert rolled_back.is_active is True
    assert rolled_back.system_prompt == "You are analyzing demographics."

    # Verify v3 is no longer active
    v3 = db_session.query(AgentPrompt).filter(
        AgentPrompt.agent_dimension == "demographics", AgentPrompt.version == 3
    ).first()
    assert v3.is_active is False


def test_rollback_to_version_not_found(
    agent_prompt_service: AgentPromptService, setup_prompts: dict
):
    """Test rolling back to non-existent version."""
    result = agent_prompt_service.rollback_to_version("demographics", 999)
    assert result is None


def test_rollback_to_version_nonexistent_dimension(
    agent_prompt_service: AgentPromptService,
):
    """Test rolling back for non-existent dimension."""
    result = agent_prompt_service.rollback_to_version("nonexistent", 1)
    assert result is None


# =============================================================================
# TESTS: get_prompt_by_version
# =============================================================================


def test_get_prompt_by_version_success(
    agent_prompt_service: AgentPromptService, setup_prompts: dict
):
    """Test retrieving specific prompt version."""
    prompt = agent_prompt_service.get_prompt_by_version("demographics", 1)

    assert prompt is not None
    assert prompt.version == 1
    assert prompt.agent_dimension == "demographics"


def test_get_prompt_by_version_not_found(
    agent_prompt_service: AgentPromptService,
):
    """Test retrieving non-existent version."""
    prompt = agent_prompt_service.get_prompt_by_version("demographics", 999)
    assert prompt is None


# =============================================================================
# TESTS: deactivate_all_prompts
# =============================================================================


def test_deactivate_all_prompts_success(
    db_session: Session,
    agent_prompt_service: AgentPromptService,
    setup_prompts: dict,
):
    """Test deactivating all prompts for a dimension."""
    agent_prompt_service.deactivate_all_prompts("demographics")

    # Verify all are inactive
    all_prompts = db_session.query(AgentPrompt).filter(
        AgentPrompt.agent_dimension == "demographics"
    ).all()

    for prompt in all_prompts:
        assert prompt.is_active is False


def test_deactivate_all_prompts_other_dimensions_unaffected(
    db_session: Session,
    agent_prompt_service: AgentPromptService,
    setup_prompts: dict,
):
    """Test deactivating prompts only affects specified dimension."""
    agent_prompt_service.deactivate_all_prompts("demographics")

    # Verify other dimensions are still active
    preferences_prompt = agent_prompt_service.get_active_prompt("preferences")
    assert preferences_prompt is not None
    assert preferences_prompt.is_active is True


# =============================================================================
# TESTS: Edge Cases and Boundary Conditions
# =============================================================================


def test_concurrent_updates_version_increment(
    db_session: Session,
    agent_prompt_service: AgentPromptService,
    setup_prompts: dict,
):
    """Test that versions increment correctly with concurrent updates."""
    for i in range(2, 6):
        prompt = agent_prompt_service.update_prompt(
            "demographics",
            f"Version {i}",
            {"type": "object"},
            created_by=f"user{i}",
        )
        assert prompt.version == i


def test_prompt_with_large_schema(
    agent_prompt_service: AgentPromptService,
):
    """Test creating prompt with complex JSON schema."""
    large_schema = {
        "type": "object",
        "properties": {
            "field1": {"type": "string"},
            "field2": {"type": "number"},
            "field3": {
                "type": "array",
                "items": {"type": "string"},
            },
            "field4": {
                "type": "object",
                "properties": {
                    "nested1": {"type": "string"},
                    "nested2": {"type": "array"},
                },
            },
        },
    }

    prompt = agent_prompt_service.create_prompt(
        dimension="complex_dimension",
        system_prompt="Test prompt",
        output_schema_json=large_schema,
        created_by="test",
    )

    assert prompt.output_schema_json == large_schema


def test_prompt_with_special_characters(
    agent_prompt_service: AgentPromptService,
):
    """Test creating prompt with special characters in text."""
    special_prompt = """
    Analyze the following with these special chars:
    @#$%^&*()_+-=[]{}|;':",./<>?
    Include unicode: 你好 مرحبا 🎉
    """

    prompt = agent_prompt_service.create_prompt(
        dimension="special_chars",
        system_prompt=special_prompt,
        output_schema_json={"type": "object"},
        created_by="test",
    )

    assert prompt.system_prompt == special_prompt
