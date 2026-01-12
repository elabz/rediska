"""Unit tests for the profile summary agent.

Tests the agent that analyzes user profiles and generates:
1. Summary text - Brief description of the user
2. Signals - Extracted structured data (interests, activity patterns, etc.)
3. Risk flags - Any red flags or concerns
4. Citations - References to source content
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, Field

from rediska_core.domain.models import ExternalAccount, ProfileItem, ProfileSnapshot
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
from rediska_core.domain.services.profile_summary import (
    Citation,
    ProfileSummaryAgent,
    ProfileSummaryInput,
    ProfileSummaryOutput,
    ProfileSummaryService,
    RiskFlag,
    Signal,
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
def sample_profile_items():
    """Create sample profile items for testing."""
    return [
        {
            "id": 1,
            "item_type": "post",
            "external_item_id": "post_1",
            "text_content": "Just launched my new SaaS startup! Excited to share our journey in the AI space.",
            "item_created_at": datetime(2024, 1, 15, tzinfo=timezone.utc),
        },
        {
            "id": 2,
            "item_type": "post",
            "external_item_id": "post_2",
            "text_content": "Looking for beta testers for our productivity tool. DM if interested!",
            "item_created_at": datetime(2024, 1, 20, tzinfo=timezone.utc),
        },
        {
            "id": 3,
            "item_type": "comment",
            "external_item_id": "comment_1",
            "text_content": "Great point about market validation. We spent 3 months talking to customers before building.",
            "item_created_at": datetime(2024, 1, 18, tzinfo=timezone.utc),
        },
        {
            "id": 4,
            "item_type": "comment",
            "external_item_id": "comment_2",
            "text_content": "Been using React for 5 years now, highly recommend it for this use case.",
            "item_created_at": datetime(2024, 1, 22, tzinfo=timezone.utc),
        },
    ]


@pytest.fixture
def sample_account_metadata():
    """Create sample account metadata."""
    return {
        "username": "startup_founder",
        "provider_id": "reddit",
        "account_age_days": 365,
        "total_karma": 5000,
        "post_count": 50,
        "comment_count": 200,
    }


# =============================================================================
# PROFILE SUMMARY OUTPUT TESTS
# =============================================================================


class TestProfileSummaryOutput:
    """Tests for ProfileSummaryOutput schema."""

    def test_output_schema_fields(self):
        """Output should have all required fields."""
        output = ProfileSummaryOutput(
            summary="Active startup founder in the AI/SaaS space.",
            signals=[
                Signal(name="industry", value="AI/SaaS", confidence=0.9),
                Signal(name="role", value="founder", confidence=0.95),
            ],
            risk_flags=[],
            citations=[
                Citation(item_id=1, quote="launched my new SaaS startup", relevance="role"),
            ],
        )

        assert output.summary == "Active startup founder in the AI/SaaS space."
        assert len(output.signals) == 2
        assert len(output.risk_flags) == 0
        assert len(output.citations) == 1

    def test_signal_structure(self):
        """Signal should capture structured data points."""
        signal = Signal(
            name="interests",
            value=["AI", "startups", "React"],
            confidence=0.85,
        )

        assert signal.name == "interests"
        assert "AI" in signal.value
        assert signal.confidence == 0.85

    def test_risk_flag_structure(self):
        """RiskFlag should capture potential concerns."""
        flag = RiskFlag(
            type="spam_behavior",
            severity="medium",
            description="Multiple promotional posts in short timeframe",
            evidence_item_ids=[1, 2],
        )

        assert flag.type == "spam_behavior"
        assert flag.severity == "medium"
        assert len(flag.evidence_item_ids) == 2

    def test_citation_structure(self):
        """Citation should reference source content."""
        citation = Citation(
            item_id=1,
            quote="launched my new SaaS startup",
            relevance="industry identification",
        )

        assert citation.item_id == 1
        assert "SaaS" in citation.quote

    def test_output_to_storage_format(self):
        """Output should convert to format suitable for profile_snapshots."""
        output = ProfileSummaryOutput(
            summary="Test summary",
            signals=[Signal(name="test", value="value", confidence=0.9)],
            risk_flags=[RiskFlag(type="test", severity="low", description="test")],
            citations=[Citation(item_id=1, quote="test", relevance="test")],
        )

        storage = output.to_storage_format()

        assert storage["summary_text"] == "Test summary"
        assert "signals_json" in storage
        assert "risk_flags_json" in storage
        assert isinstance(storage["signals_json"], list)


# =============================================================================
# PROFILE SUMMARY INPUT TESTS
# =============================================================================


class TestProfileSummaryInput:
    """Tests for ProfileSummaryInput."""

    def test_input_from_items_and_metadata(
        self, sample_profile_items, sample_account_metadata
    ):
        """Input should combine items and metadata."""
        input_data = ProfileSummaryInput(
            account_metadata=sample_account_metadata,
            profile_items=sample_profile_items,
        )

        assert input_data.account_metadata["username"] == "startup_founder"
        assert len(input_data.profile_items) == 4

    def test_input_to_prompt(self, sample_profile_items, sample_account_metadata):
        """Input should generate a prompt for the agent."""
        input_data = ProfileSummaryInput(
            account_metadata=sample_account_metadata,
            profile_items=sample_profile_items,
        )

        prompt = input_data.to_prompt()

        assert "startup_founder" in prompt
        assert "SaaS startup" in prompt
        assert "post" in prompt.lower()
        assert "comment" in prompt.lower()

    def test_input_truncates_long_content(self):
        """Input should truncate very long content."""
        long_items = [
            {
                "id": 1,
                "item_type": "post",
                "external_item_id": "post_1",
                "text_content": "x" * 10000,  # Very long content
                "item_created_at": datetime.now(timezone.utc),
            }
        ]

        input_data = ProfileSummaryInput(
            account_metadata={"username": "test"},
            profile_items=long_items,
            max_content_length=1000,
        )

        prompt = input_data.to_prompt()

        # Should be truncated
        assert len(prompt) < 15000


# =============================================================================
# PROFILE SUMMARY AGENT TESTS
# =============================================================================


class TestProfileSummaryAgent:
    """Tests for ProfileSummaryAgent."""

    @pytest.mark.asyncio
    async def test_agent_generates_summary(
        self, mock_inference_client, sample_profile_items, sample_account_metadata
    ):
        """Agent should generate a profile summary."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "summary": "Active startup founder focused on AI/SaaS products.",
                "signals": [
                    {"name": "industry", "value": "AI/SaaS", "confidence": 0.9},
                    {"name": "role", "value": "founder", "confidence": 0.95}
                ],
                "risk_flags": [],
                "citations": [
                    {"item_id": 1, "quote": "launched my new SaaS startup", "relevance": "role identification"}
                ]
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=500,
                output_tokens=150,
                latency_ms=800,
            ),
            finish_reason="stop",
        )

        agent = ProfileSummaryAgent(inference_client=mock_inference_client)

        input_data = ProfileSummaryInput(
            account_metadata=sample_account_metadata,
            profile_items=sample_profile_items,
        )

        result = await agent.analyze(input_data)

        assert result.success
        assert result.output is not None
        assert "founder" in result.output.summary.lower()
        assert len(result.output.signals) >= 1

    @pytest.mark.asyncio
    async def test_agent_extracts_signals(
        self, mock_inference_client, sample_profile_items, sample_account_metadata
    ):
        """Agent should extract structured signals."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "summary": "Tech-savvy startup founder.",
                "signals": [
                    {"name": "interests", "value": ["AI", "React", "startups"], "confidence": 0.85},
                    {"name": "experience_years", "value": 5, "confidence": 0.8},
                    {"name": "looking_for", "value": "beta testers", "confidence": 0.9}
                ],
                "risk_flags": [],
                "citations": []
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=500,
                output_tokens=100,
                latency_ms=600,
            ),
            finish_reason="stop",
        )

        agent = ProfileSummaryAgent(inference_client=mock_inference_client)

        input_data = ProfileSummaryInput(
            account_metadata=sample_account_metadata,
            profile_items=sample_profile_items,
        )

        result = await agent.analyze(input_data)

        assert result.success
        signals = result.output.signals
        signal_names = [s.name for s in signals]
        assert "interests" in signal_names

    @pytest.mark.asyncio
    async def test_agent_identifies_risk_flags(self, mock_inference_client):
        """Agent should identify potential risk flags."""
        # Suspicious profile items
        suspicious_items = [
            {
                "id": 1,
                "item_type": "post",
                "external_item_id": "post_1",
                "text_content": "BUY NOW! Limited time offer! Click here for FREE money!",
                "item_created_at": datetime.now(timezone.utc),
            },
            {
                "id": 2,
                "item_type": "post",
                "external_item_id": "post_2",
                "text_content": "AMAZING opportunity! Don't miss out! DM me NOW!",
                "item_created_at": datetime.now(timezone.utc),
            },
        ]

        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "summary": "Account showing spam-like behavior patterns.",
                "signals": [],
                "risk_flags": [
                    {
                        "type": "spam_behavior",
                        "severity": "high",
                        "description": "Multiple posts with promotional language and urgency tactics",
                        "evidence_item_ids": [1, 2]
                    }
                ],
                "citations": [
                    {"item_id": 1, "quote": "BUY NOW! Limited time offer!", "relevance": "spam indicator"}
                ]
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=300,
                output_tokens=120,
                latency_ms=500,
            ),
            finish_reason="stop",
        )

        agent = ProfileSummaryAgent(inference_client=mock_inference_client)

        input_data = ProfileSummaryInput(
            account_metadata={"username": "spammer123"},
            profile_items=suspicious_items,
        )

        result = await agent.analyze(input_data)

        assert result.success
        assert len(result.output.risk_flags) > 0
        assert result.output.risk_flags[0].type == "spam_behavior"
        assert result.output.risk_flags[0].severity == "high"

    @pytest.mark.asyncio
    async def test_agent_includes_citations(
        self, mock_inference_client, sample_profile_items, sample_account_metadata
    ):
        """Agent should include citations with evidence."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "summary": "Experienced React developer launching a SaaS startup.",
                "signals": [
                    {"name": "tech_stack", "value": ["React"], "confidence": 0.95}
                ],
                "risk_flags": [],
                "citations": [
                    {"item_id": 4, "quote": "Been using React for 5 years", "relevance": "technical experience"},
                    {"item_id": 1, "quote": "launched my new SaaS startup", "relevance": "current venture"}
                ]
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=500,
                output_tokens=100,
                latency_ms=700,
            ),
            finish_reason="stop",
        )

        agent = ProfileSummaryAgent(inference_client=mock_inference_client)

        input_data = ProfileSummaryInput(
            account_metadata=sample_account_metadata,
            profile_items=sample_profile_items,
        )

        result = await agent.analyze(input_data)

        assert result.success
        assert len(result.output.citations) >= 2
        # Citations should reference actual item IDs
        citation_ids = [c.item_id for c in result.output.citations]
        assert 4 in citation_ids or 1 in citation_ids

    @pytest.mark.asyncio
    async def test_agent_returns_model_info(
        self, mock_inference_client, sample_profile_items, sample_account_metadata
    ):
        """Agent should return model info for auditing."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "summary": "Test summary",
                "signals": [],
                "risk_flags": [],
                "citations": []
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=500,
                output_tokens=50,
                latency_ms=400,
            ),
            finish_reason="stop",
        )

        agent = ProfileSummaryAgent(inference_client=mock_inference_client)

        input_data = ProfileSummaryInput(
            account_metadata=sample_account_metadata,
            profile_items=sample_profile_items,
        )

        result = await agent.analyze(input_data)

        assert result.model_info is not None
        assert result.model_info["model_name"] == "llama-3.2-8b"
        assert result.model_info["input_tokens"] == 500


# =============================================================================
# AGENT ERROR HANDLING TESTS
# =============================================================================


class TestProfileSummaryAgentErrors:
    """Tests for error handling in ProfileSummaryAgent."""

    @pytest.mark.asyncio
    async def test_agent_handles_invalid_json(self, mock_inference_client):
        """Agent should handle invalid JSON response."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="This is not valid JSON",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=100,
                output_tokens=20,
                latency_ms=200,
            ),
            finish_reason="stop",
        )

        agent = ProfileSummaryAgent(inference_client=mock_inference_client)

        input_data = ProfileSummaryInput(
            account_metadata={"username": "test"},
            profile_items=[],
        )

        result = await agent.analyze(input_data)

        assert not result.success
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_agent_handles_missing_fields(self, mock_inference_client):
        """Agent should handle response missing required fields."""
        mock_inference_client.chat.return_value = ChatResponse(
            content='{"summary": "Test"}',  # Missing signals, risk_flags, citations
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=100,
                output_tokens=10,
                latency_ms=150,
            ),
            finish_reason="stop",
        )

        agent = ProfileSummaryAgent(inference_client=mock_inference_client)

        input_data = ProfileSummaryInput(
            account_metadata={"username": "test"},
            profile_items=[],
        )

        result = await agent.analyze(input_data)

        # Should either fail validation or use defaults
        # The implementation can choose either approach
        assert result is not None

    @pytest.mark.asyncio
    async def test_agent_handles_empty_items(self, mock_inference_client):
        """Agent should handle empty profile items."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="""{
                "summary": "New account with no public activity.",
                "signals": [
                    {"name": "activity_level", "value": "none", "confidence": 1.0}
                ],
                "risk_flags": [
                    {"type": "new_account", "severity": "low", "description": "Account has no public posts"}
                ],
                "citations": []
            }""",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=2048,
                input_tokens=50,
                output_tokens=80,
                latency_ms=300,
            ),
            finish_reason="stop",
        )

        agent = ProfileSummaryAgent(inference_client=mock_inference_client)

        input_data = ProfileSummaryInput(
            account_metadata={"username": "new_user"},
            profile_items=[],
        )

        result = await agent.analyze(input_data)

        assert result.success
        assert "no" in result.output.summary.lower() or "new" in result.output.summary.lower()


# =============================================================================
# SYSTEM PROMPT TESTS
# =============================================================================


class TestProfileSummarySystemPrompt:
    """Tests for the profile summary system prompt."""

    def test_system_prompt_includes_instructions(self):
        """System prompt should include analysis instructions."""
        agent = ProfileSummaryAgent(inference_client=AsyncMock())

        prompt = agent.get_system_prompt()

        assert "summary" in prompt.lower()
        assert "signal" in prompt.lower()
        assert "risk" in prompt.lower() or "flag" in prompt.lower()
        assert "citation" in prompt.lower() or "evidence" in prompt.lower()

    def test_system_prompt_specifies_output_format(self):
        """System prompt should specify JSON output format."""
        agent = ProfileSummaryAgent(inference_client=AsyncMock())

        prompt = agent.get_system_prompt()

        assert "json" in prompt.lower()
