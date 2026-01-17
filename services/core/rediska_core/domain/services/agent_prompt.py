"""Service for managing agent prompts and versions."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from rediska_core.domain.models import AgentPrompt


class AgentPromptService:
    """Manages agent prompt storage, retrieval, and versioning."""

    def __init__(self, db: Session) -> None:
        """Initialize service with database session."""
        self.db = db

    def get_active_prompt(self, dimension: str) -> AgentPrompt:
        """
        Get the currently active prompt for a dimension.

        Args:
            dimension: Agent dimension name (e.g., 'demographics', 'preferences')

        Returns:
            AgentPrompt: Active prompt for the dimension

        Raises:
            ValueError: If no active prompt exists for dimension
        """
        stmt = select(AgentPrompt).where(
            AgentPrompt.agent_dimension == dimension,
            AgentPrompt.is_active == True,
        )
        prompt = self.db.scalar(stmt)

        if not prompt:
            raise ValueError(f"No active prompt found for dimension: {dimension}")

        return prompt

    def get_all_active_prompts(self) -> dict[str, AgentPrompt]:
        """
        Get all active prompts for all dimensions.

        Returns:
            dict: Map of dimension name to AgentPrompt
        """
        stmt = select(AgentPrompt).where(AgentPrompt.is_active == True)
        prompts = self.db.scalars(stmt).all()

        return {prompt.agent_dimension: prompt for prompt in prompts}

    def create_prompt(
        self,
        dimension: str,
        system_prompt: str,
        output_schema_json: dict[str, Any],
        temperature: float = 0.7,
        max_tokens: int = 8192,
        notes: str | None = None,
        created_by: str = "system",
    ) -> AgentPrompt:
        """
        Create a new prompt version.

        Args:
            dimension: Agent dimension name
            system_prompt: LLM system prompt text
            output_schema_json: JSON schema for output validation
            temperature: LLM temperature (0.0-2.0)
            max_tokens: Maximum tokens for LLM response
            notes: Human-readable notes about this version
            created_by: Who created this prompt

        Returns:
            AgentPrompt: Newly created prompt
        """
        # Get next version number
        stmt = select(AgentPrompt).where(
            AgentPrompt.agent_dimension == dimension
        ).order_by(AgentPrompt.version.desc()).limit(1)
        last_prompt = self.db.scalar(stmt)
        next_version = (last_prompt.version + 1) if last_prompt else 1

        # Create new prompt
        prompt = AgentPrompt(
            agent_dimension=dimension,
            version=next_version,
            system_prompt=system_prompt,
            output_schema_json=output_schema_json,
            temperature=temperature,
            max_tokens=max_tokens,
            is_active=False,  # New prompts start inactive
            created_by=created_by,
            notes=notes,
        )

        self.db.add(prompt)
        self.db.flush()

        return prompt

    def update_prompt(
        self,
        dimension: str,
        system_prompt: str,
        output_schema_json: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        notes: str | None = None,
        created_by: str = "user",
    ) -> AgentPrompt:
        """
        Update a prompt by creating a new version and marking it as active.

        Args:
            dimension: Agent dimension name
            system_prompt: New LLM system prompt text
            output_schema_json: New JSON schema (optional, uses current if None)
            temperature: New temperature (optional, uses current if None)
            max_tokens: New max tokens (optional, uses current if None)
            notes: Notes about changes
            created_by: Who made this update

        Returns:
            AgentPrompt: New active prompt version
        """
        # Get current active prompt to inherit unspecified values
        current = self.get_active_prompt(dimension)

        # Create new version with updated values
        new_prompt = self.create_prompt(
            dimension=dimension,
            system_prompt=system_prompt,
            output_schema_json=output_schema_json or current.output_schema_json,
            temperature=temperature if temperature is not None else current.temperature,
            max_tokens=max_tokens if max_tokens is not None else current.max_tokens,
            notes=notes,
            created_by=created_by,
        )

        # Deactivate old prompt
        current.is_active = False

        # Activate new prompt
        new_prompt.is_active = True

        self.db.flush()

        return new_prompt

    def list_prompt_versions(self, dimension: str) -> list[AgentPrompt]:
        """
        List all versions of a prompt for a dimension.

        Args:
            dimension: Agent dimension name

        Returns:
            list: All prompts for dimension, ordered by version descending
        """
        stmt = (
            select(AgentPrompt)
            .where(AgentPrompt.agent_dimension == dimension)
            .order_by(AgentPrompt.version.desc())
        )
        return list(self.db.scalars(stmt).all())

    def rollback_to_version(self, dimension: str, version: int) -> AgentPrompt:
        """
        Rollback to a previous prompt version by creating it as the new active version.

        Args:
            dimension: Agent dimension name
            version: Version number to rollback to

        Returns:
            AgentPrompt: The new active prompt (based on rollback version)

        Raises:
            ValueError: If specified version doesn't exist
        """
        # Get the version to rollback to
        stmt = select(AgentPrompt).where(
            AgentPrompt.agent_dimension == dimension,
            AgentPrompt.version == version,
        )
        rollback_prompt = self.db.scalar(stmt)

        if not rollback_prompt:
            raise ValueError(
                f"Version {version} not found for dimension {dimension}"
            )

        # Create new version based on rollback prompt
        new_prompt = self.create_prompt(
            dimension=dimension,
            system_prompt=rollback_prompt.system_prompt,
            output_schema_json=rollback_prompt.output_schema_json,
            temperature=rollback_prompt.temperature,
            max_tokens=rollback_prompt.max_tokens,
            notes=f"Rolled back from version {version}",
            created_by="system",
        )

        # Deactivate current active prompt
        current = self.get_active_prompt(dimension)
        current.is_active = False

        # Activate new prompt
        new_prompt.is_active = True

        self.db.flush()

        return new_prompt

    def get_prompt_by_version(self, dimension: str, version: int) -> AgentPrompt:
        """
        Get a specific version of a prompt.

        Args:
            dimension: Agent dimension name
            version: Version number

        Returns:
            AgentPrompt: The specified prompt version

        Raises:
            ValueError: If version doesn't exist
        """
        stmt = select(AgentPrompt).where(
            AgentPrompt.agent_dimension == dimension,
            AgentPrompt.version == version,
        )
        prompt = self.db.scalar(stmt)

        if not prompt:
            raise ValueError(
                f"Version {version} not found for dimension {dimension}"
            )

        return prompt

    def deactivate_all_prompts(self, dimension: str) -> int:
        """
        Deactivate all prompts for a dimension.

        Args:
            dimension: Agent dimension name

        Returns:
            int: Number of prompts deactivated
        """
        stmt = select(AgentPrompt).where(
            AgentPrompt.agent_dimension == dimension
        )
        prompts = self.db.scalars(stmt).all()

        count = 0
        for prompt in prompts:
            if prompt.is_active:
                prompt.is_active = False
                count += 1

        self.db.flush()
        return count
