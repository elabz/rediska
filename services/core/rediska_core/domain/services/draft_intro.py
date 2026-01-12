"""Draft intro agent for generating personalized intro messages.

Generates personalized introductory messages:
1. Uses identity voice config for tone/style
2. Personalizes based on target profile
3. Returns draft without sending (manual approval required)
4. Provides alternative versions

Usage:
    voice_config = VoiceConfig.from_dict(identity.voice_config_json)

    agent = DraftIntroAgent(
        inference_client=client,
        voice_config=voice_config,
    )

    input_data = DraftIntroInput(
        target_profile={"username": "...", "summary": "..."},
        lead_context={"title": "...", "body_text": "..."},
    )

    result = await agent.draft(input_data)

    if result.success:
        print(result.output.primary_draft.body)
        # User reviews and clicks "Send" button
"""

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError

from rediska_core.domain.services.agent import VoiceConfig
from rediska_core.domain.services.inference import ChatMessage, InferenceClient


# =============================================================================
# OUTPUT SCHEMAS
# =============================================================================


class DraftMessage(BaseModel):
    """A draft message ready for review.

    Represents a single draft that the user can review and send.
    """

    subject: Optional[str] = Field(
        default=None, description="Subject line (optional, for emails/titled messages)"
    )
    body: str = Field(..., description="The message body text")
    tone_used: str = Field(default="neutral", description="The tone used in this draft")
    personalization_notes: list[str] = Field(
        default_factory=list, description="What personalization was applied"
    )


class DraftIntroOutput(BaseModel):
    """Structured output from the draft intro agent."""

    primary_draft: DraftMessage = Field(..., description="The primary recommended draft")
    alternatives: list[DraftMessage] = Field(
        default_factory=list, description="Alternative draft versions"
    )
    personalization_used: list[str] = Field(
        default_factory=list, description="What profile data was used for personalization"
    )
    reasoning: Optional[str] = Field(
        default=None, description="Why this approach was chosen"
    )


# =============================================================================
# INPUT DATA
# =============================================================================


@dataclass
class DraftIntroInput:
    """Input data for the draft intro agent.

    Combines target profile, lead context, and optional instructions.
    """

    target_profile: dict = field(default_factory=dict)
    lead_context: Optional[dict] = None
    product_context: Optional[dict] = None
    custom_instructions: Optional[str] = None

    def to_prompt(self) -> str:
        """Generate a prompt from the input data.

        Returns:
            Formatted prompt string for the agent
        """
        parts = []

        # Target profile section
        parts.append("## Target Profile")
        parts.append(f"Username: {self.target_profile.get('username', 'Unknown')}")

        if self.target_profile.get("summary"):
            parts.append(f"Summary: {self.target_profile.get('summary')}")

        signals = self.target_profile.get("signals", [])
        if signals:
            parts.append("\nKnown signals:")
            for signal in signals[:5]:
                name = signal.get("name", "")
                value = signal.get("value", "")
                parts.append(f"- {name}: {value}")

        interests = self.target_profile.get("interests", [])
        if interests:
            parts.append(f"\nInterests: {', '.join(interests[:5])}")

        parts.append("")

        # Lead context section
        if self.lead_context:
            parts.append("## Lead Post Context")
            if self.lead_context.get("title"):
                parts.append(f"Title: {self.lead_context.get('title')}")
            if self.lead_context.get("source_location"):
                parts.append(f"Source: {self.lead_context.get('source_location')}")
            if self.lead_context.get("body_text"):
                parts.append(f"\nContent:\n{self.lead_context.get('body_text')[:1000]}")
            parts.append("")

        # Product context section
        if self.product_context:
            parts.append("## Product Context")
            for key, value in self.product_context.items():
                if isinstance(value, list):
                    parts.append(f"- {key}: {', '.join(str(v) for v in value)}")
                else:
                    parts.append(f"- {key}: {value}")
            parts.append("")

        # Custom instructions
        if self.custom_instructions:
            parts.append("## Special Instructions")
            parts.append(self.custom_instructions)
            parts.append("")

        parts.append("## Task")
        parts.append("Write a personalized intro message for this target.")

        return "\n".join(parts)


# =============================================================================
# AGENT RESULT
# =============================================================================


@dataclass
class DraftIntroResult:
    """Result from running the draft intro agent."""

    success: bool
    output: Optional[DraftIntroOutput] = None
    error: Optional[str] = None
    model_info: Optional[dict] = None
    raw_response: Optional[str] = None


# =============================================================================
# DRAFT INTRO AGENT
# =============================================================================


DRAFT_INTRO_SYSTEM_PROMPT = """You are an expert at writing personalized introductory messages. Your task is to draft messages that will start meaningful conversations.

**Guidelines for Effective Intros:**
1. **Be Personal**: Reference specific details from their profile or post
2. **Be Genuine**: Don't be pushy or salesy - focus on being helpful
3. **Be Concise**: Keep messages short and easy to respond to
4. **Be Relevant**: Connect to their stated needs or interests
5. **Be Human**: Write like a real person, not a marketing bot

**Message Structure:**
- Opening: Reference something specific about them (shows you read their post/profile)
- Value: Briefly explain how you might help (without a hard sell)
- Call to Action: Simple, low-commitment ask (chat, question, etc.)

**Things to Avoid:**
- Generic templates that could apply to anyone
- Aggressive sales language ("buy now", "limited time", etc.)
- Very long messages (keep under 150 words typically)
- Multiple asks or CTAs

You MUST respond with valid JSON in this exact format:
{
    "primary_draft": {
        "subject": "optional subject line or null",
        "body": "the message text",
        "tone_used": "description of tone used",
        "personalization_notes": ["what was personalized"]
    },
    "alternatives": [
        {
            "subject": "optional",
            "body": "alternative message",
            "tone_used": "tone",
            "personalization_notes": []
        }
    ],
    "personalization_used": ["list of profile elements used"],
    "reasoning": "why this approach was chosen"
}

Respond ONLY with the JSON object, no other text."""


class DraftIntroAgent:
    """Agent for drafting personalized intro messages.

    Uses identity voice config to match the sender's persona
    and personalizes based on the target's profile.
    """

    def __init__(
        self,
        inference_client: InferenceClient,
        voice_config: Optional[VoiceConfig] = None,
    ):
        """Initialize the draft intro agent.

        Args:
            inference_client: Client for LLM inference
            voice_config: Voice configuration from identity
        """
        self.inference_client = inference_client
        self.voice_config = voice_config

    def get_system_prompt(self) -> str:
        """Get the system prompt for the agent.

        Incorporates voice config if provided.

        Returns:
            System prompt string
        """
        base_prompt = DRAFT_INTRO_SYSTEM_PROMPT

        if self.voice_config:
            voice_additions = []

            if self.voice_config.system_prompt:
                voice_additions.append(f"\n**Your Persona:**\n{self.voice_config.system_prompt}")

            if self.voice_config.tone:
                voice_additions.append(f"\n**Required Tone:** {self.voice_config.tone}")

            if self.voice_config.style:
                voice_additions.append(f"\n**Communication Style:** {self.voice_config.style}")

            if self.voice_config.persona_name:
                voice_additions.append(f"\n**Sign as:** {self.voice_config.persona_name}")

            if voice_additions:
                base_prompt = base_prompt + "\n" + "\n".join(voice_additions)

        return base_prompt

    async def draft(self, input_data: DraftIntroInput) -> DraftIntroResult:
        """Draft an intro message.

        Args:
            input_data: Draft intro input data

        Returns:
            DraftIntroResult with output or error
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
            return DraftIntroResult(
                success=False,
                error=f"Inference error: {e}",
            )

        # Parse response
        try:
            content = response.content.strip()

            # Handle potential markdown code blocks
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])

            data = json.loads(content)

            # Validate against schema
            output = DraftIntroOutput.model_validate(data)

            return DraftIntroResult(
                success=True,
                output=output,
                model_info=response.model_info.to_dict(),
                raw_response=response.content,
            )

        except json.JSONDecodeError as e:
            return DraftIntroResult(
                success=False,
                error=f"Invalid JSON response: {e}",
                model_info=response.model_info.to_dict() if response.model_info else None,
                raw_response=response.content,
            )
        except ValidationError as e:
            return DraftIntroResult(
                success=False,
                error=f"Validation error: {e}",
                model_info=response.model_info.to_dict() if response.model_info else None,
                raw_response=response.content,
            )


# =============================================================================
# DRAFT INTRO SERVICE
# =============================================================================


class DraftIntroService:
    """Service for orchestrating draft intro generation.

    Loads target profile, identity voice config, and runs the agent.
    Does NOT send the message - returns draft for user approval.
    """

    def __init__(
        self,
        db,
        inference_client: InferenceClient,
    ):
        """Initialize the draft intro service.

        Args:
            db: Database session
            inference_client: Client for LLM inference
        """
        self.db = db
        self.inference_client = inference_client

    async def draft_for_lead(
        self,
        lead_id: int,
        identity_id: int,
        custom_instructions: Optional[str] = None,
        product_context: Optional[dict] = None,
    ) -> DraftIntroResult:
        """Draft an intro message for a lead.

        Args:
            lead_id: ID of the lead post
            identity_id: ID of the identity to use for voice config
            custom_instructions: Optional custom drafting instructions
            product_context: Optional product/service context

        Returns:
            DraftIntroResult with the draft (NOT sent)
        """
        from rediska_core.domain.models import Identity, LeadPost, ProfileSnapshot

        # Load lead
        lead = self.db.get(LeadPost, lead_id)
        if not lead:
            return DraftIntroResult(
                success=False,
                error=f"Lead {lead_id} not found",
            )

        # Load identity and voice config
        identity = self.db.get(Identity, identity_id)
        if not identity:
            return DraftIntroResult(
                success=False,
                error=f"Identity {identity_id} not found",
            )

        voice_config = VoiceConfig.from_dict(identity.voice_config_json)

        # Build lead context
        lead_context = {
            "title": lead.title,
            "body_text": lead.body_text,
            "source_location": lead.source_location,
            "post_url": lead.post_url,
        }

        # Get target profile if author exists
        target_profile = {"username": "unknown"}

        if lead.author_account_id:
            from rediska_core.domain.models import ExternalAccount

            account = self.db.get(ExternalAccount, lead.author_account_id)
            if account:
                target_profile["username"] = account.external_username
                target_profile["provider_id"] = account.provider_id

                # Get latest snapshot
                snapshot = (
                    self.db.query(ProfileSnapshot)
                    .filter(ProfileSnapshot.account_id == account.id)
                    .order_by(ProfileSnapshot.fetched_at.desc())
                    .first()
                )

                if snapshot:
                    target_profile["summary"] = snapshot.summary_text
                    target_profile["signals"] = snapshot.signals_json or []

        # Create agent and run
        agent = DraftIntroAgent(
            inference_client=self.inference_client,
            voice_config=voice_config,
        )

        input_data = DraftIntroInput(
            target_profile=target_profile,
            lead_context=lead_context,
            product_context=product_context,
            custom_instructions=custom_instructions,
        )

        return await agent.draft(input_data)

    async def draft_for_account(
        self,
        account_id: int,
        identity_id: int,
        custom_instructions: Optional[str] = None,
        product_context: Optional[dict] = None,
    ) -> DraftIntroResult:
        """Draft an intro message for an external account.

        Args:
            account_id: ID of the external account
            identity_id: ID of the identity to use for voice config
            custom_instructions: Optional custom drafting instructions
            product_context: Optional product/service context

        Returns:
            DraftIntroResult with the draft (NOT sent)
        """
        from rediska_core.domain.models import ExternalAccount, Identity, ProfileSnapshot

        # Load account
        account = self.db.get(ExternalAccount, account_id)
        if not account:
            return DraftIntroResult(
                success=False,
                error=f"Account {account_id} not found",
            )

        # Load identity and voice config
        identity = self.db.get(Identity, identity_id)
        if not identity:
            return DraftIntroResult(
                success=False,
                error=f"Identity {identity_id} not found",
            )

        voice_config = VoiceConfig.from_dict(identity.voice_config_json)

        # Build target profile
        target_profile = {
            "username": account.external_username,
            "provider_id": account.provider_id,
        }

        # Get latest snapshot
        snapshot = (
            self.db.query(ProfileSnapshot)
            .filter(ProfileSnapshot.account_id == account.id)
            .order_by(ProfileSnapshot.fetched_at.desc())
            .first()
        )

        if snapshot:
            target_profile["summary"] = snapshot.summary_text
            target_profile["signals"] = snapshot.signals_json or []

        # Create agent and run
        agent = DraftIntroAgent(
            inference_client=self.inference_client,
            voice_config=voice_config,
        )

        input_data = DraftIntroInput(
            target_profile=target_profile,
            product_context=product_context,
            custom_instructions=custom_instructions,
        )

        return await agent.draft(input_data)


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "DraftIntroAgent",
    "DraftIntroInput",
    "DraftIntroOutput",
    "DraftIntroResult",
    "DraftIntroService",
    "DraftMessage",
]
