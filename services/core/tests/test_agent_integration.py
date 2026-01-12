"""Integration tests for agent infrastructure.

Tests the full flow:
1. Loading voice config from Identity
2. Injecting voice config into agent
3. Running agent with structured outputs
4. Recording model info for auditing
"""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel, Field

from rediska_core.domain.models import Identity, Provider
from rediska_core.domain.services.agent import (
    AgentConfig,
    AgentHarness,
    VoiceConfig,
)
from rediska_core.domain.services.inference import (
    ChatResponse,
    InferenceClient,
    ModelInfo,
)


# =============================================================================
# TEST SCHEMAS
# =============================================================================


class ProfileSummaryOutput(BaseModel):
    """Structured output for profile summaries."""

    summary: str = Field(..., description="Brief summary")
    interests: list[str] = Field(default_factory=list)
    score: int = Field(..., ge=0, le=100)


class DraftIntroOutput(BaseModel):
    """Structured output for draft intros."""

    message: str = Field(..., description="Draft message")
    subject: str = Field(default="", description="Subject line")
    tone_used: str = Field(default="neutral")


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def setup_provider(db_session):
    """Set up provider for tests."""
    provider = Provider(provider_id="reddit", display_name="Reddit")
    db_session.add(provider)
    db_session.flush()
    return provider


@pytest.fixture
def identity_with_voice_config(db_session, setup_provider):
    """Create an identity with voice configuration."""
    identity = Identity(
        provider_id="reddit",
        external_username="sales_rep",
        external_user_id="t2_salesrep",
        display_name="Sales Representative",
        voice_config_json={
            "system_prompt": "You are a professional sales representative for a SaaS company.",
            "tone": "friendly and professional",
            "style": "conversational",
            "persona_name": "Alex from SalesTeam",
        },
        is_default=True,
        is_active=True,
    )
    db_session.add(identity)
    db_session.flush()
    return identity


@pytest.fixture
def identity_without_voice_config(db_session, setup_provider):
    """Create an identity without voice configuration."""
    identity = Identity(
        provider_id="reddit",
        external_username="basic_user",
        external_user_id="t2_basic",
        display_name="Basic User",
        voice_config_json=None,
        is_default=False,
        is_active=True,
    )
    db_session.add(identity)
    db_session.flush()
    return identity


@pytest.fixture
def mock_inference_client():
    """Create a mock inference client."""
    client = AsyncMock(spec=InferenceClient)
    return client


# =============================================================================
# VOICE CONFIG FROM IDENTITY TESTS
# =============================================================================


class TestVoiceConfigFromIdentity:
    """Tests for loading voice config from Identity model."""

    def test_load_voice_config_from_identity(self, identity_with_voice_config):
        """VoiceConfig should load from identity.voice_config_json."""
        identity = identity_with_voice_config

        voice_config = VoiceConfig.from_dict(identity.voice_config_json)

        assert voice_config.system_prompt == "You are a professional sales representative for a SaaS company."
        assert voice_config.tone == "friendly and professional"
        assert voice_config.style == "conversational"
        assert voice_config.persona_name == "Alex from SalesTeam"

    def test_load_voice_config_from_identity_without_config(self, identity_without_voice_config):
        """VoiceConfig should handle identity without voice_config_json."""
        identity = identity_without_voice_config

        voice_config = VoiceConfig.from_dict(identity.voice_config_json)

        assert voice_config.system_prompt is None
        assert voice_config.tone is None

    def test_voice_config_generates_system_prompt(self, identity_with_voice_config):
        """Voice config should generate proper system prompt."""
        identity = identity_with_voice_config
        voice_config = VoiceConfig.from_dict(identity.voice_config_json)

        system_prompt = voice_config.to_system_prompt()

        assert "sales representative" in system_prompt
        assert "friendly" in system_prompt.lower() or "professional" in system_prompt.lower()
        assert "Alex" in system_prompt


# =============================================================================
# AGENT WITH IDENTITY VOICE TESTS
# =============================================================================


class TestAgentWithIdentityVoice:
    """Tests for running agents with identity voice configuration."""

    @pytest.mark.asyncio
    async def test_agent_uses_identity_voice(
        self, identity_with_voice_config, mock_inference_client
    ):
        """Agent should use voice config from identity."""
        identity = identity_with_voice_config
        voice_config = VoiceConfig.from_dict(identity.voice_config_json)

        mock_inference_client.chat.return_value = ChatResponse(
            content="Hello! I'm Alex from SalesTeam.",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=1024,
                input_tokens=50,
                output_tokens=20,
                latency_ms=200,
            ),
            finish_reason="stop",
        )

        config = AgentConfig(
            name="intro_agent",
            system_prompt="You write introductory messages.",
        )

        harness = AgentHarness(
            config=config,
            inference_client=mock_inference_client,
            voice_config=voice_config,
        )

        result = await harness.run("Write an intro message")

        assert result.success

        # Verify the system prompt included voice config
        call_args = mock_inference_client.chat.call_args
        messages = call_args[0][0]  # First positional arg is messages
        system_message = messages[0]
        assert "sales representative" in system_message.content.lower()

    @pytest.mark.asyncio
    async def test_agent_without_voice_config(
        self, identity_without_voice_config, mock_inference_client
    ):
        """Agent should work without voice config."""
        identity = identity_without_voice_config
        voice_config = VoiceConfig.from_dict(identity.voice_config_json)

        mock_inference_client.chat.return_value = ChatResponse(
            content="Generic response.",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=1024,
                input_tokens=30,
                output_tokens=10,
                latency_ms=100,
            ),
            finish_reason="stop",
        )

        config = AgentConfig(
            name="basic_agent",
            system_prompt="You are a helpful assistant.",
        )

        harness = AgentHarness(
            config=config,
            inference_client=mock_inference_client,
            voice_config=voice_config,
        )

        result = await harness.run("Hello")

        assert result.success


# =============================================================================
# STRUCTURED OUTPUT WITH IDENTITY TESTS
# =============================================================================


class TestStructuredOutputWithIdentity:
    """Tests for structured outputs with identity-aware agents."""

    @pytest.mark.asyncio
    async def test_profile_summary_agent(
        self, identity_with_voice_config, mock_inference_client
    ):
        """Profile summary agent should return structured output."""
        voice_config = VoiceConfig.from_dict(identity_with_voice_config.voice_config_json)

        mock_inference_client.chat.return_value = ChatResponse(
            content='{"summary": "Active Reddit user interested in tech", "interests": ["programming", "startups"], "score": 85}',
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=1024,
                input_tokens=100,
                output_tokens=50,
                latency_ms=300,
            ),
            finish_reason="stop",
        )

        config = AgentConfig(
            name="profile_summary",
            system_prompt="You analyze user profiles and provide summaries.",
            output_schema=ProfileSummaryOutput,
        )

        harness = AgentHarness(
            config=config,
            inference_client=mock_inference_client,
            voice_config=voice_config,
        )

        result = await harness.run("Summarize this user's profile based on their posts...")

        assert result.success
        assert result.parsed_output is not None
        assert result.parsed_output["summary"] == "Active Reddit user interested in tech"
        assert "programming" in result.parsed_output["interests"]
        assert result.parsed_output["score"] == 85

    @pytest.mark.asyncio
    async def test_draft_intro_agent_with_voice(
        self, identity_with_voice_config, mock_inference_client
    ):
        """Draft intro agent should use voice config and return structured output."""
        voice_config = VoiceConfig.from_dict(identity_with_voice_config.voice_config_json)

        mock_inference_client.chat.return_value = ChatResponse(
            content='{"message": "Hi! I noticed your interest in our product. Would love to chat!", "subject": "Quick question", "tone_used": "friendly"}',
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=1024,
                input_tokens=80,
                output_tokens=40,
                latency_ms=250,
            ),
            finish_reason="stop",
        )

        config = AgentConfig(
            name="draft_intro",
            system_prompt="You write introductory messages to potential leads.",
            output_schema=DraftIntroOutput,
        )

        harness = AgentHarness(
            config=config,
            inference_client=mock_inference_client,
            voice_config=voice_config,
        )

        result = await harness.run("Draft an intro message for this lead")

        assert result.success
        assert result.parsed_output is not None
        assert "message" in result.parsed_output
        assert result.parsed_output["tone_used"] == "friendly"


# =============================================================================
# MODEL INFO RECORDING TESTS
# =============================================================================


class TestModelInfoRecording:
    """Tests for model info recording for auditing."""

    @pytest.mark.asyncio
    async def test_agent_records_model_info(
        self, identity_with_voice_config, mock_inference_client
    ):
        """Agent should record model info for audit logging."""
        voice_config = VoiceConfig.from_dict(identity_with_voice_config.voice_config_json)

        mock_inference_client.chat.return_value = ChatResponse(
            content="Response",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=150,
                output_tokens=75,
                latency_ms=450,
            ),
            finish_reason="stop",
        )

        config = AgentConfig(name="test_agent")

        harness = AgentHarness(
            config=config,
            inference_client=mock_inference_client,
            voice_config=voice_config,
        )

        result = await harness.run("Test query")

        # Model info should be present
        assert result.model_info is not None
        assert result.model_info["model_name"] == "llama-3.2-8b"
        assert result.model_info["provider"] == "llama.cpp"
        assert result.model_info["input_tokens"] == 150
        assert result.model_info["output_tokens"] == 75
        assert result.model_info["latency_ms"] == 450

    @pytest.mark.asyncio
    async def test_model_info_can_be_stored_in_snapshot(
        self, identity_with_voice_config, mock_inference_client, db_session
    ):
        """Model info should be JSON-serializable for profile_snapshots.model_info_json."""
        from rediska_core.domain.models import ExternalAccount, ProfileSnapshot

        # Create an account for the snapshot
        account = ExternalAccount(
            provider_id="reddit",
            external_username="target_user",
            external_user_id="t2_target",
        )
        db_session.add(account)
        db_session.flush()

        voice_config = VoiceConfig.from_dict(identity_with_voice_config.voice_config_json)

        mock_inference_client.chat.return_value = ChatResponse(
            content='{"summary": "Test", "interests": [], "score": 50}',
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=100,
                output_tokens=50,
                latency_ms=300,
            ),
            finish_reason="stop",
        )

        config = AgentConfig(
            name="profile_agent",
            output_schema=ProfileSummaryOutput,
        )

        harness = AgentHarness(
            config=config,
            inference_client=mock_inference_client,
            voice_config=voice_config,
        )

        result = await harness.run("Summarize profile")

        # Create snapshot with model info
        snapshot = ProfileSnapshot(
            account_id=account.id,
            fetched_at=datetime.utcnow(),
            summary_text=result.parsed_output["summary"] if result.parsed_output else "",
            model_info_json=result.model_info,
        )
        db_session.add(snapshot)
        db_session.commit()

        # Verify it was stored correctly
        stored = db_session.query(ProfileSnapshot).filter_by(account_id=account.id).first()
        assert stored is not None
        assert stored.model_info_json["model_name"] == "llama-3.2-8b"
        assert stored.model_info_json["input_tokens"] == 100


# =============================================================================
# FULL FLOW TESTS
# =============================================================================


class TestFullAgentFlow:
    """End-to-end tests for agent workflows."""

    @pytest.mark.asyncio
    async def test_profile_summary_flow(
        self, identity_with_voice_config, mock_inference_client, db_session
    ):
        """Test full profile summary flow: identity -> agent -> snapshot."""
        from rediska_core.domain.models import ExternalAccount, ProfileSnapshot

        # Create target account
        account = ExternalAccount(
            provider_id="reddit",
            external_username="lead_user",
            external_user_id="t2_lead",
        )
        db_session.add(account)
        db_session.flush()

        # Load voice config from identity
        identity = identity_with_voice_config
        voice_config = VoiceConfig.from_dict(identity.voice_config_json)

        # Configure agent
        mock_inference_client.chat.return_value = ChatResponse(
            content='{"summary": "Tech enthusiast with startup experience", "interests": ["AI", "SaaS", "Investing"], "score": 92}',
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=200,
                output_tokens=80,
                latency_ms=500,
            ),
            finish_reason="stop",
        )

        config = AgentConfig(
            name="profile_summary",
            system_prompt="Analyze Reddit profiles and provide structured summaries.",
            output_schema=ProfileSummaryOutput,
        )

        harness = AgentHarness(
            config=config,
            inference_client=mock_inference_client,
            voice_config=voice_config,
        )

        # Run agent
        result = await harness.run(
            "Analyze this user based on their posts: "
            "- Posted about AI startups\n"
            "- Active in r/SaaS\n"
            "- Has 10k karma"
        )

        assert result.success
        assert result.parsed_output is not None

        # Store result in snapshot
        snapshot = ProfileSnapshot(
            account_id=account.id,
            fetched_at=datetime.utcnow(),
            summary_text=result.parsed_output["summary"],
            signals_json={"interests": result.parsed_output["interests"]},
            model_info_json=result.model_info,
        )
        db_session.add(snapshot)
        db_session.commit()

        # Verify full flow
        stored = db_session.query(ProfileSnapshot).filter_by(account_id=account.id).first()
        assert stored.summary_text == "Tech enthusiast with startup experience"
        assert "AI" in stored.signals_json["interests"]
        assert stored.model_info_json["model_name"] == "llama-3.2-8b"
