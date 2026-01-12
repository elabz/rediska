"""Unit tests for Redis rate limiter.

These tests follow TDD - written BEFORE implementation.
Tests cover:
- Token bucket rate limiting
- Inflight concurrency limiting
- Combined rate + concurrency limiting
- Backoff strategy for 429/5xx errors
"""

import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rediska_core.infrastructure.rate_limiter import (
    BackoffStrategy,
    RateLimiter,
    RateLimitConfig,
    RateLimitExceeded,
)


class MockPipeline:
    """Mock Redis pipeline that supports chaining and async execute."""

    def set(self, key, value):
        return self

    def delete(self, *keys):
        return self

    def expire(self, key, seconds):
        return self

    async def execute(self):
        return [True, True, True]


@pytest.fixture
def mock_async_redis():
    """Create a mock async Redis client for testing."""
    mock = MagicMock()

    # Async methods need to be AsyncMock
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.incr = AsyncMock(return_value=1)
    mock.decr = AsyncMock(return_value=0)
    mock.delete = AsyncMock(return_value=1)
    mock.expire = AsyncMock(return_value=True)

    # pipeline() is sync and returns a pipeline object
    mock.pipeline = MagicMock(return_value=MockPipeline())

    return mock


class TestRateLimitConfig:
    """Tests for rate limit configuration."""

    def test_config_defaults(self):
        """Test that config has sensible defaults."""
        config = RateLimitConfig(provider_id="reddit")

        assert config.provider_id == "reddit"
        assert config.requests_per_minute > 0
        assert config.max_concurrent > 0
        assert config.bucket_size >= config.requests_per_minute

    def test_config_custom_values(self):
        """Test config with custom values."""
        config = RateLimitConfig(
            provider_id="reddit",
            requests_per_minute=60,
            max_concurrent=5,
            bucket_size=100,
        )

        assert config.requests_per_minute == 60
        assert config.max_concurrent == 5
        assert config.bucket_size == 100


class TestTokenBucket:
    """Tests for token bucket rate limiting."""

    @pytest.mark.asyncio
    async def test_acquire_token_success(self, mock_async_redis):
        """Test successfully acquiring a token."""
        # Setup Redis mock to return available tokens
        mock_async_redis.get.return_value = b"10"  # 10 tokens available

        config = RateLimitConfig(provider_id="reddit", requests_per_minute=60)
        limiter = RateLimiter(mock_async_redis, config)

        result = await limiter.acquire_token()

        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_token_empty_bucket(self, mock_async_redis):
        """Test acquiring token when bucket is empty."""
        # Setup Redis mock to return no tokens and recent refill time
        # (so no tokens will be added via refill)
        now = str(time.time()).encode()
        mock_async_redis.get.side_effect = [b"0", now]  # tokens=0, last_refill=now

        config = RateLimitConfig(provider_id="reddit", requests_per_minute=60)
        limiter = RateLimiter(mock_async_redis, config)

        result = await limiter.acquire_token()

        assert result is False

    @pytest.mark.asyncio
    async def test_acquire_token_refills_bucket(self, mock_async_redis):
        """Test that tokens are refilled based on elapsed time."""
        # Mock: bucket was empty but time has passed for refill
        mock_async_redis.get.side_effect = [
            b"0",  # Current tokens
            str(time.time() - 60).encode(),  # Last refill was 60 seconds ago
        ]

        config = RateLimitConfig(provider_id="reddit", requests_per_minute=60)
        limiter = RateLimiter(mock_async_redis, config)

        # After refill, should have tokens available
        result = await limiter.acquire_token()

        # The limiter should have attempted to refill
        assert mock_async_redis.get.called

    @pytest.mark.asyncio
    async def test_token_bucket_keys(self, mock_async_redis):
        """Test that correct Redis keys are used."""
        mock_async_redis.get.return_value = b"10"

        config = RateLimitConfig(provider_id="reddit")
        limiter = RateLimiter(mock_async_redis, config)

        await limiter.acquire_token()

        # Should use provider-specific keys
        calls = [str(call) for call in mock_async_redis.get.call_args_list]
        assert any("reddit" in call for call in calls)

    @pytest.mark.asyncio
    async def test_release_token_not_needed(self, mock_async_redis):
        """Test that releasing a token is a no-op for token bucket."""
        config = RateLimitConfig(provider_id="reddit")
        limiter = RateLimiter(mock_async_redis, config)

        # Release should not raise
        await limiter.release_token()


class TestInflightConcurrency:
    """Tests for inflight concurrency limiting."""

    @pytest.mark.asyncio
    async def test_acquire_slot_success(self, mock_async_redis):
        """Test successfully acquiring a concurrency slot."""
        mock_async_redis.incr.return_value = 1  # First request

        config = RateLimitConfig(provider_id="reddit", max_concurrent=5)
        limiter = RateLimiter(mock_async_redis, config)

        result = await limiter.acquire_slot()

        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_slot_at_limit(self, mock_async_redis):
        """Test acquiring slot when at concurrency limit."""
        mock_async_redis.incr.return_value = 6  # Over limit of 5

        config = RateLimitConfig(provider_id="reddit", max_concurrent=5)
        limiter = RateLimiter(mock_async_redis, config)

        result = await limiter.acquire_slot()

        assert result is False
        # Should have decremented back
        mock_async_redis.decr.assert_called()

    @pytest.mark.asyncio
    async def test_release_slot(self, mock_async_redis):
        """Test releasing a concurrency slot."""
        config = RateLimitConfig(provider_id="reddit", max_concurrent=5)
        limiter = RateLimiter(mock_async_redis, config)

        await limiter.release_slot()

        mock_async_redis.decr.assert_called()

    @pytest.mark.asyncio
    async def test_slot_key_has_expiry(self, mock_async_redis):
        """Test that inflight key has TTL to prevent leaks."""
        mock_async_redis.incr.return_value = 1

        config = RateLimitConfig(provider_id="reddit", max_concurrent=5)
        limiter = RateLimiter(mock_async_redis, config)

        await limiter.acquire_slot()

        # Should set expiry on the key
        mock_async_redis.expire.assert_called()


class TestCombinedRateLimiting:
    """Tests for combined token + concurrency limiting."""

    @pytest.mark.asyncio
    async def test_acquire_checks_both(self, mock_async_redis):
        """Test that acquire checks both token and slot."""
        mock_async_redis.get.return_value = b"10"  # Tokens available
        mock_async_redis.incr.return_value = 1  # Slot available

        config = RateLimitConfig(
            provider_id="reddit",
            requests_per_minute=60,
            max_concurrent=5,
        )
        limiter = RateLimiter(mock_async_redis, config)

        result = await limiter.acquire()

        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_fails_if_no_tokens(self, mock_async_redis):
        """Test that acquire fails if no tokens available."""
        # No tokens and recent refill (so no tokens added)
        now = str(time.time()).encode()
        mock_async_redis.get.side_effect = [b"0", now]
        mock_async_redis.incr.return_value = 1  # Slot available

        config = RateLimitConfig(provider_id="reddit")
        limiter = RateLimiter(mock_async_redis, config)

        result = await limiter.acquire()

        assert result is False

    @pytest.mark.asyncio
    async def test_acquire_fails_if_no_slots(self, mock_async_redis):
        """Test that acquire fails if no slots available."""
        mock_async_redis.get.return_value = b"10"  # Tokens available
        mock_async_redis.incr.return_value = 100  # Way over slot limit

        config = RateLimitConfig(provider_id="reddit", max_concurrent=5)
        limiter = RateLimiter(mock_async_redis, config)

        result = await limiter.acquire()

        assert result is False

    @pytest.mark.asyncio
    async def test_release_decrements_slot(self, mock_async_redis):
        """Test that release decrements the slot counter."""
        config = RateLimitConfig(provider_id="reddit")
        limiter = RateLimiter(mock_async_redis, config)

        await limiter.release()

        mock_async_redis.decr.assert_called()

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_async_redis):
        """Test using rate limiter as async context manager."""
        mock_async_redis.get.return_value = b"10"
        mock_async_redis.incr.return_value = 1

        config = RateLimitConfig(provider_id="reddit")
        limiter = RateLimiter(mock_async_redis, config)

        async with limiter:
            # Should have acquired
            pass

        # Should have released after exit
        mock_async_redis.decr.assert_called()

    @pytest.mark.asyncio
    async def test_context_manager_raises_on_failure(self, mock_async_redis):
        """Test that context manager raises if cannot acquire."""
        # No tokens and recent refill (so no tokens added)
        now = str(time.time()).encode()
        mock_async_redis.get.side_effect = [b"0", now]

        config = RateLimitConfig(provider_id="reddit")
        limiter = RateLimiter(mock_async_redis, config)

        with pytest.raises(RateLimitExceeded):
            async with limiter:
                pass


class TestBackoffStrategy:
    """Tests for backoff strategy helper."""

    def test_backoff_initial_delay(self):
        """Test initial backoff delay."""
        strategy = BackoffStrategy()

        delay = strategy.get_delay(attempt=1)

        assert delay > 0
        assert delay <= 5  # Initial delay should be small

    def test_backoff_exponential_increase(self):
        """Test that backoff increases exponentially."""
        strategy = BackoffStrategy()

        delay1 = strategy.get_delay(attempt=1)
        delay2 = strategy.get_delay(attempt=2)
        delay3 = strategy.get_delay(attempt=3)

        assert delay2 > delay1
        assert delay3 > delay2

    def test_backoff_max_delay(self):
        """Test that backoff has a maximum."""
        strategy = BackoffStrategy(max_delay=60)

        delay = strategy.get_delay(attempt=100)

        assert delay <= 60

    def test_backoff_with_jitter(self):
        """Test that backoff includes jitter."""
        strategy = BackoffStrategy(jitter=True)

        delays = [strategy.get_delay(attempt=5) for _ in range(10)]

        # With jitter, delays should vary
        assert len(set(delays)) > 1

    def test_backoff_429_response(self):
        """Test backoff for 429 Too Many Requests."""
        strategy = BackoffStrategy(jitter=False)

        delay = strategy.get_delay_for_status(429, attempt=1)

        # 429 should have longer initial delay (30s base)
        assert delay >= 30

    def test_backoff_429_with_retry_after(self):
        """Test backoff respects Retry-After header."""
        strategy = BackoffStrategy()

        delay = strategy.get_delay_for_status(
            429,
            attempt=1,
            retry_after=120,
        )

        assert delay >= 120

    def test_backoff_5xx_response(self):
        """Test backoff for 5xx server errors."""
        strategy = BackoffStrategy(jitter=False)

        delay = strategy.get_delay_for_status(500, attempt=1)

        # Server errors should have moderate delay (5s base)
        assert delay >= 5

    def test_backoff_503_response(self):
        """Test backoff for 503 Service Unavailable."""
        strategy = BackoffStrategy(jitter=False)

        delay = strategy.get_delay_for_status(503, attempt=1)

        # 503 should have longer delay like 429 (30s base)
        assert delay >= 30

    def test_should_retry_429(self):
        """Test that 429 should always retry."""
        strategy = BackoffStrategy()

        assert strategy.should_retry(429, attempt=1) is True
        assert strategy.should_retry(429, attempt=5) is True

    def test_should_retry_5xx(self):
        """Test that 5xx should retry with limits."""
        strategy = BackoffStrategy(max_retries=3)

        assert strategy.should_retry(500, attempt=1) is True
        assert strategy.should_retry(500, attempt=3) is True
        assert strategy.should_retry(500, attempt=4) is False

    def test_should_not_retry_4xx(self):
        """Test that 4xx (except 429) should not retry."""
        strategy = BackoffStrategy()

        assert strategy.should_retry(400, attempt=1) is False
        assert strategy.should_retry(401, attempt=1) is False
        assert strategy.should_retry(403, attempt=1) is False
        assert strategy.should_retry(404, attempt=1) is False


class TestRateLimiterWait:
    """Tests for rate limiter wait/blocking behavior."""

    @pytest.mark.asyncio
    async def test_wait_for_token(self, mock_async_redis):
        """Test waiting for a token to become available."""
        # First call: no tokens, second call: tokens available
        mock_async_redis.get.side_effect = [b"0", b"10"]
        mock_async_redis.incr.return_value = 1

        config = RateLimitConfig(provider_id="reddit")
        limiter = RateLimiter(mock_async_redis, config)

        # Should eventually succeed
        result = await limiter.acquire(wait=True, timeout=1.0)

        assert result is True

    @pytest.mark.asyncio
    async def test_wait_timeout(self, mock_async_redis):
        """Test that wait times out if no tokens available."""
        # Always return no tokens with recent refill
        now = str(time.time()).encode()

        def get_side_effect(key):
            if "tokens" in key:
                return b"0"
            return now  # last_refill

        mock_async_redis.get.side_effect = get_side_effect

        config = RateLimitConfig(provider_id="reddit")
        limiter = RateLimiter(mock_async_redis, config)

        # Should timeout
        result = await limiter.acquire(wait=True, timeout=0.1)

        assert result is False

    @pytest.mark.asyncio
    async def test_wait_with_backoff(self, mock_async_redis):
        """Test that waiting uses backoff between retries."""
        call_count = [0]
        call_times = []
        now = str(time.time()).encode()

        async def mock_get(key):
            call_times.append(time.time())
            if "tokens" in key:
                call_count[0] += 1
                # Return 0 tokens for first 2 token checks, then 10
                return b"0" if call_count[0] < 3 else b"10"
            return now  # last_refill - always recent

        mock_async_redis.get.side_effect = mock_get
        mock_async_redis.incr.return_value = 1

        config = RateLimitConfig(provider_id="reddit")
        limiter = RateLimiter(mock_async_redis, config)

        await limiter.acquire(wait=True, timeout=5.0)

        # Should have had some delays between retry attempts
        # At least 3 token checks (2 failures + 1 success)
        assert call_count[0] >= 3


class TestRateLimiterStats:
    """Tests for rate limiter statistics."""

    @pytest.mark.asyncio
    async def test_get_stats(self, mock_async_redis):
        """Test getting rate limiter statistics."""
        mock_async_redis.get.side_effect = [b"45", b"3"]  # tokens, inflight

        config = RateLimitConfig(
            provider_id="reddit",
            requests_per_minute=60,
            max_concurrent=5,
        )
        limiter = RateLimiter(mock_async_redis, config)

        stats = await limiter.get_stats()

        assert stats["provider_id"] == "reddit"
        assert stats["tokens_available"] == 45
        assert stats["inflight_count"] == 3
        assert stats["max_concurrent"] == 5
        assert stats["requests_per_minute"] == 60


class TestMultipleProviders:
    """Tests for rate limiting multiple providers."""

    @pytest.mark.asyncio
    async def test_separate_limits_per_provider(self, mock_async_redis):
        """Test that each provider has separate limits."""
        mock_async_redis.get.return_value = b"10"
        mock_async_redis.incr.return_value = 1

        reddit_config = RateLimitConfig(provider_id="reddit", requests_per_minute=60)
        twitter_config = RateLimitConfig(provider_id="twitter", requests_per_minute=100)

        reddit_limiter = RateLimiter(mock_async_redis, reddit_config)
        twitter_limiter = RateLimiter(mock_async_redis, twitter_config)

        await reddit_limiter.acquire()
        await twitter_limiter.acquire()

        # Both should have used different keys
        get_calls = mock_async_redis.get.call_args_list
        keys_used = [str(call) for call in get_calls]

        assert any("reddit" in k for k in keys_used)
        assert any("twitter" in k for k in keys_used)


class TestRateLimiterReset:
    """Tests for resetting rate limiter state."""

    @pytest.mark.asyncio
    async def test_reset_tokens(self, mock_async_redis):
        """Test resetting token bucket to full."""
        config = RateLimitConfig(
            provider_id="reddit",
            bucket_size=100,
        )
        limiter = RateLimiter(mock_async_redis, config)

        await limiter.reset()

        # Should have used pipeline to set tokens
        mock_async_redis.pipeline.assert_called()

    @pytest.mark.asyncio
    async def test_reset_inflight(self, mock_async_redis):
        """Test resetting inflight counter."""
        config = RateLimitConfig(provider_id="reddit")
        limiter = RateLimiter(mock_async_redis, config)

        await limiter.reset()

        # Should have used pipeline to reset state
        mock_async_redis.pipeline.assert_called()
