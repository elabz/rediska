"""Unit tests for the draft intro agent.

Tests the agent that generates personalized intro messages:
1. Uses identity voice config for tone/style
2. Personalizes based on target profile
3. Returns draft without sending
4. Provides alternative versions
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from rediska_core.domain.services.agent import VoiceConfig
from rediska_core.domain.services.inference import (
    ChatResponse,
    InferenceClient,
    ModelInfo,
)
from rediska_core.domain.services.draft_intro import (
    DraftIntroAgent,
    DraftIntroInput,
    DraftIntroService,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_inference_client():
    """Create a mock inference client."""
    client = AsyncMock(spec=InferenceClient)
    return client


@pytest.fixture
def sample_voice_config():
    """Create a sample voice configuration."""
    return VoiceConfig(
        system_prompt="You are a friendly sales representative for a CRM company.",
        tone="professional yet approachable",
        style="conversational",
        persona_name="Alex",
    )


@pytest.fixture
def sample_target_profile():
    """Create sample target profile data."""
    return {
        "username": "startup_ceo",
        "provider_id": "reddit",
        "summary": "Tech startup founder building B2B SaaS products. Recently raised Series A.",
        "signals": [
            {"name": "role", "value": "founder/CEO", "confidence": 0.95},
            {"name": "industry", "value": "B2B SaaS", "confidence": 0.9},
            {"name": "company_stage", "value": "Series A", "confidence": 0.85},
        ],
        "interests": ["AI", "developer tools", "startups"],
    }


@pytest.fixture
def sample_lead_context():
    """Create sample lead post context."""
    return {
        "title": "Looking for a CRM solution",
        "body_text": "We're a growing startup looking for a CRM that integrates with Slack. "
        "Budget around $500/month. Need good automation features.",
        "source_location": "r/startups",
    }


# =============================================================================
# DRAFT INTRO INPUT TESTS
# =============================================================================


class TestDraftIntroInput:
    """Tests for DraftIntroInput."""

    def test_input_to_prompt(self, sample_target_profile, sample_lead_context):
        """Input should generate a prompt for the agent."""
        input_data = DraftIntroInput(
            target_profile=sample_target_profile,
            lead_context=sample_lead_context,
        )

        prompt = input_data.to_prompt()

        assert "startup_ceo" in prompt
        assert "CRM" in prompt
        assert "B2B SaaS" in prompt

    def test_to_prompt_renders_product_context_and_instructions(self, sample_target_profile):
        """Optional sections should be rendered, with lists comma-joined."""
        input_data = DraftIntroInput(
            target_profile=sample_target_profile,
            product_context={
                "product_name": "SuperCRM",
                "key_features": ["Slack integration", "automation", "analytics"],
            },
            custom_instructions="Keep the message under 100 words. Focus on ROI.",
        )

        prompt = input_data.to_prompt()

        assert "## Product Context" in prompt
        assert "- product_name: SuperCRM" in prompt
        # list values are joined, not repr'd
        assert "- key_features: Slack integration, automation, analytics" in prompt
        assert "## Special Instructions" in prompt
        assert "Keep the message under 100 words. Focus on ROI." in prompt

    def test_to_prompt_omits_absent_optional_sections(self, sample_target_profile):
        """Sections with no data must not appear as empty headers."""
        prompt = DraftIntroInput(target_profile=sample_target_profile).to_prompt()

        assert "## Lead Post Context" not in prompt
        assert "## Product Context" not in prompt
        assert "## Special Instructions" not in prompt
        assert "## Task" in prompt


# =============================================================================
# DRAFT INTRO AGENT TESTS
# =============================================================================


class TestDraftIntroAgent:
    """Tests for DraftIntroAgent."""

    @pytest.mark.asyncio
    async def test_agent_generates_draft(
        self, mock_inference_client, sample_voice_config, sample_target_profile
    ):
        """Agent should generate a draft intro message."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "primary_draft": {
                    "subject": "Quick question about your CRM search",
                    "body": "Hi! I noticed your post about looking for a CRM solution for your growing team. As someone who works with startups at your stage, I'd love to share some insights that might help. Would you be open to a quick chat?",
                    "tone_used": "professional yet friendly",
                    "personalization_notes": ["Referenced their CRM search", "Acknowledged their growth stage"]
                },
                "alternatives": [],
                "personalization_used": ["company_stage", "need_stated"],
                "reasoning": "Used a helpful, non-pushy approach based on their genuine need."
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=400,
                output_tokens=150,
                latency_ms=600,
            ),
            finish_reason="stop",
        )

        agent = DraftIntroAgent(
            inference_client=mock_inference_client,
            voice_config=sample_voice_config,
        )

        input_data = DraftIntroInput(target_profile=sample_target_profile)

        result = await agent.draft(input_data)

        assert result.success
        assert result.output is not None
        assert result.output.primary_draft.body is not None
        assert len(result.output.primary_draft.body) > 20

    @pytest.mark.asyncio
    async def test_agent_uses_voice_config(
        self, mock_inference_client, sample_voice_config, sample_target_profile
    ):
        """Agent should use voice config in system prompt."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "primary_draft": {
                    "subject": "Hello from Alex",
                    "body": "Hey there! Alex here from the CRM team...",
                    "tone_used": "friendly",
                    "personalization_notes": []
                },
                "alternatives": [],
                "personalization_used": [],
                "reasoning": "Used friendly Alex persona as specified."
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=350,
                output_tokens=100,
                latency_ms=450,
            ),
            finish_reason="stop",
        )

        agent = DraftIntroAgent(
            inference_client=mock_inference_client,
            voice_config=sample_voice_config,
        )

        input_data = DraftIntroInput(target_profile=sample_target_profile)

        await agent.draft(input_data)

        # Verify voice config was included in system prompt
        call_args = mock_inference_client.chat.call_args
        messages = call_args[0][0]
        system_prompt = messages[0].content

        assert "Alex" in system_prompt or "friendly" in system_prompt.lower()
        assert "professional" in system_prompt.lower() or "approachable" in system_prompt.lower()

    @pytest.mark.asyncio
    async def test_agent_personalizes_message(
        self, mock_inference_client, sample_voice_config, sample_target_profile, sample_lead_context
    ):
        """Agent should personalize based on target profile."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "primary_draft": {
                    "subject": "Re: CRM for your B2B SaaS startup",
                    "body": "Hi! Congrats on the Series A - exciting times! I saw you're looking for a CRM with Slack integration. We've helped several B2B SaaS companies at your stage streamline their sales process...",
                    "tone_used": "professional",
                    "personalization_notes": ["Mentioned Series A funding", "Referenced B2B SaaS industry", "Addressed Slack integration need"]
                },
                "alternatives": [],
                "personalization_used": ["company_stage", "industry", "specific_need"],
                "reasoning": "Personalized based on their funding stage and specific requirements."
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=500,
                output_tokens=180,
                latency_ms=700,
            ),
            finish_reason="stop",
        )

        agent = DraftIntroAgent(
            inference_client=mock_inference_client,
            voice_config=sample_voice_config,
        )

        input_data = DraftIntroInput(
            target_profile=sample_target_profile,
            lead_context=sample_lead_context,
        )

        result = await agent.draft(input_data)

        assert result.success

        # The agent only parses the model's reply, so asserting on the drafted
        # body would just read back the canned mock. What the agent actually
        # controls is the prompt: assert the target-profile signals and lead
        # context it was given are all present in the user message.
        user_prompt = mock_inference_client.chat.call_args[0][0][1].content

        assert "startup_ceo" in user_prompt
        assert "founder/CEO" in user_prompt  # signals[].name/value pairs
        assert "B2B SaaS" in user_prompt
        assert "Series A" in user_prompt
        assert "AI, developer tools, startups" in user_prompt  # interests joined
        assert "Looking for a CRM solution" in user_prompt  # lead title
        assert "r/startups" in user_prompt  # lead source_location
        assert "integrates with Slack" in user_prompt  # lead body_text

    @pytest.mark.asyncio
    async def test_agent_provides_alternatives(
        self, mock_inference_client, sample_voice_config, sample_target_profile
    ):
        """Agent should provide alternative drafts."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "primary_draft": {
                    "subject": "Formal introduction",
                    "body": "Dear startup_ceo, I hope this message finds you well...",
                    "tone_used": "formal",
                    "personalization_notes": []
                },
                "alternatives": [
                    {
                        "subject": "Quick thought on your CRM search",
                        "body": "Hey! Saw your post - mind if I share some CRM insights?",
                        "tone_used": "casual",
                        "personalization_notes": ["More casual approach"]
                    },
                    {
                        "subject": null,
                        "body": "Hi! I work with startups on CRM solutions. Happy to help if useful!",
                        "tone_used": "direct",
                        "personalization_notes": ["Short and direct"]
                    }
                ],
                "personalization_used": [],
                "reasoning": "Provided formal, casual, and direct options."
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=400,
                output_tokens=200,
                latency_ms=800,
            ),
            finish_reason="stop",
        )

        agent = DraftIntroAgent(
            inference_client=mock_inference_client,
            voice_config=sample_voice_config,
        )

        input_data = DraftIntroInput(target_profile=sample_target_profile)

        result = await agent.draft(input_data)

        assert result.success
        assert result.output is not None

        # Exact count and field mapping: `>= 1` would pass even if the parser
        # silently dropped an alternative. The second alternative has a null
        # subject, which pins Optional[str] handling on the nested model.
        assert len(result.output.alternatives) == 2
        assert result.output.alternatives[0].tone_used == "casual"
        assert result.output.alternatives[1].subject is None
        assert result.output.alternatives[1].tone_used == "direct"

        # The agent controls the prompt, not the reply: assert the target
        # profile it was handed actually reached the user message.
        user_prompt = mock_inference_client.chat.call_args[0][0][1].content
        assert "startup_ceo" in user_prompt
        assert "B2B SaaS" in user_prompt

    @pytest.mark.asyncio
    async def test_agent_returns_model_info(
        self, mock_inference_client, sample_voice_config, sample_target_profile
    ):
        """Agent should return model info for auditing."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "primary_draft": {
                    "subject": "Hello",
                    "body": "Hi there!",
                    "tone_used": "friendly",
                    "personalization_notes": []
                },
                "alternatives": [],
                "personalization_used": [],
                "reasoning": "Simple greeting."
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=300,
                output_tokens=60,
                latency_ms=300,
            ),
            finish_reason="stop",
        )

        agent = DraftIntroAgent(
            inference_client=mock_inference_client,
            voice_config=sample_voice_config,
        )

        input_data = DraftIntroInput(target_profile=sample_target_profile)

        result = await agent.draft(input_data)

        assert result.model_info is not None
        assert result.model_info["model_name"] == "llama-3.2-8b"


# =============================================================================
# VOICE CONFIG INTEGRATION TESTS
# =============================================================================


class TestDraftIntroVoiceConfig:
    """Tests for voice config integration."""

    @pytest.mark.asyncio
    async def test_different_voice_configs_produce_different_styles(
        self, mock_inference_client, sample_target_profile
    ):
        """Different voice configs should produce different message styles."""
        formal_voice = VoiceConfig(
            system_prompt="You are a formal business development representative.",
            tone="formal and professional",
            style="business formal",
        )

        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "primary_draft": {
                    "subject": "Business Inquiry",
                    "body": "Dear Sir/Madam, I am writing to inquire...",
                    "tone_used": "formal",
                    "personalization_notes": []
                },
                "alternatives": [],
                "personalization_used": [],
                "reasoning": "Formal approach as per voice config."
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=300,
                output_tokens=80,
                latency_ms=400,
            ),
            finish_reason="stop",
        )

        agent = DraftIntroAgent(
            inference_client=mock_inference_client,
            voice_config=formal_voice,
        )

        input_data = DraftIntroInput(target_profile=sample_target_profile)

        await agent.draft(input_data)

        # Verify formal voice was used
        call_args = mock_inference_client.chat.call_args
        messages = call_args[0][0]
        system_prompt = messages[0].content

        assert "formal" in system_prompt.lower()

    @pytest.mark.asyncio
    async def test_agent_without_voice_config(
        self, mock_inference_client, sample_target_profile
    ):
        """Agent should work without voice config (use defaults)."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "primary_draft": {
                    "subject": "Hello",
                    "body": "Hi! I'd like to connect...",
                    "tone_used": "neutral",
                    "personalization_notes": []
                },
                "alternatives": [],
                "personalization_used": [],
                "reasoning": "Default professional tone."
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=250,
                output_tokens=60,
                latency_ms=300,
            ),
            finish_reason="stop",
        )

        agent = DraftIntroAgent(
            inference_client=mock_inference_client,
            voice_config=None,  # No voice config
        )

        input_data = DraftIntroInput(target_profile=sample_target_profile)

        result = await agent.draft(input_data)

        assert result.success


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


class TestDraftIntroAgentErrors:
    """Tests for error handling in DraftIntroAgent."""

    @pytest.mark.asyncio
    async def test_agent_handles_invalid_json(
        self, mock_inference_client, sample_voice_config
    ):
        """Agent should handle invalid JSON response."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="This is not valid JSON",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=100,
                output_tokens=10,
                latency_ms=100,
            ),
            finish_reason="stop",
        )

        agent = DraftIntroAgent(
            inference_client=mock_inference_client,
            voice_config=sample_voice_config,
        )

        input_data = DraftIntroInput(
            target_profile={"username": "test"},
        )

        result = await agent.draft(input_data)

        assert not result.success
        assert result.error is not None


# =============================================================================
# SYSTEM PROMPT TESTS
# =============================================================================


class TestDraftIntroSystemPrompt:
    """Tests for the draft intro system prompt."""

    def test_system_prompt_includes_drafting_instructions(self):
        """System prompt should include message drafting instructions."""
        agent = DraftIntroAgent(
            inference_client=AsyncMock(),
            voice_config=VoiceConfig(tone="friendly"),
        )

        prompt = agent.get_system_prompt()

        # Assert the structural contract rather than incidental prose: the
        # prompt must name every JSON key DraftIntroOutput/DraftMessage
        # require, otherwise the model cannot produce a parseable reply.
        for required_key in (
            '"primary_draft"',
            '"alternatives"',
            '"personalization_used"',
            '"reasoning"',
            '"body"',
            '"tone_used"',
            '"personalization_notes"',
        ):
            assert required_key in prompt, f"system prompt missing {required_key}"

    def test_system_prompt_includes_voice_config(self):
        """System prompt should incorporate voice config."""
        voice = VoiceConfig(
            system_prompt="You are a helpful sales rep named Bob.",
            tone="casual",
            persona_name="Bob",
        )

        agent = DraftIntroAgent(
            inference_client=AsyncMock(),
            voice_config=voice,
        )

        prompt = agent.get_system_prompt()

        assert "Bob" in prompt or "casual" in prompt.lower()

    def test_system_prompt_specifies_output_format(self):
        """System prompt should specify JSON output format."""
        agent = DraftIntroAgent(
            inference_client=AsyncMock(),
            voice_config=None,
        )

        prompt = agent.get_system_prompt()

        assert "json" in prompt.lower()
