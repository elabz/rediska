"""Unit tests for idempotency utilities.

Tests cover:
- Dedupe key computation
- IdempotencyManager lock operations
"""

import json
from unittest.mock import MagicMock, AsyncMock

import pytest


class TestComputeDedupeKey:
    """Tests for dedupe key computation."""

    def test_basic_dedupe_key(self):
        """Test basic dedupe key generation."""
        from rediska_worker.util.idempotency import compute_dedupe_key

        key = compute_dedupe_key(
            job_type="test.job",
            payload={"user_id": 123},
        )

        assert key is not None
        assert len(key) == 32  # SHA256 truncated to 32 chars

    def test_deterministic_key(self):
        """Same inputs should produce same key."""
        from rediska_worker.util.idempotency import compute_dedupe_key

        key1 = compute_dedupe_key("test.job", {"user_id": 123})
        key2 = compute_dedupe_key("test.job", {"user_id": 123})

        assert key1 == key2

    def test_different_payloads_different_keys(self):
        """Different payloads should produce different keys."""
        from rediska_worker.util.idempotency import compute_dedupe_key

        key1 = compute_dedupe_key("test.job", {"user_id": 123})
        key2 = compute_dedupe_key("test.job", {"user_id": 456})

        assert key1 != key2

    def test_different_job_types_different_keys(self):
        """Different job types should produce different keys."""
        from rediska_worker.util.idempotency import compute_dedupe_key

        key1 = compute_dedupe_key("job.type.a", {"user_id": 123})
        key2 = compute_dedupe_key("job.type.b", {"user_id": 123})

        assert key1 != key2

    def test_dict_key_order_independent(self):
        """Dict key order should not affect dedupe key."""
        from rediska_worker.util.idempotency import compute_dedupe_key

        key1 = compute_dedupe_key("test.job", {"a": 1, "b": 2, "c": 3})
        key2 = compute_dedupe_key("test.job", {"c": 3, "a": 1, "b": 2})

        assert key1 == key2

    def test_nested_payload(self):
        """Test with nested payload objects."""
        from rediska_worker.util.idempotency import compute_dedupe_key

        payload = {
            "user": {"id": 123, "name": "test"},
            "items": [1, 2, 3],
            "metadata": {"source": "api"},
        }

        key1 = compute_dedupe_key("test.job", payload)
        key2 = compute_dedupe_key("test.job", payload)

        assert key1 == key2

    def test_empty_payload(self):
        """Test with empty payload."""
        from rediska_worker.util.idempotency import compute_dedupe_key

        key = compute_dedupe_key("test.job", {})

        assert key is not None
        assert len(key) == 32

    def test_payload_with_special_characters(self):
        """Test with special characters in payload."""
        from rediska_worker.util.idempotency import compute_dedupe_key

        payload = {
            "text": "Hello! @#$%^&*()",
            "emoji": "🎉",
            "unicode": "日本語",
        }

        key = compute_dedupe_key("test.job", payload)

        assert key is not None
        assert len(key) == 32

    def test_payload_with_datetime_serialization(self):
        """Test with datetime in payload (uses default=str)."""
        from datetime import datetime
        from rediska_worker.util.idempotency import compute_dedupe_key

        payload = {
            "timestamp": datetime(2024, 1, 15, 12, 0, 0),
        }

        # Should not raise
        key = compute_dedupe_key("test.job", payload)

        assert key is not None


class TestIdempotencyManager:
    """Tests for IdempotencyManager class."""

    @pytest.fixture
    def manager(self, mock_db_session):
        """Create IdempotencyManager with mock DB."""
        from rediska_worker.util.idempotency import IdempotencyManager

        return IdempotencyManager(mock_db_session)

    @pytest.mark.asyncio
    async def test_acquire_lock_returns_true(self, manager):
        """acquire_lock should return True (stub implementation)."""
        result = await manager.acquire_lock("test-dedupe-key")

        assert result is True

    @pytest.mark.asyncio
    async def test_release_lock_no_error(self, manager):
        """release_lock should not raise errors."""
        # Should not raise
        await manager.release_lock("test-dedupe-key")

    @pytest.mark.asyncio
    async def test_mark_complete_no_error(self, manager):
        """mark_complete should not raise errors."""
        # Should not raise
        await manager.mark_complete("test-dedupe-key")

    @pytest.mark.asyncio
    async def test_mark_failed_no_error(self, manager):
        """mark_failed should not raise errors."""
        # Should not raise
        await manager.mark_failed("test-dedupe-key", "Test error message")


class TestDedupeKeyProperties:
    """Property-based tests for dedupe key generation."""

    def test_key_is_hex_string(self):
        """Dedupe key should be a valid hex string."""
        from rediska_worker.util.idempotency import compute_dedupe_key

        key = compute_dedupe_key("test.job", {"data": "value"})

        # All characters should be valid hex
        assert all(c in "0123456789abcdef" for c in key)

    def test_key_length_consistent(self):
        """Key length should be consistent regardless of input size."""
        from rediska_worker.util.idempotency import compute_dedupe_key

        small_key = compute_dedupe_key("job", {"x": 1})
        large_key = compute_dedupe_key(
            "very.long.job.type.name.here",
            {f"key_{i}": f"value_{i}" for i in range(100)},
        )

        assert len(small_key) == len(large_key) == 32


class TestDedupeKeyEdgeCases:
    """Edge case tests for dedupe key generation."""

    def test_none_values_in_payload(self):
        """Test payload containing None values."""
        from rediska_worker.util.idempotency import compute_dedupe_key

        key = compute_dedupe_key("test.job", {"value": None, "other": "data"})

        assert key is not None

    def test_boolean_values_in_payload(self):
        """Test payload containing boolean values."""
        from rediska_worker.util.idempotency import compute_dedupe_key

        key = compute_dedupe_key("test.job", {"enabled": True, "disabled": False})

        assert key is not None

    def test_numeric_values_in_payload(self):
        """Test various numeric values in payload."""
        from rediska_worker.util.idempotency import compute_dedupe_key

        payload = {
            "integer": 42,
            "negative": -100,
            "float": 3.14159,
            "zero": 0,
        }

        key = compute_dedupe_key("test.job", payload)

        assert key is not None

    def test_list_values_in_payload(self):
        """Test list values in payload."""
        from rediska_worker.util.idempotency import compute_dedupe_key

        payload = {
            "empty_list": [],
            "numbers": [1, 2, 3],
            "mixed": [1, "two", None, True],
        }

        key = compute_dedupe_key("test.job", payload)

        assert key is not None

    def test_deeply_nested_payload(self):
        """Test deeply nested payload structure."""
        from rediska_worker.util.idempotency import compute_dedupe_key

        payload = {
            "level1": {
                "level2": {
                    "level3": {
                        "level4": {
                            "value": "deep",
                        }
                    }
                }
            }
        }

        key = compute_dedupe_key("test.job", payload)

        assert key is not None
