"""Profile summary agent for analyzing user profiles.

Generates structured summaries including:
1. Summary text - Brief description of the user
2. Signals - Extracted structured data (interests, activity patterns, etc.)
3. Risk flags - Any red flags or concerns
4. Citations - References to source content

Usage:
    agent = ProfileSummaryAgent(inference_client=client)

    input_data = ProfileSummaryInput(
        account_metadata={"username": "user123", "karma": 5000},
        profile_items=[...],
    )

    result = await agent.analyze(input_data)

    if result.success:
        print(result.output.summary)
        print(result.output.signals)
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Union

from pydantic import BaseModel, Field, ValidationError

from rediska_core.domain.services.agent import AgentConfig, AgentHarness, VoiceConfig
from rediska_core.domain.services.inference import ChatMessage, InferenceClient, ModelInfo


# =============================================================================
# OUTPUT SCHEMAS
# =============================================================================


class Signal(BaseModel):
    """A structured signal extracted from the profile.

    Represents a data point about the user (interests, role, experience, etc.).
    """

    name: str = Field(..., description="Signal name (e.g., 'interests', 'role', 'industry')")
    value: Any = Field(..., description="Signal value (string, list, number, etc.)")
    confidence: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Confidence score 0-1"
    )


class RiskFlag(BaseModel):
    """A potential risk or concern identified in the profile.

    Used to flag suspicious patterns, spam behavior, etc.
    """

    type: str = Field(..., description="Type of risk (e.g., 'spam_behavior', 'fake_account')")
    severity: str = Field(
        default="medium", description="Severity level: low, medium, high"
    )
    description: str = Field(..., description="Description of the risk")
    evidence_item_ids: list[int] = Field(
        default_factory=list, description="IDs of items that evidence this risk"
    )


class Citation(BaseModel):
    """A citation/reference to source content.

    Provides evidence for claims made in the summary.
    """

    item_id: int = Field(..., description="ID of the profile item being cited")
    quote: str = Field(..., description="Relevant quote from the item")
    relevance: str = Field(..., description="Why this quote is relevant")


class ProfileSummaryOutput(BaseModel):
    """Structured output from the profile summary agent."""

    summary: str = Field(..., description="Brief summary of the profile (2-3 sentences)")
    signals: list[Signal] = Field(
        default_factory=list, description="Extracted signals about the user"
    )
    risk_flags: list[RiskFlag] = Field(
        default_factory=list, description="Identified risk flags"
    )
    citations: list[Citation] = Field(
        default_factory=list, description="Citations to source content"
    )

    def to_storage_format(self) -> dict:
        """Convert to format suitable for profile_snapshots storage.

        Returns:
            Dictionary with summary_text, signals_json, risk_flags_json
        """
        return {
            "summary_text": self.summary,
            "signals_json": [s.model_dump() for s in self.signals],
            "risk_flags_json": [r.model_dump() for r in self.risk_flags],
            "citations_json": [c.model_dump() for c in self.citations],
        }


# =============================================================================
# INPUT DATA
# =============================================================================


@dataclass
class ProfileSummaryInput:
    """Input data for the profile summary agent.

    Combines account metadata and profile items into a prompt.
    """

    account_metadata: dict = field(default_factory=dict)
    profile_items: list[dict] = field(default_factory=list)
    max_content_length: int = 8000  # Max chars for content in prompt

    def to_prompt(self) -> str:
        """Generate a prompt from the input data.

        Returns:
            Formatted prompt string for the agent
        """
        parts = []

        # Account metadata section
        parts.append("## Account Information")
        for key, value in self.account_metadata.items():
            parts.append(f"- {key}: {value}")
        parts.append("")

        # Profile items section
        parts.append("## Profile Content")

        if not self.profile_items:
            parts.append("(No public content available)")
        else:
            # Group by type
            posts = [i for i in self.profile_items if i.get("item_type") == "post"]
            comments = [i for i in self.profile_items if i.get("item_type") == "comment"]

            total_content_length = 0

            if posts:
                parts.append(f"\n### Posts ({len(posts)} total)")
                for item in posts[:10]:  # Limit to 10 posts
                    content = item.get("text_content", "")[:500]  # Truncate each item
                    total_content_length += len(content)
                    if total_content_length > self.max_content_length:
                        parts.append("(Content truncated...)")
                        break
                    item_id = item.get("id", "?")
                    created = item.get("item_created_at", "")
                    parts.append(f"\n[Post ID:{item_id}] ({created})")
                    parts.append(content)

            if comments and total_content_length < self.max_content_length:
                parts.append(f"\n### Comments ({len(comments)} total)")
                for item in comments[:10]:  # Limit to 10 comments
                    content = item.get("text_content", "")[:300]  # Shorter for comments
                    total_content_length += len(content)
                    if total_content_length > self.max_content_length:
                        parts.append("(Content truncated...)")
                        break
                    item_id = item.get("id", "?")
                    parts.append(f"\n[Comment ID:{item_id}]")
                    parts.append(content)

        return "\n".join(parts)


# =============================================================================
# AGENT RESULT
# =============================================================================


@dataclass
class ProfileSummaryResult:
    """Result from running the profile summary agent."""

    success: bool
    output: Optional[ProfileSummaryOutput] = None
    error: Optional[str] = None
    model_info: Optional[dict] = None
    raw_response: Optional[str] = None


# =============================================================================
# PROFILE SUMMARY AGENT
# =============================================================================


PROFILE_SUMMARY_SYSTEM_PROMPT = """You are an expert profile analyst. Your task is to analyze user profiles and generate structured summaries.

Given account information and their public content (posts, comments), you must:

1. **Summary**: Write a brief 2-3 sentence summary describing who this person is, their interests, and what they're known for.

2. **Signals**: Extract structured data points about the user. Common signals include:
   - interests: List of topics they're interested in
   - role: Their professional role or identity
   - industry: Industry they work in
   - experience_level: Beginner, intermediate, expert
   - activity_pattern: How they engage (poster, commenter, lurker)
   - looking_for: What they seem to be seeking (advice, customers, networking)

3. **Risk Flags**: Identify any concerning patterns:
   - spam_behavior: Promotional or spammy content
   - fake_account: Signs of inauthenticity
   - aggressive_behavior: Hostile or aggressive language
   - new_account: Very new with no history

4. **Citations**: For key claims in your summary, cite the specific content that supports it.

You MUST respond with valid JSON in this exact format:
{
    "summary": "Brief 2-3 sentence summary",
    "signals": [
        {"name": "signal_name", "value": "signal_value", "confidence": 0.8}
    ],
    "risk_flags": [
        {"type": "flag_type", "severity": "low|medium|high", "description": "Why this is a concern", "evidence_item_ids": [1, 2]}
    ],
    "citations": [
        {"item_id": 1, "quote": "exact quote", "relevance": "why this matters"}
    ]
}

Respond ONLY with the JSON object, no other text."""


class ProfileSummaryAgent:
    """Agent for generating profile summaries.

    Analyzes user profiles and generates structured summaries with
    signals, risk flags, and citations.
    """

    def __init__(
        self,
        inference_client: InferenceClient,
        voice_config: Optional[VoiceConfig] = None,
    ):
        """Initialize the profile summary agent.

        Args:
            inference_client: Client for LLM inference
            voice_config: Optional voice configuration
        """
        self.inference_client = inference_client
        self.voice_config = voice_config

    def get_system_prompt(self) -> str:
        """Get the system prompt for the agent.

        Returns:
            System prompt string
        """
        base_prompt = PROFILE_SUMMARY_SYSTEM_PROMPT

        if self.voice_config:
            voice_addition = self.voice_config.to_system_prompt()
            if voice_addition:
                base_prompt = f"{base_prompt}\n\nAdditional context: {voice_addition}"

        return base_prompt

    async def analyze(self, input_data: ProfileSummaryInput) -> ProfileSummaryResult:
        """Analyze a profile and generate a summary.

        Args:
            input_data: Profile input data

        Returns:
            ProfileSummaryResult with output or error
        """
        # Build messages
        messages = [
            ChatMessage(role="system", content=self.get_system_prompt()),
            ChatMessage(role="user", content=input_data.to_prompt()),
        ]

        # Make inference request
        try:
            response = await self.inference_client.chat(messages)
        except Exception as e:
            return ProfileSummaryResult(
                success=False,
                error=f"Inference error: {e}",
            )

        # Parse response
        try:
            # Try to extract JSON from response
            content = response.content.strip()

            # Handle potential markdown code blocks
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])

            data = json.loads(content)

            # Validate against schema
            output = ProfileSummaryOutput.model_validate(data)

            return ProfileSummaryResult(
                success=True,
                output=output,
                model_info=response.model_info.to_dict(),
                raw_response=response.content,
            )

        except json.JSONDecodeError as e:
            return ProfileSummaryResult(
                success=False,
                error=f"Invalid JSON response: {e}",
                model_info=response.model_info.to_dict() if response.model_info else None,
                raw_response=response.content,
            )
        except ValidationError as e:
            return ProfileSummaryResult(
                success=False,
                error=f"Validation error: {e}",
                model_info=response.model_info.to_dict() if response.model_info else None,
                raw_response=response.content,
            )


# =============================================================================
# PROFILE SUMMARY SERVICE
# =============================================================================


class ProfileSummaryService:
    """Service for orchestrating profile summary generation.

    Loads account data, runs the agent, and saves the snapshot.
    """

    def __init__(
        self,
        db,
        inference_client: InferenceClient,
    ):
        """Initialize the profile summary service.

        Args:
            db: Database session
            inference_client: Client for LLM inference
        """
        self.db = db
        self.inference_client = inference_client

    async def summarize_account(
        self,
        account_id: int,
        voice_config: Optional[VoiceConfig] = None,
    ) -> ProfileSummaryResult:
        """Generate a summary for an account.

        Args:
            account_id: ID of the external account
            voice_config: Optional voice configuration

        Returns:
            ProfileSummaryResult with the summary
        """
        from rediska_core.domain.models import ExternalAccount, ProfileItem, ProfileSnapshot

        # Load account
        account = self.db.query(ExternalAccount).get(account_id)
        if not account:
            return ProfileSummaryResult(
                success=False,
                error=f"Account {account_id} not found",
            )

        # Load profile items
        items = (
            self.db.query(ProfileItem)
            .filter(ProfileItem.account_id == account_id)
            .filter(ProfileItem.deleted_at.is_(None))
            .order_by(ProfileItem.item_created_at.desc())
            .limit(50)
            .all()
        )

        # Build metadata
        metadata = {
            "username": account.external_username,
            "provider_id": account.provider_id,
            "account_id": account.id,
            "analysis_state": account.analysis_state,
            "item_count": len(items),
        }

        # Convert items to dict format
        items_data = [
            {
                "id": item.id,
                "item_type": item.item_type,
                "external_item_id": item.external_item_id,
                "text_content": item.text_content,
                "item_created_at": str(item.item_created_at) if item.item_created_at else None,
            }
            for item in items
        ]

        # Create agent and run
        agent = ProfileSummaryAgent(
            inference_client=self.inference_client,
            voice_config=voice_config,
        )

        input_data = ProfileSummaryInput(
            account_metadata=metadata,
            profile_items=items_data,
        )

        result = await agent.analyze(input_data)

        # Save snapshot if successful
        if result.success and result.output:
            storage = result.output.to_storage_format()

            snapshot = ProfileSnapshot(
                account_id=account_id,
                fetched_at=datetime.utcnow(),
                summary_text=storage["summary_text"],
                signals_json=storage["signals_json"],
                risk_flags_json=storage["risk_flags_json"],
                model_info_json=result.model_info,
            )
            self.db.add(snapshot)
            self.db.commit()

        return result


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "Citation",
    "ProfileSummaryAgent",
    "ProfileSummaryInput",
    "ProfileSummaryOutput",
    "ProfileSummaryResult",
    "ProfileSummaryService",
    "RiskFlag",
    "Signal",
]
