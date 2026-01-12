"""Redis-backed rate limiter for provider API calls.

Implements:
- Token bucket algorithm for rate limiting (requests per minute)
- Inflight concurrency limiting (max concurrent requests)
- Exponential backoff strategy for 429/5xx errors

Usage:
    config = RateLimitConfig(provider_id="reddit", requests_per_minute=60)
    limiter = RateLimiter(redis_client, config)

    async with limiter:
        # Make API call
        response = await provider.api_call()
"""

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional, Protocol


class AsyncRedisProtocol(Protocol):
    """Protocol for async Redis client."""

    async def get(self, key: str) -> Optional[bytes]: ...
    async def set(self, key: str, value: str) -> Any: ...
    async def incr(self, key: str) -> int: ...
    async def decr(self, key: str) -> int: ...
    async def delete(self, *keys: str) -> int: ...
    async def expire(self, key: str, seconds: int) -> bool: ...
    def pipeline(self) -> Any: ...


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded and cannot acquire."""

    pass


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting a provider.

    Attributes:
        provider_id: Unique identifier for the provider (e.g., "reddit").
        requests_per_minute: Maximum requests per minute (token refill rate).
        max_concurrent: Maximum concurrent requests allowed.
        bucket_size: Maximum tokens in bucket (burst capacity).
    """

    provider_id: str
    requests_per_minute: int = 60
    max_concurrent: int = 10
    bucket_size: int = 0  # 0 means same as requests_per_minute

    def __post_init__(self):
        if self.bucket_size == 0:
            self.bucket_size = self.requests_per_minute


@dataclass
class BackoffStrategy:
    """Exponential backoff strategy for retries.

    Attributes:
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay in seconds.
        multiplier: Multiplier for exponential increase.
        jitter: Whether to add random jitter.
        max_retries: Maximum number of retries (0 = unlimited for 429).
    """

    base_delay: float = 1.0
    max_delay: float = 300.0  # 5 minutes
    multiplier: float = 2.0
    jitter: bool = True
    max_retries: int = 5

    # Special delays for specific status codes
    _status_delays: dict[int, float] = field(default_factory=lambda: {
        429: 30.0,  # Rate limited - longer initial delay
        503: 30.0,  # Service unavailable - longer delay
        500: 5.0,   # Server error - moderate delay
        502: 10.0,  # Bad gateway - moderate delay
        504: 10.0,  # Gateway timeout - moderate delay
    })

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for a retry attempt.

        Args:
            attempt: The attempt number (1-based).

        Returns:
            Delay in seconds before next retry.
        """
        delay = self.base_delay * (self.multiplier ** (attempt - 1))

        if self.jitter:
            # Add +/- 25% jitter before capping
            jitter_range = delay * 0.25
            delay = delay + random.uniform(-jitter_range, jitter_range)

        # Cap at max_delay after jitter
        delay = min(delay, self.max_delay)

        return max(0.1, delay)  # Minimum 100ms

    def get_delay_for_status(
        self,
        status_code: int,
        attempt: int,
        retry_after: Optional[int] = None,
    ) -> float:
        """Calculate delay based on HTTP status code.

        Args:
            status_code: The HTTP status code.
            attempt: The attempt number (1-based).
            retry_after: Optional Retry-After header value in seconds.

        Returns:
            Delay in seconds before next retry.
        """
        # Respect Retry-After header if provided
        if retry_after is not None:
            return max(retry_after, self.get_delay(attempt))

        # Use status-specific base delay if available
        base = self._status_delays.get(status_code, self.base_delay)

        # Apply exponential backoff from the status-specific base
        delay = base * (self.multiplier ** (attempt - 1))

        if self.jitter:
            jitter_range = delay * 0.25
            delay = delay + random.uniform(-jitter_range, jitter_range)

        # Cap at max_delay after jitter
        delay = min(delay, self.max_delay)

        return max(0.1, delay)

    def should_retry(self, status_code: int, attempt: int) -> bool:
        """Determine if a request should be retried.

        Args:
            status_code: The HTTP status code.
            attempt: The current attempt number.

        Returns:
            True if should retry, False otherwise.
        """
        # 429 always retries (rate limit is temporary)
        if status_code == 429:
            return True

        # 5xx errors retry with limit
        if 500 <= status_code < 600:
            return attempt <= self.max_retries

        # 4xx errors (except 429) don't retry
        return False


class RateLimiter:
    """Redis-backed rate limiter combining token bucket and concurrency limiting.

    Uses Redis keys:
    - rate:{provider_id}:tokens - Current token count
    - rate:{provider_id}:last_refill - Timestamp of last refill
    - rate:{provider_id}:inflight - Current inflight request count
    """

    def __init__(self, redis: AsyncRedisProtocol, config: RateLimitConfig):
        """Initialize the rate limiter.

        Args:
            redis: Async Redis client.
            config: Rate limit configuration.
        """
        self.redis = redis
        self.config = config

        # Redis key names
        self._tokens_key = f"rate:{config.provider_id}:tokens"
        self._refill_key = f"rate:{config.provider_id}:last_refill"
        self._inflight_key = f"rate:{config.provider_id}:inflight"

        # Calculate refill rate (tokens per second)
        self._refill_rate = config.requests_per_minute / 60.0

    async def acquire_token(self) -> bool:
        """Attempt to acquire a token from the bucket.

        Returns:
            True if token acquired, False if bucket empty.
        """
        # Get current state
        tokens_raw = await self.redis.get(self._tokens_key)
        last_refill_raw = await self.redis.get(self._refill_key)

        now = time.time()

        # Parse current values
        if tokens_raw is None:
            # Initialize bucket to full
            tokens = float(self.config.bucket_size)
            last_refill = now
        else:
            tokens = float(tokens_raw)
            last_refill = float(last_refill_raw) if last_refill_raw else now

        # Calculate tokens to add based on elapsed time
        elapsed = now - last_refill
        tokens_to_add = elapsed * self._refill_rate
        tokens = min(tokens + tokens_to_add, self.config.bucket_size)

        # Try to consume a token
        if tokens >= 1:
            tokens -= 1
            # Update Redis
            pipe = self.redis.pipeline()
            pipe.set(self._tokens_key, str(tokens))
            pipe.set(self._refill_key, str(now))
            pipe.expire(self._tokens_key, 3600)  # 1 hour TTL
            pipe.expire(self._refill_key, 3600)
            await pipe.execute()
            return True

        return False

    async def release_token(self) -> None:
        """Release a token (no-op for token bucket).

        Token bucket doesn't need explicit release as tokens
        are automatically refilled over time.
        """
        pass

    async def acquire_slot(self) -> bool:
        """Attempt to acquire a concurrency slot.

        Returns:
            True if slot acquired, False if at limit.
        """
        # Atomically increment inflight counter
        count = await self.redis.incr(self._inflight_key)

        # Set expiry to prevent leaks from crashed processes
        await self.redis.expire(self._inflight_key, 300)  # 5 minute TTL

        if count > self.config.max_concurrent:
            # Over limit, decrement and fail
            await self.redis.decr(self._inflight_key)
            return False

        return True

    async def release_slot(self) -> None:
        """Release a concurrency slot."""
        await self.redis.decr(self._inflight_key)

    async def acquire(self, wait: bool = False, timeout: float = 30.0) -> bool:
        """Acquire both token and slot.

        Args:
            wait: Whether to wait for availability.
            timeout: Maximum time to wait in seconds.

        Returns:
            True if acquired, False if not available (and not waiting).
        """
        start_time = time.time()
        attempt = 0
        backoff = BackoffStrategy(base_delay=0.1, max_delay=5.0)

        while True:
            attempt += 1

            # Try to acquire slot first (faster to check)
            slot_acquired = await self.acquire_slot()
            if not slot_acquired:
                if not wait or (time.time() - start_time) >= timeout:
                    return False
                await asyncio.sleep(backoff.get_delay(attempt))
                continue

            # Try to acquire token
            token_acquired = await self.acquire_token()
            if token_acquired:
                return True

            # Release slot since we couldn't get token
            await self.release_slot()

            if not wait or (time.time() - start_time) >= timeout:
                return False

            await asyncio.sleep(backoff.get_delay(attempt))

    async def release(self) -> None:
        """Release acquired resources."""
        await self.release_slot()
        # Token doesn't need explicit release

    async def __aenter__(self) -> "RateLimiter":
        """Async context manager entry."""
        acquired = await self.acquire()
        if not acquired:
            raise RateLimitExceeded(
                f"Rate limit exceeded for provider {self.config.provider_id}"
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.release()

    async def get_stats(self) -> dict[str, Any]:
        """Get current rate limiter statistics.

        Returns:
            Dictionary with current state.
        """
        tokens_raw = await self.redis.get(self._tokens_key)
        inflight_raw = await self.redis.get(self._inflight_key)

        tokens = int(float(tokens_raw)) if tokens_raw else self.config.bucket_size
        inflight = int(inflight_raw) if inflight_raw else 0

        return {
            "provider_id": self.config.provider_id,
            "tokens_available": tokens,
            "bucket_size": self.config.bucket_size,
            "inflight_count": inflight,
            "max_concurrent": self.config.max_concurrent,
            "requests_per_minute": self.config.requests_per_minute,
        }

    async def reset(self) -> None:
        """Reset rate limiter state to initial values."""
        pipe = self.redis.pipeline()
        pipe.set(self._tokens_key, str(self.config.bucket_size))
        pipe.set(self._refill_key, str(time.time()))
        pipe.delete(self._inflight_key)
        await pipe.execute()
