"""Unit tests for the inference client.

Tests the LLM inference wrapper for chat/completion operations.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rediska_core.domain.services.inference import (
    ChatMessage,
    ChatResponse,
    InferenceClient,
    InferenceConfig,
    ModelInfo,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def inference_config():
    """Create a test inference configuration."""
    return InferenceConfig(
        base_url="http://localhost:8080",
        model_name="llama-3.2-8b",
        timeout=30.0,
        max_tokens=1024,
        temperature=0.7,
    )


@pytest.fixture
def mock_http_client():
    """Create a mock HTTP client."""
    return AsyncMock()


# =============================================================================
# INFERENCE CONFIG TESTS
# =============================================================================


class TestInferenceConfig:
    """Tests for InferenceConfig dataclass."""

    def test_config_with_defaults(self):
        """Config should have sensible defaults."""
        config = InferenceConfig(base_url="http://localhost:8080")

        assert config.base_url == "http://localhost:8080"
        assert config.model_name == "default"
        assert config.timeout == 60.0
        assert config.max_tokens == 2048
        # Deliberately below the usual 0.7 for more consistent JSON output.
        assert config.temperature == 0.6


# =============================================================================
# MODEL INFO TESTS
# =============================================================================


class TestModelInfo:
    """Tests for ModelInfo serialization."""

    def test_model_info_to_dict(self):
        """to_dict() should emit the audit fields and flatten `extra` alongside them."""
        info = ModelInfo(
            model_name="llama-3.2-8b",
            provider="llama.cpp",
            temperature=0.7,
            max_tokens=1024,
            input_tokens=100,
            output_tokens=50,
            latency_ms=1500,
            extra={"chat_template": "llama3"},
        )

        data = info.to_dict()

        assert data == {
            "model_name": "llama-3.2-8b",
            "provider": "llama.cpp",
            "temperature": 0.7,
            "max_tokens": 1024,
            "input_tokens": 100,
            "output_tokens": 50,
            "latency_ms": 1500,
            # `extra` is spread flat, not nested under an "extra" key.
            "chat_template": "llama3",
        }


# =============================================================================
# INFERENCE CLIENT TESTS
# =============================================================================


class TestInferenceClient:
    """Tests for InferenceClient."""

    @pytest.mark.asyncio
    async def test_chat_sends_messages(self, inference_config):
        """chat() should send messages to the LLM endpoint."""
        client = InferenceClient(config=inference_config)

        with patch.object(client, "_make_request") as mock_request:
            mock_request.return_value = {
                "choices": [
                    {
                        "message": {"content": "Hello!"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                },
            }

            messages = [
                ChatMessage(role="user", content="Hi!"),
            ]

            response = await client.chat(messages)

            assert response.content == "Hello!"
            assert response.finish_reason == "stop"
            mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_includes_system_prompt(self, inference_config):
        """chat() should include system prompt in messages."""
        client = InferenceClient(config=inference_config)

        with patch.object(client, "_make_request") as mock_request:
            mock_request.return_value = {
                "choices": [
                    {
                        "message": {"content": "Response"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            }

            messages = [
                ChatMessage(role="system", content="You are helpful."),
                ChatMessage(role="user", content="Hi!"),
            ]

            await client.chat(messages)

            # Verify the request included both messages
            call_args = mock_request.call_args
            request_messages = call_args[1]["messages"]
            assert len(request_messages) == 2
            assert request_messages[0]["role"] == "system"
            assert request_messages[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_chat_returns_model_info(self, inference_config):
        """chat() should return model info for auditing."""
        client = InferenceClient(config=inference_config)

        with patch.object(client, "_make_request") as mock_request:
            mock_request.return_value = {
                "choices": [
                    {
                        "message": {"content": "Response"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 15, "completion_tokens": 8},
            }

            messages = [ChatMessage(role="user", content="Hi!")]

            response = await client.chat(messages)

            assert response.model_info is not None
            assert response.model_info.model_name == "llama-3.2-8b"
            assert response.model_info.input_tokens == 15
            assert response.model_info.output_tokens == 8

    @pytest.mark.asyncio
    async def test_chat_with_custom_temperature(self, inference_config):
        """chat() should allow custom temperature override."""
        client = InferenceClient(config=inference_config)

        with patch.object(client, "_make_request") as mock_request:
            mock_request.return_value = {
                "choices": [{"message": {"content": "Response"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

            messages = [ChatMessage(role="user", content="Hi!")]

            await client.chat(messages, temperature=0.2)

            call_args = mock_request.call_args
            assert call_args[1]["temperature"] == 0.2

    @pytest.mark.asyncio
    async def test_chat_with_max_tokens_override(self, inference_config):
        """chat() should allow max_tokens override."""
        client = InferenceClient(config=inference_config)

        with patch.object(client, "_make_request") as mock_request:
            mock_request.return_value = {
                "choices": [{"message": {"content": "Response"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

            messages = [ChatMessage(role="user", content="Hi!")]

            await client.chat(messages, max_tokens=512)

            call_args = mock_request.call_args
            assert call_args[1]["max_tokens"] == 512

    @pytest.mark.asyncio
    async def test_chat_tracks_latency(self, inference_config):
        """chat() should measure the elapsed request time in milliseconds."""
        client = InferenceClient(config=inference_config)

        # Drive the clock so the measured latency is exact, not merely non-negative:
        # chat() reads monotonic() once before and once after the request.
        # 1.5s is exactly representable in binary float, so int() truncation is stable.
        clock = iter([100.0, 101.5])

        with patch.object(client, "_make_request") as mock_request, patch(
            "rediska_core.domain.services.inference.time.monotonic",
            side_effect=lambda: next(clock),
        ):
            mock_request.return_value = {
                "choices": [{"message": {"content": "Response"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

            messages = [ChatMessage(role="user", content="Hi!")]

            response = await client.chat(messages)

        assert response.model_info.latency_ms == 1500


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


class TestInferenceClientErrors:
    """Tests for error handling in InferenceClient."""

    @pytest.mark.asyncio
    async def test_chat_handles_connection_error(self, inference_config):
        """chat() should handle connection errors gracefully."""
        from rediska_core.domain.services.inference import InferenceError

        client = InferenceClient(config=inference_config)

        with patch.object(client, "_make_request") as mock_request:
            mock_request.side_effect = ConnectionError("Cannot connect")

            messages = [ChatMessage(role="user", content="Hi!")]

            with pytest.raises(InferenceError) as exc_info:
                await client.chat(messages)

            assert "connection" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_chat_handles_timeout(self, inference_config):
        """chat() should handle timeout errors."""
        from rediska_core.domain.services.inference import InferenceError

        client = InferenceClient(config=inference_config)

        with patch.object(client, "_make_request") as mock_request:
            import asyncio
            mock_request.side_effect = asyncio.TimeoutError()

            messages = [ChatMessage(role="user", content="Hi!")]

            with pytest.raises(InferenceError) as exc_info:
                await client.chat(messages)

            assert "timeout" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_chat_handles_invalid_response(self, inference_config):
        """chat() should handle malformed responses."""
        from rediska_core.domain.services.inference import InferenceError

        client = InferenceClient(config=inference_config)

        with patch.object(client, "_make_request") as mock_request:
            mock_request.return_value = {"invalid": "response"}

            messages = [ChatMessage(role="user", content="Hi!")]

            with pytest.raises(InferenceError) as exc_info:
                await client.chat(messages)

            assert "response" in str(exc_info.value).lower()


# =============================================================================
# COMPLETION TESTS
# =============================================================================


class TestInferenceClientCompletion:
    """Tests for completion (non-chat) mode."""

    @pytest.mark.asyncio
    async def test_complete_sends_prompt(self, inference_config):
        """complete() should send a prompt for completion."""
        client = InferenceClient(config=inference_config)

        with patch.object(client, "_make_completion_request") as mock_request:
            mock_request.return_value = {
                "choices": [{"text": "completed text", "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 15},
            }

            response = await client.complete("Once upon a time")

            assert response.content == "completed text"
            mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_returns_model_info(self, inference_config):
        """complete() should return model info."""
        client = InferenceClient(config=inference_config)

        with patch.object(client, "_make_completion_request") as mock_request:
            mock_request.return_value = {
                "choices": [{"text": "completed", "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10},
            }

            response = await client.complete("Test prompt")

            assert response.model_info.input_tokens == 5
            assert response.model_info.output_tokens == 10
