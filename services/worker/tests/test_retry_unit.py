"""Unit tests for retry utilities.

Tests cover:
- Exponential backoff calculation
- Retry decorator behavior
- Predefined retry configurations
"""

import time
from unittest.mock import MagicMock, patch

import pytest


class TestRetryConfig:
    """Tests for RetryConfig class."""

    def test_default_config(self):
        """Test default retry configuration values."""
        from rediska_worker.util.retry import RetryConfig

        config = RetryConfig()

        assert config.max_attempts == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.exponential_base == 2.0
        assert config.retryable_exceptions == (Exception,)

    def test_custom_config(self):
        """Test custom retry configuration."""
        from rediska_worker.util.retry import RetryConfig

        config = RetryConfig(
            max_attempts=5,
            base_delay=2.0,
            max_delay=120.0,
            exponential_base=3.0,
            retryable_exceptions=(ValueError, TypeError),
        )

        assert config.max_attempts == 5
        assert config.base_delay == 2.0
        assert config.max_delay == 120.0
        assert config.exponential_base == 3.0
        assert config.retryable_exceptions == (ValueError, TypeError)


class TestExponentialBackoff:
    """Tests for exponential backoff calculation."""

    def test_first_attempt_returns_base_delay(self):
        """First attempt should return base delay."""
        from rediska_worker.util.retry import RetryConfig, exponential_backoff

        config = RetryConfig(base_delay=1.0, exponential_base=2.0)

        delay = exponential_backoff(attempt=1, config=config)

        assert delay == 1.0

    def test_second_attempt_doubles_delay(self):
        """Second attempt with base 2 should double the delay."""
        from rediska_worker.util.retry import RetryConfig, exponential_backoff

        config = RetryConfig(base_delay=1.0, exponential_base=2.0)

        delay = exponential_backoff(attempt=2, config=config)

        assert delay == 2.0

    def test_third_attempt_quadruples_delay(self):
        """Third attempt with base 2 should quadruple the delay."""
        from rediska_worker.util.retry import RetryConfig, exponential_backoff

        config = RetryConfig(base_delay=1.0, exponential_base=2.0)

        delay = exponential_backoff(attempt=3, config=config)

        assert delay == 4.0

    def test_delay_capped_at_max(self):
        """Delay should be capped at max_delay."""
        from rediska_worker.util.retry import RetryConfig, exponential_backoff

        config = RetryConfig(base_delay=10.0, max_delay=30.0, exponential_base=2.0)

        # Attempt 10 would be 10 * 2^9 = 5120, but should be capped
        delay = exponential_backoff(attempt=10, config=config)

        assert delay == 30.0

    def test_custom_base_multiplier(self):
        """Test with different exponential base."""
        from rediska_worker.util.retry import RetryConfig, exponential_backoff

        config = RetryConfig(base_delay=1.0, exponential_base=3.0)

        delay = exponential_backoff(attempt=3, config=config)

        # 1.0 * 3^2 = 9.0
        assert delay == 9.0


class TestWithRetryDecorator:
    """Tests for with_retry decorator."""

    def test_successful_call_no_retry(self):
        """Successful call should not retry."""
        from rediska_worker.util.retry import RetryConfig, with_retry

        call_count = [0]

        @with_retry(RetryConfig(max_attempts=3))
        def successful_func():
            call_count[0] += 1
            return "success"

        result = successful_func()

        assert result == "success"
        assert call_count[0] == 1

    def test_retries_on_exception(self):
        """Should retry on retryable exception."""
        from rediska_worker.util.retry import RetryConfig, with_retry

        call_count = [0]

        @with_retry(RetryConfig(max_attempts=3, base_delay=0.01))
        def failing_func():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("Temporary error")
            return "success"

        result = failing_func()

        assert result == "success"
        assert call_count[0] == 3

    def test_raises_after_max_attempts(self):
        """Should raise after max attempts exhausted."""
        from rediska_worker.util.retry import RetryConfig, with_retry

        call_count = [0]

        @with_retry(RetryConfig(max_attempts=3, base_delay=0.01))
        def always_fails():
            call_count[0] += 1
            raise ValueError("Always fails")

        with pytest.raises(ValueError, match="Always fails"):
            always_fails()

        assert call_count[0] == 3

    def test_only_retries_specified_exceptions(self):
        """Should only retry specified exception types."""
        from rediska_worker.util.retry import RetryConfig, with_retry

        call_count = [0]

        @with_retry(
            RetryConfig(
                max_attempts=3,
                base_delay=0.01,
                retryable_exceptions=(ValueError,),
            )
        )
        def raises_type_error():
            call_count[0] += 1
            raise TypeError("Not retryable")

        with pytest.raises(TypeError, match="Not retryable"):
            raises_type_error()

        # Should not retry on TypeError
        assert call_count[0] == 1

    def test_default_config_when_none(self):
        """Should use default config when None provided."""
        from rediska_worker.util.retry import with_retry

        @with_retry(None)
        def simple_func():
            return "result"

        result = simple_func()

        assert result == "result"

    @patch("time.sleep")
    def test_sleeps_between_retries(self, mock_sleep):
        """Should sleep between retry attempts."""
        from rediska_worker.util.retry import RetryConfig, with_retry

        call_count = [0]

        @with_retry(RetryConfig(max_attempts=3, base_delay=1.0))
        def fails_twice():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("Fail")
            return "success"

        fails_twice()

        # Should have slept twice (after attempt 1 and 2)
        assert mock_sleep.call_count == 2

    def test_preserves_function_metadata(self):
        """Decorator should preserve function metadata."""
        from rediska_worker.util.retry import with_retry

        @with_retry()
        def documented_func():
            """This is documentation."""
            return 42

        assert documented_func.__name__ == "documented_func"
        assert documented_func.__doc__ == "This is documentation."


class TestPredefinedConfigs:
    """Tests for predefined retry configurations."""

    def test_rate_limit_retry_config(self):
        """Test rate limit retry configuration."""
        from rediska_worker.util.retry import RATE_LIMIT_RETRY

        assert RATE_LIMIT_RETRY.max_attempts == 5
        assert RATE_LIMIT_RETRY.base_delay == 60.0
        assert RATE_LIMIT_RETRY.max_delay == 300.0

    def test_network_retry_config(self):
        """Test network retry configuration."""
        from rediska_worker.util.retry import NETWORK_RETRY

        assert NETWORK_RETRY.max_attempts == 3
        assert NETWORK_RETRY.base_delay == 1.0
        assert NETWORK_RETRY.max_delay == 30.0


class TestRetryWithRealDelay:
    """Tests that verify actual delay behavior (use sparingly)."""

    def test_retry_has_delay(self):
        """Verify retry actually delays (quick test)."""
        from rediska_worker.util.retry import RetryConfig, with_retry

        call_times = []

        @with_retry(RetryConfig(max_attempts=2, base_delay=0.05))
        def timed_fail():
            call_times.append(time.time())
            if len(call_times) < 2:
                raise ValueError("Fail")
            return "success"

        timed_fail()

        # Second call should be at least 0.04 seconds after first
        assert call_times[1] - call_times[0] >= 0.04
