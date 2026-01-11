"""Unit tests for performance-related features (indexes, query limits)."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone

from rediska_core.domain.query_limits import (
    QueryLimits,
    QueryTimeoutError,
    apply_query_limits,
    DEFAULT_ES_TIMEOUT,
    DEFAULT_ES_MAX_RESULTS,
)


class TestQueryLimits:
    """Tests for QueryLimits configuration."""

    def test_create_default_limits(self):
        """Test creating query limits with defaults."""
        limits = QueryLimits()

        assert limits.timeout_ms == DEFAULT_ES_TIMEOUT
        assert limits.max_results == DEFAULT_ES_MAX_RESULTS
        assert limits.min_score is None

    def test_create_custom_limits(self):
        """Test creating query limits with custom values."""
        limits = QueryLimits(
            timeout_ms=5000,
            max_results=50,
            min_score=0.5,
        )

        assert limits.timeout_ms == 5000
        assert limits.max_results == 50
        assert limits.min_score == 0.5

    def test_timeout_clamped_to_max(self):
        """Test that timeout is clamped to maximum."""
        limits = QueryLimits(timeout_ms=60000, max_timeout_ms=30000)

        assert limits.timeout_ms == 30000

    def test_max_results_clamped(self):
        """Test that max_results is clamped to limit."""
        limits = QueryLimits(max_results=5000, max_results_limit=1000)

        assert limits.max_results == 1000

    def test_timeout_minimum(self):
        """Test that timeout has a minimum value."""
        limits = QueryLimits(timeout_ms=0)

        assert limits.timeout_ms >= 100

    def test_max_results_minimum(self):
        """Test that max_results has a minimum value."""
        limits = QueryLimits(max_results=0)

        assert limits.max_results >= 1

    def test_to_dict(self):
        """Test converting limits to dictionary."""
        limits = QueryLimits(timeout_ms=5000, max_results=100)

        result = limits.to_dict()

        assert result["timeout_ms"] == 5000
        assert result["max_results"] == 100

    def test_to_es_params(self):
        """Test converting limits to Elasticsearch parameters."""
        limits = QueryLimits(timeout_ms=5000, max_results=100, min_score=0.5)

        es_params = limits.to_es_params()

        assert es_params["timeout"] == "5000ms"
        assert es_params["size"] == 100
        assert es_params["min_score"] == 0.5


class TestQueryLimitsFromEnv:
    """Tests for creating QueryLimits from environment."""

    def test_from_env_defaults(self):
        """Test creating limits from environment with defaults."""
        limits = QueryLimits.from_env()

        assert limits.timeout_ms == DEFAULT_ES_TIMEOUT
        assert limits.max_results == DEFAULT_ES_MAX_RESULTS

    @patch.dict("os.environ", {"ES_QUERY_TIMEOUT_MS": "8000"})
    def test_from_env_custom_timeout(self):
        """Test creating limits with custom timeout from env."""
        limits = QueryLimits.from_env()

        assert limits.timeout_ms == 8000

    @patch.dict("os.environ", {"ES_MAX_RESULTS": "200"})
    def test_from_env_custom_max_results(self):
        """Test creating limits with custom max results from env."""
        limits = QueryLimits.from_env()

        assert limits.max_results == 200


class TestApplyQueryLimits:
    """Tests for applying query limits to ES queries."""

    def test_apply_limits_adds_timeout(self):
        """Test that limits add timeout to query."""
        query = {"query": {"match_all": {}}}
        limits = QueryLimits(timeout_ms=5000, max_results=100)

        result = apply_query_limits(query, limits)

        assert "timeout" in result
        assert result["timeout"] == "5000ms"

    def test_apply_limits_adds_size(self):
        """Test that limits add size to query."""
        query = {"query": {"match_all": {}}}
        limits = QueryLimits(timeout_ms=5000, max_results=50)

        result = apply_query_limits(query, limits)

        assert result["size"] == 50

    def test_apply_limits_adds_min_score(self):
        """Test that limits add min_score when specified."""
        query = {"query": {"match_all": {}}}
        limits = QueryLimits(timeout_ms=5000, max_results=100, min_score=0.5)

        result = apply_query_limits(query, limits)

        assert result["min_score"] == 0.5

    def test_apply_limits_preserves_existing_query(self):
        """Test that limits preserve existing query parameters."""
        query = {
            "query": {"match": {"title": "test"}},
            "sort": [{"created_at": "desc"}],
        }
        limits = QueryLimits(timeout_ms=5000, max_results=100)

        result = apply_query_limits(query, limits)

        assert result["query"] == {"match": {"title": "test"}}
        assert result["sort"] == [{"created_at": "desc"}]

    def test_apply_limits_respects_existing_size(self):
        """Test that limits cap existing size if lower."""
        query = {"query": {"match_all": {}}, "size": 500}
        limits = QueryLimits(timeout_ms=5000, max_results=100)

        result = apply_query_limits(query, limits)

        # Should cap to max_results
        assert result["size"] == 100

    def test_apply_limits_keeps_smaller_existing_size(self):
        """Test that limits keep existing size if smaller than max."""
        query = {"query": {"match_all": {}}, "size": 25}
        limits = QueryLimits(timeout_ms=5000, max_results=100)

        result = apply_query_limits(query, limits)

        # Should keep original size
        assert result["size"] == 25


class TestQueryTimeoutError:
    """Tests for QueryTimeoutError exception."""

    def test_create_timeout_error(self):
        """Test creating a timeout error."""
        error = QueryTimeoutError(
            query_type="search",
            timeout_ms=5000,
            partial_results=10,
        )

        assert error.query_type == "search"
        assert error.timeout_ms == 5000
        assert error.partial_results == 10

    def test_timeout_error_message(self):
        """Test timeout error message."""
        error = QueryTimeoutError(
            query_type="search",
            timeout_ms=5000,
        )

        assert "5000ms" in str(error)
        assert "search" in str(error).lower()

    def test_timeout_error_to_dict(self):
        """Test converting timeout error to dict."""
        error = QueryTimeoutError(
            query_type="search",
            timeout_ms=5000,
            partial_results=10,
        )

        result = error.to_dict()

        assert result["error_type"] == "query_timeout"
        assert result["query_type"] == "search"
        assert result["timeout_ms"] == 5000
        assert result["partial_results"] == 10


class TestDatabaseIndexes:
    """Tests for verifying database indexes exist."""

    def test_message_conversation_time_index(self):
        """Verify Message has index on conversation_id + sent_at."""
        from rediska_core.domain.models import Message

        table = Message.__table__
        index_names = [idx.name for idx in table.indexes]

        assert "idx_msg_conv_time" in index_names

    def test_conversation_last_activity_index(self):
        """Verify Conversation has index on last_activity_at."""
        from rediska_core.domain.models import Conversation

        table = Conversation.__table__
        index_names = [idx.name for idx in table.indexes]

        assert "idx_conv_last_activity" in index_names

    def test_lead_post_status_index(self):
        """Verify LeadPost has index on status."""
        from rediska_core.domain.models import LeadPost

        table = LeadPost.__table__
        index_names = [idx.name for idx in table.indexes]

        assert "idx_status" in index_names

    def test_audit_log_timestamp_index(self):
        """Verify AuditLog has index on timestamp."""
        from rediska_core.domain.models import AuditLog

        table = AuditLog.__table__
        index_names = [idx.name for idx in table.indexes]

        assert "idx_audit_ts" in index_names

    def test_attachment_message_index(self):
        """Verify Attachment has index on message_id."""
        from rediska_core.domain.models import Attachment

        table = Attachment.__table__
        index_names = [idx.name for idx in table.indexes]

        assert "idx_attach_msg" in index_names


class TestPaginationIndexOptimization:
    """Tests for pagination index optimization patterns."""

    def test_conversation_inbox_query_uses_index(self):
        """Verify inbox query pattern is optimized."""
        from rediska_core.domain.models import Conversation

        table = Conversation.__table__
        index_names = [idx.name for idx in table.indexes]

        # Should have index for last_activity_at for inbox sorting
        assert "idx_conv_last_activity" in index_names
        # Should have index for identity filtering
        assert "idx_conv_identity" in index_names

    def test_message_thread_query_uses_index(self):
        """Verify message thread query pattern is optimized."""
        from rediska_core.domain.models import Message

        table = Message.__table__
        index_names = [idx.name for idx in table.indexes]

        # Should have composite index for conversation + time
        assert "idx_msg_conv_time" in index_names

    def test_audit_log_query_uses_index(self):
        """Verify audit log query pattern is optimized."""
        from rediska_core.domain.models import AuditLog

        table = AuditLog.__table__
        index_names = [idx.name for idx in table.indexes]

        # Should have index for timestamp sorting
        assert "idx_audit_ts" in index_names
        # Should have index for action type filtering
        assert "idx_audit_action" in index_names


class TestESQueryWithLimits:
    """Integration tests for ES query with limits."""

    def test_search_query_with_timeout(self):
        """Test building search query with timeout."""
        limits = QueryLimits(timeout_ms=5000, max_results=100)

        query = {
            "query": {
                "bool": {
                    "must": [
                        {"match": {"body": "test search"}}
                    ]
                }
            }
        }

        result = apply_query_limits(query, limits)

        assert result["timeout"] == "5000ms"
        assert result["size"] == 100
        assert "query" in result

    def test_aggregation_query_with_limits(self):
        """Test building aggregation query with limits."""
        limits = QueryLimits(timeout_ms=10000, max_results=0)  # No results, just aggs

        query = {
            "query": {"match_all": {}},
            "aggs": {
                "by_status": {
                    "terms": {"field": "status"}
                }
            },
            "size": 0,
        }

        result = apply_query_limits(query, limits)

        assert result["timeout"] == "10000ms"
        assert result["size"] == 0  # Keep size 0 for agg queries
        assert "aggs" in result
