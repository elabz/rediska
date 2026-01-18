"""Inference client for LLM operations.

Provides a wrapper for llama.cpp or compatible inference servers.
Supports both chat and completion modes.

Usage:
    config = InferenceConfig(base_url="http://localhost:8080")
    client = InferenceClient(config=config)

    messages = [
        ChatMessage(role="system", content="You are helpful."),
        ChatMessage(role="user", content="Hello!"),
    ]

    response = await client.chat(messages)
    print(response.content)
    print(response.model_info.to_dict())
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


# =============================================================================
# EXCEPTIONS
# =============================================================================


class InferenceError(Exception):
    """Base exception for inference errors."""

    pass


class ConnectionInferenceError(InferenceError):
    """Connection error during inference."""

    pass


class TimeoutInferenceError(InferenceError):
    """Timeout during inference."""

    pass


class ResponseInferenceError(InferenceError):
    """Invalid or malformed response from inference server."""

    pass


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class InferenceConfig:
    """Configuration for the inference client.

    Attributes:
        base_url: URL of the inference server (e.g., http://localhost:8080)
        model_name: Name of the model to use
        timeout: Request timeout in seconds
        max_tokens: Maximum tokens to generate
        temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative)
        api_key: Optional API key for authentication
    """

    base_url: str
    model_name: str = "default"
    timeout: float = 60.0
    max_tokens: int = 2048  # Default for standard models; increase for reasoning models with <think> tags
    temperature: float = 0.6  # Lower temperature for more consistent JSON output
    api_key: Optional[str] = None


@dataclass
class ChatMessage:
    """A message in a chat conversation.

    Attributes:
        role: The role (system, user, assistant)
        content: The message content
    """

    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class ModelInfo:
    """Information about the model and inference run.

    Used for auditing and debugging.
    """

    model_name: str
    provider: str
    temperature: float
    max_tokens: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON storage."""
        return {
            "model_name": self.model_name,
            "provider": self.provider,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            **self.extra,
        }


@dataclass
class ChatResponse:
    """Response from a chat request.

    Attributes:
        content: The generated text content
        model_info: Information about the model and run
        finish_reason: Why generation stopped (stop, length, etc.)
        parsed_output: Optional parsed structured output
    """

    content: str
    model_info: ModelInfo
    finish_reason: str
    parsed_output: Optional[dict] = None


# =============================================================================
# INFERENCE CLIENT
# =============================================================================


class InferenceClient:
    """Client for LLM inference operations.

    Wraps llama.cpp server or compatible OpenAI-style API.
    Supports both chat and completion modes.
    """

    def __init__(self, config: InferenceConfig):
        """Initialize the inference client.

        Args:
            config: Inference configuration.
        """
        self.config = config
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._http_client is None:
            headers = {}
            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
            self._http_client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                headers=headers,
            )
        return self._http_client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def _make_request(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> dict:
        """Make a chat completion request to the server.

        Args:
            messages: List of message dicts with role and content
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Returns:
            Response dict from the server

        Raises:
            InferenceError: On connection, timeout, or response errors
        """
        client = await self._get_http_client()

        payload = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Log full prompts for debugging
        logger.info(f"=== LLM REQUEST to {self.config.base_url} ===")
        logger.info(f"Model: {self.config.model_name}, temp: {temperature}, max_tokens: {max_tokens}")
        logger.info(f"Messages count: {len(messages)}")
        for i, msg in enumerate(messages):
            role = msg.get('role', 'unknown') if isinstance(msg, dict) else getattr(msg, 'role', 'unknown')
            content = msg.get('content', '') if isinstance(msg, dict) else getattr(msg, 'content', '')
            logger.info(f"--- MESSAGE {i} ({role.upper()}) ---")
            # Log content in chunks to avoid truncation
            if content:
                for j in range(0, len(content), 2000):
                    logger.info(content[j:j+2000])
            else:
                logger.info("(empty content)")
        logger.info("=== END LLM REQUEST ===")

        try:
            response = await client.post("/v1/chat/completions", json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            raise ConnectionInferenceError(f"Connection error: {e}") from e
        except httpx.TimeoutException as e:
            raise TimeoutInferenceError(f"Timeout error: {e}") from e
        except httpx.HTTPStatusError as e:
            raise InferenceError(f"HTTP error: {e}") from e

    async def _make_completion_request(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        """Make a completion request to the server.

        Args:
            prompt: The prompt text
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Returns:
            Response dict from the server
        """
        client = await self._get_http_client()

        payload = {
            "model": self.config.model_name,
            "prompt": prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            response = await client.post("/v1/completions", json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            raise ConnectionInferenceError(f"Connection error: {e}") from e
        except httpx.TimeoutException as e:
            raise TimeoutInferenceError(f"Timeout error: {e}") from e
        except httpx.HTTPStatusError as e:
            raise InferenceError(f"HTTP error: {e}") from e

    async def chat(
        self,
        messages: list[ChatMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> ChatResponse:
        """Send a chat request to the LLM.

        Args:
            messages: List of ChatMessage objects
            temperature: Override default temperature
            max_tokens: Override default max_tokens

        Returns:
            ChatResponse with content and model info

        Raises:
            InferenceError: On errors during inference
        """
        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens if max_tokens is not None else self.config.max_tokens

        # Convert messages to dict format
        message_dicts = [{"role": m.role, "content": m.content} for m in messages]

        # Track timing
        start_time = time.monotonic()

        try:
            response_data = await self._make_request(
                messages=message_dicts,
                temperature=temp,
                max_tokens=tokens,
            )
        except ConnectionError as e:
            raise ConnectionInferenceError(f"Connection error: {e}") from e
        except asyncio.TimeoutError as e:
            raise TimeoutInferenceError(f"Timeout error: {e}") from e

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Check for error response from LLM server
        if "error" in response_data:
            error_info = response_data["error"]
            if isinstance(error_info, dict):
                error_msg = error_info.get("message", str(error_info))
            else:
                error_msg = str(error_info)
            logger.error(f"LLM server returned error: {error_msg}")
            raise ResponseInferenceError(f"LLM server error: {error_msg}")

        # Parse response
        try:
            choices = response_data.get("choices", [])
            if not choices:
                logger.error(f"Invalid LLM response - no choices. Response: {response_data}")
                raise ResponseInferenceError("Invalid response: no choices")

            choice = choices[0]
            message = choice.get("message", {})
            content = message.get("content", "")
            finish_reason = choice.get("finish_reason", "unknown")

            usage = response_data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

        except (KeyError, IndexError, TypeError) as e:
            raise ResponseInferenceError(f"Invalid response format: {e}") from e

        model_info = ModelInfo(
            model_name=self.config.model_name,
            provider="llama.cpp",
            temperature=temp,
            max_tokens=tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=elapsed_ms,
        )

        return ChatResponse(
            content=content,
            model_info=model_info,
            finish_reason=finish_reason,
        )

    async def complete(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> ChatResponse:
        """Send a completion request to the LLM.

        Args:
            prompt: The prompt text
            temperature: Override default temperature
            max_tokens: Override default max_tokens

        Returns:
            ChatResponse with content and model info

        Raises:
            InferenceError: On errors during inference
        """
        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens if max_tokens is not None else self.config.max_tokens

        start_time = time.monotonic()

        try:
            response_data = await self._make_completion_request(
                prompt=prompt,
                temperature=temp,
                max_tokens=tokens,
            )
        except ConnectionError as e:
            raise ConnectionInferenceError(f"Connection error: {e}") from e
        except asyncio.TimeoutError as e:
            raise TimeoutInferenceError(f"Timeout error: {e}") from e

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Check for error response from LLM server
        if "error" in response_data:
            error_info = response_data["error"]
            if isinstance(error_info, dict):
                error_msg = error_info.get("message", str(error_info))
            else:
                error_msg = str(error_info)
            logger.error(f"LLM server returned error: {error_msg}")
            raise ResponseInferenceError(f"LLM server error: {error_msg}")

        # Parse response
        try:
            choices = response_data.get("choices", [])
            if not choices:
                logger.error(f"Invalid LLM response - no choices. Response: {response_data}")
                raise ResponseInferenceError("Invalid response: no choices")

            choice = choices[0]
            content = choice.get("text", "")
            finish_reason = choice.get("finish_reason", "unknown")

            usage = response_data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

        except (KeyError, IndexError, TypeError) as e:
            raise ResponseInferenceError(f"Invalid response format: {e}") from e

        model_info = ModelInfo(
            model_name=self.config.model_name,
            provider="llama.cpp",
            temperature=temp,
            max_tokens=tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=elapsed_ms,
        )

        return ChatResponse(
            content=content,
            model_info=model_info,
            finish_reason=finish_reason,
        )


# =============================================================================
# FACTORY FUNCTION
# =============================================================================


def get_inference_client() -> InferenceClient:
    """Create a properly configured InferenceClient from settings.

    This is the recommended way to get an InferenceClient instance.
    It ensures all parts of the system use the same configuration
    and API credentials.

    Returns:
        InferenceClient: Configured client ready for LLM requests.

    Raises:
        RuntimeError: If inference_url is not configured.

    Example:
        client = get_inference_client()
        response = await client.chat(messages)
    """
    from rediska_core.config import get_settings

    settings = get_settings()

    if not settings.inference_url:
        raise RuntimeError("INFERENCE_URL not configured")

    config = InferenceConfig(
        base_url=settings.inference_url,
        model_name=settings.inference_model or "default",
        timeout=settings.inference_timeout,
        api_key=settings.inference_api_key,
    )

    return InferenceClient(config=config)


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "InferenceClient",
    "InferenceConfig",
    "ChatMessage",
    "ChatResponse",
    "ModelInfo",
    "InferenceError",
    "ConnectionInferenceError",
    "TimeoutInferenceError",
    "ResponseInferenceError",
    "get_inference_client",
]
