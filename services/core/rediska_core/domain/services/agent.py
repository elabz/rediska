"""Agent harness for running LLM agents.

Provides:
1. Tool allowlist - restrict which tools an agent can use
2. Structured outputs - validate outputs against Pydantic models
3. Model info recording - capture model metadata for auditing
4. Voice config injection - inject identity voice into system prompt

Usage:
    config = AgentConfig(
        name="profile_summary",
        system_prompt="You analyze user profiles.",
        output_schema=ProfileSummaryOutput,
    )

    voice = VoiceConfig.from_dict(identity.voice_config_json)

    harness = AgentHarness(
        config=config,
        inference_client=client,
        voice_config=voice,
        tools=[search_tool, analyze_tool],
    )

    result = await harness.run("Summarize this profile: ...")
    print(result.output)
    print(result.model_info)
"""

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Type

from pydantic import BaseModel, ValidationError

from rediska_core.domain.services.inference import (
    ChatMessage,
    ChatResponse,
    InferenceClient,
    ModelInfo,
)


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class VoiceConfig:
    """Voice/persona configuration for LLM-generated content.

    Loaded from identity.voice_config_json to customize agent behavior.
    """

    system_prompt: Optional[str] = None
    tone: Optional[str] = None
    style: Optional[str] = None
    persona_name: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "VoiceConfig":
        """Create VoiceConfig from a dictionary.

        Args:
            data: Dictionary with voice config fields

        Returns:
            VoiceConfig instance
        """
        if not data:
            return cls()

        return cls(
            system_prompt=data.get("system_prompt"),
            tone=data.get("tone"),
            style=data.get("style"),
            persona_name=data.get("persona_name"),
        )

    def to_system_prompt(self) -> str:
        """Generate a system prompt incorporating voice config.

        Returns:
            Combined system prompt string
        """
        parts = []

        if self.system_prompt:
            parts.append(self.system_prompt)

        if self.tone:
            parts.append(f"Maintain a {self.tone} tone in all responses.")

        if self.style:
            parts.append(f"Use a {self.style} communication style.")

        if self.persona_name:
            parts.append(f"You are {self.persona_name}.")

        return " ".join(parts)


@dataclass
class AgentConfig:
    """Configuration for an agent.

    Attributes:
        name: Agent name for logging/identification
        system_prompt: Base system prompt
        max_turns: Maximum conversation turns
        tool_allowlist: List of allowed tool names (None = all allowed)
        output_schema: Pydantic model for structured output validation
        temperature: Override inference temperature
        max_tokens: Override inference max_tokens
    """

    name: str
    system_prompt: str = ""
    max_turns: int = 10
    tool_allowlist: Optional[list[str]] = None
    output_schema: Optional[Type[BaseModel]] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


@dataclass
class AgentTool:
    """Definition of a tool available to the agent.

    Attributes:
        name: Tool name
        description: Human-readable description
        function: Async callable to execute
        parameters: JSON schema for parameters
    """

    name: str
    description: str
    function: Callable
    parameters: dict = field(default_factory=dict)

    def to_schema(self) -> dict:
        """Convert to OpenAI-compatible function schema.

        Returns:
            Function schema dictionary
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": list(self.parameters.keys()),
                },
            },
        }


@dataclass
class ToolCall:
    """Record of a tool call made by the agent.

    Attributes:
        name: Tool name
        arguments: Arguments passed to the tool
        result: Result returned by the tool
    """

    name: str
    arguments: dict
    result: Any


@dataclass
class ToolResult:
    """Result from executing a tool.

    Attributes:
        success: Whether the tool executed successfully
        output: Tool output
        error: Error message if failed
    """

    success: bool
    output: Any
    error: Optional[str] = None


@dataclass
class AgentResult:
    """Result from running an agent.

    Attributes:
        success: Whether the agent completed successfully
        output: Final output text
        parsed_output: Parsed structured output (if schema provided)
        error: Error message if failed
        model_info: Model metadata for auditing
        turns: Number of conversation turns
        tool_calls: List of tool calls made
    """

    success: bool
    output: str
    model_info: dict
    turns: int
    tool_calls: list[ToolCall]
    parsed_output: Optional[dict] = None
    error: Optional[str] = None


# =============================================================================
# AGENT HARNESS
# =============================================================================


class AgentHarness:
    """Harness for running LLM agents with tools and structured outputs.

    Features:
    - Tool allowlist for restricting available tools
    - Structured output validation with Pydantic
    - Voice config injection for personalized responses
    - Model info recording for auditing
    """

    def __init__(
        self,
        config: AgentConfig,
        inference_client: InferenceClient,
        tools: Optional[list[AgentTool]] = None,
        voice_config: Optional[VoiceConfig] = None,
    ):
        """Initialize the agent harness.

        Args:
            config: Agent configuration
            inference_client: Client for LLM inference
            tools: Available tools
            voice_config: Voice configuration for personalization
        """
        self.config = config
        self.inference_client = inference_client
        self.tools = tools or []
        self.voice_config = voice_config

    def get_allowed_tools(self) -> list[AgentTool]:
        """Get tools filtered by allowlist.

        Returns:
            List of allowed tools
        """
        if self.config.tool_allowlist is None:
            return self.tools

        return [t for t in self.tools if t.name in self.config.tool_allowlist]

    def build_system_prompt(self) -> str:
        """Build the complete system prompt with voice config.

        Returns:
            Combined system prompt
        """
        parts = []

        # Base system prompt
        if self.config.system_prompt:
            parts.append(self.config.system_prompt)

        # Voice config additions
        if self.voice_config:
            voice_prompt = self.voice_config.to_system_prompt()
            if voice_prompt:
                parts.append(voice_prompt)

        # Output format instructions if structured output required
        if self.config.output_schema:
            schema_name = self.config.output_schema.__name__
            parts.append(
                f"You must respond with valid JSON matching the {schema_name} schema. "
                "Do not include any other text, only the JSON object."
            )

        return " ".join(parts)

    def _get_tool_schemas(self) -> list[dict]:
        """Get JSON schemas for allowed tools.

        Returns:
            List of tool schema dictionaries
        """
        return [t.to_schema() for t in self.get_allowed_tools()]

    async def _execute_tool(self, name: str, arguments: dict) -> ToolResult:
        """Execute a tool by name.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            ToolResult with output or error
        """
        tool = next((t for t in self.get_allowed_tools() if t.name == name), None)

        if not tool:
            return ToolResult(
                success=False,
                output=None,
                error=f"Tool '{name}' not found or not allowed",
            )

        try:
            result = await tool.function(**arguments)
            return ToolResult(success=True, output=result)
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))

    def _parse_structured_output(self, content: str) -> tuple[bool, Optional[dict], Optional[str]]:
        """Parse and validate structured output.

        Args:
            content: Raw content string

        Returns:
            Tuple of (success, parsed_dict, error_message)
        """
        if not self.config.output_schema:
            return True, None, None

        try:
            # Try to parse JSON
            data = json.loads(content)

            # Validate against schema
            validated = self.config.output_schema.model_validate(data)
            return True, validated.model_dump(), None

        except json.JSONDecodeError as e:
            return False, None, f"Invalid JSON: {e}"
        except ValidationError as e:
            return False, None, f"Validation error: {e}"

    async def run(self, user_input: str) -> AgentResult:
        """Run the agent with user input.

        Args:
            user_input: User's input/query

        Returns:
            AgentResult with output and metadata
        """
        messages = [
            ChatMessage(role="system", content=self.build_system_prompt()),
            ChatMessage(role="user", content=user_input),
        ]

        tool_calls_made: list[ToolCall] = []
        turns = 0
        last_model_info: Optional[ModelInfo] = None

        while turns < self.config.max_turns:
            turns += 1

            # Make inference request
            response = await self.inference_client.chat(
                messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )

            last_model_info = response.model_info

            # Check if we're done (no tool calls, just content)
            if response.finish_reason == "stop":
                # Parse structured output if required
                success, parsed, error = self._parse_structured_output(response.content)

                if not success:
                    return AgentResult(
                        success=False,
                        output=response.content,
                        error=error,
                        model_info=last_model_info.to_dict() if last_model_info else {},
                        turns=turns,
                        tool_calls=tool_calls_made,
                    )

                return AgentResult(
                    success=True,
                    output=response.content,
                    parsed_output=parsed,
                    model_info=last_model_info.to_dict() if last_model_info else {},
                    turns=turns,
                    tool_calls=tool_calls_made,
                )

            # Handle tool calls if present in response
            # For now, we assume the response content is the final output
            # Full tool calling would require parsing tool_calls from response
            break

        # Max turns reached
        return AgentResult(
            success=True,
            output=response.content if response else "",
            model_info=last_model_info.to_dict() if last_model_info else {},
            turns=turns,
            tool_calls=tool_calls_made,
        )


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "AgentConfig",
    "AgentHarness",
    "AgentResult",
    "AgentTool",
    "ToolCall",
    "ToolResult",
    "VoiceConfig",
]
