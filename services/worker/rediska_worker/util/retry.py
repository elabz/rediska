"""Retry utilities for handling transient failures."""

import time
from functools import wraps
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        retryable_exceptions: tuple = (Exception,),
    ) -> None:
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.retryable_exceptions = retryable_exceptions


def exponential_backoff(attempt: int, config: RetryConfig) -> float:
    """Calculate exponential backoff delay."""
    delay = config.base_delay * (config.exponential_base ** (attempt - 1))
    return min(delay, config.max_delay)


def with_retry(config: RetryConfig | None = None) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to add retry logic with exponential backoff."""
    if config is None:
        config = RetryConfig()

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception | None = None

            for attempt in range(1, config.max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except config.retryable_exceptions as e:
                    last_exception = e
                    if attempt < config.max_attempts:
                        delay = exponential_backoff(attempt, config)
                        time.sleep(delay)

            if last_exception:
                raise last_exception
            raise RuntimeError("Unexpected retry state")

        return wrapper

    return decorator


# Predefined configs for common scenarios
RATE_LIMIT_RETRY = RetryConfig(
    max_attempts=5,
    base_delay=60.0,  # Start with 1 minute for rate limits
    max_delay=300.0,  # Max 5 minutes
    exponential_base=2.0,
)

NETWORK_RETRY = RetryConfig(
    max_attempts=3,
    base_delay=1.0,
    max_delay=30.0,
    exponential_base=2.0,
)
