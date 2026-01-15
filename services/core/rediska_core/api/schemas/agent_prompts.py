"""Schemas for agent prompt management API endpoints."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentPromptResponse(BaseModel):
    """Agent prompt response model."""

    id: int
    agent_dimension: str
    version: int
    system_prompt: str
    output_schema_json: dict[str, Any]
    temperature: float
    max_tokens: int
    is_active: bool
    created_at: str
    created_by: str
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class UpdateAgentPromptRequest(BaseModel):
    """Request to update an agent prompt."""

    system_prompt: str = Field(
        ...,
        description="New system prompt for the agent",
    )
    output_schema_json: Optional[dict[str, Any]] = Field(
        None,
        description="New output schema (optional, uses current if not provided)",
    )
    temperature: Optional[float] = Field(
        None,
        ge=0.0,
        le=2.0,
        description="New temperature (optional)",
    )
    max_tokens: Optional[int] = Field(
        None,
        ge=1,
        le=32000,
        description="New max tokens (optional)",
    )
    notes: Optional[str] = Field(
        None,
        description="Notes about changes",
    )


class RollbackPromptRequest(BaseModel):
    """Request to rollback to a previous prompt version."""

    version: int = Field(
        ...,
        description="Version number to rollback to",
    )


class ListAgentPromptsResponse(BaseModel):
    """List all agent prompts with their active versions."""

    prompts: dict[str, AgentPromptResponse] = Field(
        ...,
        description="Map of dimension name to active prompt",
    )

    class Config:
        from_attributes = True


class PromptVersionHistoryResponse(BaseModel):
    """History of prompt versions for a dimension."""

    dimension: str
    versions: list[AgentPromptResponse]

    class Config:
        from_attributes = True
