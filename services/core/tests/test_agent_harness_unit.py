"""Unit tests for the agent harness.

Tests the agent runner harness which provides:
1. Tool allowlist - restrict which tools an agent can use
2. Structured outputs - validate outputs against Pydantic models
3. Model info recording - capture model metadata for auditing
4. Voice config injection - inject identity voice into system prompt
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from rediska_core.domain.services.inference import (
    ChatMessage,
    ChatResponse,
    InferenceClient,
    InferenceConfig,
    ModelInfo,
)
from rediska_core.domain.services.agent import (
    AgentConfig,
    AgentHarness,
    AgentResult,
    AgentTool,
    ToolCall,
    ToolResult,
    VoiceConfig,
)


# =============================================================================
# TEST SCHEMAS
# =============================================================================


class ProfileSummaryOutput(BaseModel):
    """Example structured output for profile summary."""

    summary: str = Field(..., description="Brief summary of the profile")
    interests: list[str] = Field(default_factory=list, description="List of interests")
    score: int = Field(..., ge=0, le=100, description="Quality score 0-100")


class LeadScoreOutput(BaseModel):
    """Example structured output for lead scoring."""

    score: int = Field(..., ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    recommended_action: str = Field(default="review")


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_inference_client():
    """Create a mock inference client."""
    client = AsyncMock(spec=InferenceClient)
    return client


@pytest.fixture
def basic_agent_config():
    """Create a basic agent configuration."""
    return AgentConfig(
        name="test_agent",
        system_prompt="You are a helpful assistant.",
        max_turns=5,
    )


@pytest.fixture
def voice_config():
    """Create a test voice configuration."""
    return VoiceConfig(
        system_prompt="You are a friendly sales representative.",
        tone="professional",
        style="conversational",
        persona_name="Alex",
    )


@pytest.fixture
def sample_tools():
    """Create sample tools for testing."""
    async def search_tool(query: str) -> str:
        return f"Search results for: {query}"

    async def calculate_tool(expression: str) -> str:
        return f"Result: {eval(expression)}"

    return [
        AgentTool(
            name="search",
            description="Search for information",
            function=search_tool,
            parameters={"query": {"type": "string", "description": "Search query"}},
        ),
        AgentTool(
            name="calculate",
            description="Calculate a math expression",
            function=calculate_tool,
            parameters={"expression": {"type": "string", "description": "Math expression"}},
        ),
    ]


# =============================================================================
# VOICE CONFIG TESTS
# =============================================================================


class TestVoiceConfig:
    """Tests for VoiceConfig dataclass."""

    def test_voice_config_fields(self):
        """VoiceConfig should store voice configuration."""
        config = VoiceConfig(
            system_prompt="You are helpful.",
            tone="friendly",
            style="casual",
            persona_name="Bot",
        )

        assert config.system_prompt == "You are helpful."
        assert config.tone == "friendly"
        assert config.style == "casual"
        assert config.persona_name == "Bot"

    def test_voice_config_from_dict(self):
        """VoiceConfig should be constructable from dict."""
        data = {
            "system_prompt": "You are an expert.",
            "tone": "professional",
            "style": "formal",
        }

        config = VoiceConfig.from_dict(data)

        assert config.system_prompt == "You are an expert."
        assert config.tone == "professional"
        assert config.style == "formal"

    def test_voice_config_from_dict_with_missing_fields(self):
        """VoiceConfig should handle missing optional fields."""
        data = {"system_prompt": "Basic prompt"}

        config = VoiceConfig.from_dict(data)

        assert config.system_prompt == "Basic prompt"
        assert config.tone is None
        assert config.style is None

    def test_voice_config_to_system_prompt(self):
        """VoiceConfig should generate a complete system prompt."""
        config = VoiceConfig(
            system_prompt="You are a sales assistant.",
            tone="professional",
            style="conversational",
            persona_name="Alex",
        )

        prompt = config.to_system_prompt()

        assert "You are a sales assistant." in prompt
        assert "professional" in prompt.lower() or "tone" in prompt.lower()

    def test_voice_config_empty(self):
        """VoiceConfig should handle empty/None values."""
        config = VoiceConfig()

        assert config.system_prompt is None
        assert config.tone is None


# =============================================================================
# AGENT CONFIG TESTS
# =============================================================================


class TestAgentConfig:
    """Tests for AgentConfig dataclass."""

    def test_agent_config_defaults(self):
        """AgentConfig should have sensible defaults."""
        config = AgentConfig(name="test")

        assert config.name == "test"
        assert config.max_turns == 10
        assert config.tool_allowlist is None  # All tools allowed
        assert config.output_schema is None

    def test_agent_config_with_tool_allowlist(self):
        """AgentConfig should support tool allowlist."""
        config = AgentConfig(
            name="restricted_agent",
            tool_allowlist=["search", "read"],
        )

        assert config.tool_allowlist == ["search", "read"]

    def test_agent_config_with_output_schema(self):
        """AgentConfig should support output schema."""
        config = AgentConfig(
            name="scoring_agent",
            output_schema=LeadScoreOutput,
        )

        assert config.output_schema == LeadScoreOutput


# =============================================================================
# AGENT TOOL TESTS
# =============================================================================


class TestAgentTool:
    """Tests for AgentTool dataclass."""

    def test_tool_definition(self):
        """AgentTool should define a callable tool."""
        async def my_tool(arg: str) -> str:
            return f"Result: {arg}"

        tool = AgentTool(
            name="my_tool",
            description="Does something useful",
            function=my_tool,
            parameters={"arg": {"type": "string"}},
        )

        assert tool.name == "my_tool"
        assert tool.description == "Does something useful"
        assert callable(tool.function)

    def test_tool_to_schema(self):
        """AgentTool should convert to JSON schema for LLM."""
        async def search(query: str) -> str:
            return query

        tool = AgentTool(
            name="search",
            description="Search for info",
            function=search,
            parameters={
                "query": {"type": "string", "description": "Search query"},
            },
        )

        schema = tool.to_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "search"
        assert schema["function"]["description"] == "Search for info"
        assert "parameters" in schema["function"]


# =============================================================================
# AGENT HARNESS INITIALIZATION TESTS
# =============================================================================


class TestAgentHarnessInit:
    """Tests for AgentHarness initialization."""

    def test_harness_creation(self, mock_inference_client, basic_agent_config):
        """AgentHarness should be creatable with config and client."""
        harness = AgentHarness(
            config=basic_agent_config,
            inference_client=mock_inference_client,
        )

        assert harness.config == basic_agent_config
        assert harness.inference_client == mock_inference_client

    def test_harness_with_tools(self, mock_inference_client, basic_agent_config, sample_tools):
        """AgentHarness should accept tools."""
        harness = AgentHarness(
            config=basic_agent_config,
            inference_client=mock_inference_client,
            tools=sample_tools,
        )

        assert len(harness.tools) == 2
        assert harness.tools[0].name == "search"

    def test_harness_with_voice_config(self, mock_inference_client, basic_agent_config, voice_config):
        """AgentHarness should accept voice config."""
        harness = AgentHarness(
            config=basic_agent_config,
            inference_client=mock_inference_client,
            voice_config=voice_config,
        )

        assert harness.voice_config == voice_config


# =============================================================================
# TOOL ALLOWLIST TESTS
# =============================================================================


class TestToolAllowlist:
    """Tests for tool allowlist functionality."""

    def test_filter_tools_with_allowlist(self, mock_inference_client, sample_tools):
        """Tools should be filtered by allowlist."""
        config = AgentConfig(
            name="restricted",
            tool_allowlist=["search"],  # Only allow search
        )

        harness = AgentHarness(
            config=config,
            inference_client=mock_inference_client,
            tools=sample_tools,
        )

        filtered = harness.get_allowed_tools()

        assert len(filtered) == 1
        assert filtered[0].name == "search"

    def test_no_allowlist_allows_all(self, mock_inference_client, sample_tools):
        """No allowlist should allow all tools."""
        config = AgentConfig(name="unrestricted")

        harness = AgentHarness(
            config=config,
            inference_client=mock_inference_client,
            tools=sample_tools,
        )

        filtered = harness.get_allowed_tools()

        assert len(filtered) == 2

    def test_empty_allowlist_blocks_all(self, mock_inference_client, sample_tools):
        """Empty allowlist should block all tools."""
        config = AgentConfig(
            name="no_tools",
            tool_allowlist=[],  # Empty list = no tools
        )

        harness = AgentHarness(
            config=config,
            inference_client=mock_inference_client,
            tools=sample_tools,
        )

        filtered = harness.get_allowed_tools()

        assert len(filtered) == 0


# =============================================================================
# VOICE CONFIG INJECTION TESTS
# =============================================================================


class TestVoiceConfigInjection:
    """Tests for voice config injection into system prompt."""

    def test_inject_voice_config(self, mock_inference_client, voice_config):
        """Voice config should be injected into system prompt."""
        config = AgentConfig(
            name="voiced_agent",
            system_prompt="Base instructions.",
        )

        harness = AgentHarness(
            config=config,
            inference_client=mock_inference_client,
            voice_config=voice_config,
        )

        system_prompt = harness.build_system_prompt()

        # Should include both base and voice config
        assert "Base instructions" in system_prompt
        assert "friendly sales representative" in system_prompt

    def test_no_voice_config_uses_base(self, mock_inference_client):
        """No voice config should use base system prompt only."""
        config = AgentConfig(
            name="basic_agent",
            system_prompt="You are a helpful assistant.",
        )

        harness = AgentHarness(
            config=config,
            inference_client=mock_inference_client,
        )

        system_prompt = harness.build_system_prompt()

        assert system_prompt == "You are a helpful assistant."

    def test_voice_config_overrides_tone(self, mock_inference_client):
        """Voice config tone should be included in prompt."""
        config = AgentConfig(
            name="toned_agent",
            system_prompt="Base prompt.",
        )
        voice = VoiceConfig(
            system_prompt="Custom voice prompt.",
            tone="enthusiastic",
        )

        harness = AgentHarness(
            config=config,
            inference_client=mock_inference_client,
            voice_config=voice,
        )

        system_prompt = harness.build_system_prompt()

        assert "enthusiastic" in system_prompt.lower()


# =============================================================================
# AGENT RUN TESTS
# =============================================================================


class TestAgentRun:
    """Tests for running the agent."""

    @pytest.mark.asyncio
    async def test_run_simple_query(self, mock_inference_client, basic_agent_config):
        """Agent should handle simple queries."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="Hello! I'm here to help.",
            model_info=ModelInfo(
                model_name="test-model",
                provider="test",
                temperature=0.7,
                max_tokens=1024,
                input_tokens=10,
                output_tokens=20,
                latency_ms=100,
            ),
            finish_reason="stop",
        )

        harness = AgentHarness(
            config=basic_agent_config,
            inference_client=mock_inference_client,
        )

        result = await harness.run("Say hello")

        assert result.success
        assert "Hello" in result.output or "help" in result.output

    @pytest.mark.asyncio
    async def test_run_returns_model_info(self, mock_inference_client, basic_agent_config):
        """Agent run should return model info for auditing."""
        mock_inference_client.chat.return_value = ChatResponse(
            content="Response",
            model_info=ModelInfo(
                model_name="llama-3.2-8b",
                provider="llama.cpp",
                temperature=0.7,
                max_tokens=1024,
                input_tokens=50,
                output_tokens=100,
                latency_ms=500,
            ),
            finish_reason="stop",
        )

        harness = AgentHarness(
            config=basic_agent_config,
            inference_client=mock_inference_client,
        )

        result = await harness.run("Test query")

        assert result.model_info is not None
        assert result.model_info["model_name"] == "llama-3.2-8b"
        assert result.model_info["input_tokens"] == 50

    @pytest.mark.asyncio
    async def test_run_respects_max_turns(self, mock_inference_client):
        """Agent should respect max_turns limit."""
        config = AgentConfig(name="limited", max_turns=2)

        # Simulate tool calls that would continue indefinitely
        mock_inference_client.chat.return_value = ChatResponse(
            content="Final response after max turns",
            model_info=ModelInfo(
                model_name="test",
                provider="test",
                temperature=0.7,
                max_tokens=1024,
                input_tokens=10,
                output_tokens=10,
                latency_ms=50,
            ),
            finish_reason="stop",
        )

        harness = AgentHarness(
            config=config,
            inference_client=mock_inference_client,
        )

        result = await harness.run("Test")

        assert result.turns <= 2


# =============================================================================
# STRUCTURED OUTPUT TESTS
# =============================================================================


class TestStructuredOutput:
    """Tests for structured output validation."""

    @pytest.mark.asyncio
    async def test_parse_structured_output(self, mock_inference_client):
        """Agent should parse and validate structured output."""
        config = AgentConfig(
            name="scoring_agent",
            output_schema=LeadScoreOutput,
        )

        mock_inference_client.chat.return_value = ChatResponse(
            content='{"score": 85, "reasons": ["Good karma", "Active user"], "recommended_action": "contact"}',
            model_info=ModelInfo(
                model_name="test",
                provider="test",
                temperature=0.7,
                max_tokens=1024,
                input_tokens=10,
                output_tokens=20,
                latency_ms=100,
            ),
            finish_reason="stop",
        )

        harness = AgentHarness(
            config=config,
            inference_client=mock_inference_client,
        )

        result = await harness.run("Score this lead")

        assert result.success
        assert result.parsed_output is not None
        assert result.parsed_output["score"] == 85
        assert len(result.parsed_output["reasons"]) == 2

    @pytest.mark.asyncio
    async def test_structured_output_validation_error(self, mock_inference_client):
        """Agent should handle invalid structured output."""
        config = AgentConfig(
            name="scoring_agent",
            output_schema=LeadScoreOutput,
        )

        mock_inference_client.chat.return_value = ChatResponse(
            content='{"invalid": "output"}',  # Missing required fields
            model_info=ModelInfo(
                model_name="test",
                provider="test",
                temperature=0.7,
                max_tokens=1024,
                input_tokens=10,
                output_tokens=10,
                latency_ms=100,
            ),
            finish_reason="stop",
        )

        harness = AgentHarness(
            config=config,
            inference_client=mock_inference_client,
        )

        result = await harness.run("Score this lead")

        # Should indicate validation failure
        assert not result.success or result.error is not None


# =============================================================================
# AGENT RESULT TESTS
# =============================================================================


class TestAgentResult:
    """Tests for AgentResult dataclass."""

    def test_agent_result_success(self):
        """AgentResult should represent successful execution."""
        result = AgentResult(
            success=True,
            output="Generated response",
            model_info={"model_name": "test"},
            turns=1,
            tool_calls=[],
        )

        assert result.success
        assert result.output == "Generated response"
        assert result.error is None

    def test_agent_result_failure(self):
        """AgentResult should represent failed execution."""
        result = AgentResult(
            success=False,
            output="",
            error="Validation failed",
            model_info={"model_name": "test"},
            turns=1,
            tool_calls=[],
        )

        assert not result.success
        assert result.error == "Validation failed"

    def test_agent_result_with_tool_calls(self):
        """AgentResult should record tool calls."""
        result = AgentResult(
            success=True,
            output="Final response",
            model_info={"model_name": "test"},
            turns=2,
            tool_calls=[
                ToolCall(name="search", arguments={"query": "test"}, result="found"),
            ],
        )

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "search"
