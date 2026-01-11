"""Unit tests for ingest tasks.

Tests cover:
- Backfill conversations task
- Backfill messages task
- Delta sync task
- Browse location task
- Fetch profile task
"""

from unittest.mock import MagicMock, patch

import pytest


class TestBackfillConversations:
    """Tests for backfill_conversations task."""

    def test_task_is_registered(self, mock_celery_app):
        """Task should be registered with Celery."""
        from rediska_worker.tasks.ingest import backfill_conversations

        assert backfill_conversations.name == "ingest.backfill_conversations"

    def test_returns_not_implemented(self, mock_celery_app):
        """Task should return not_implemented status (stub)."""
        from rediska_worker.tasks.ingest import backfill_conversations

        result = backfill_conversations("reddit")

        assert result["status"] == "not_implemented"
        assert result["provider_id"] == "reddit"

    def test_accepts_provider_id_parameter(self, mock_celery_app):
        """Task should accept provider_id parameter."""
        from rediska_worker.tasks.ingest import backfill_conversations

        result = backfill_conversations(provider_id="twitter")

        assert result["provider_id"] == "twitter"


class TestBackfillMessages:
    """Tests for backfill_messages task."""

    def test_task_is_registered(self, mock_celery_app):
        """Task should be registered with Celery."""
        from rediska_worker.tasks.ingest import backfill_messages

        assert backfill_messages.name == "ingest.backfill_messages"

    def test_returns_not_implemented(self, mock_celery_app):
        """Task should return not_implemented status (stub)."""
        from rediska_worker.tasks.ingest import backfill_messages

        result = backfill_messages("reddit", "conv_123")

        assert result["status"] == "not_implemented"
        assert result["provider_id"] == "reddit"
        assert result["external_conversation_id"] == "conv_123"

    def test_accepts_cursor_parameter(self, mock_celery_app):
        """Task should accept optional cursor parameter."""
        from rediska_worker.tasks.ingest import backfill_messages

        result = backfill_messages("reddit", "conv_123", cursor="cursor_abc")

        assert result["status"] == "not_implemented"


class TestSyncDelta:
    """Tests for sync_delta task."""

    def test_task_is_registered(self, mock_celery_app):
        """Task should be registered with Celery."""
        from rediska_worker.tasks.ingest import sync_delta

        assert sync_delta.name == "ingest.sync_delta"

    def test_returns_not_implemented(self, mock_celery_app):
        """Task should return not_implemented status (stub)."""
        from rediska_worker.tasks.ingest import sync_delta

        result = sync_delta("reddit")

        assert result["status"] == "not_implemented"
        assert result["provider_id"] == "reddit"

    def test_accepts_optional_provider_id(self, mock_celery_app):
        """Task should work without provider_id (syncs all)."""
        from rediska_worker.tasks.ingest import sync_delta

        result = sync_delta()

        assert result["status"] == "not_implemented"
        assert result["provider_id"] is None


class TestBrowseLocation:
    """Tests for browse_location task."""

    def test_task_is_registered(self, mock_celery_app):
        """Task should be registered with Celery."""
        from rediska_worker.tasks.ingest import browse_location

        assert browse_location.name == "ingest.browse_location"

    def test_returns_not_implemented(self, mock_celery_app):
        """Task should return not_implemented status (stub)."""
        from rediska_worker.tasks.ingest import browse_location

        result = browse_location("reddit", "programming")

        assert result["status"] == "not_implemented"
        assert result["provider_id"] == "reddit"
        assert result["location"] == "programming"

    def test_accepts_cursor_parameter(self, mock_celery_app):
        """Task should accept optional cursor parameter."""
        from rediska_worker.tasks.ingest import browse_location

        result = browse_location("reddit", "programming", cursor="page_2")

        assert result["status"] == "not_implemented"


class TestFetchPost:
    """Tests for fetch_post task."""

    def test_task_is_registered(self, mock_celery_app):
        """Task should be registered with Celery."""
        from rediska_worker.tasks.ingest import fetch_post

        assert fetch_post.name == "ingest.fetch_post"

    def test_returns_not_implemented(self, mock_celery_app):
        """Task should return not_implemented status (stub)."""
        from rediska_worker.tasks.ingest import fetch_post

        result = fetch_post("reddit", "abc123")

        assert result["status"] == "not_implemented"
        assert result["provider_id"] == "reddit"
        assert result["post_id"] == "abc123"


class TestFetchProfile:
    """Tests for fetch_profile task."""

    def test_task_is_registered(self, mock_celery_app):
        """Task should be registered with Celery."""
        from rediska_worker.tasks.ingest import fetch_profile

        assert fetch_profile.name == "ingest.fetch_profile"

    def test_returns_not_implemented(self, mock_celery_app):
        """Task should return not_implemented status (stub)."""
        from rediska_worker.tasks.ingest import fetch_profile

        result = fetch_profile("reddit", "testuser")

        assert result["status"] == "not_implemented"
        assert result["provider_id"] == "reddit"
        assert result["username"] == "testuser"


class TestFetchProfileItems:
    """Tests for fetch_profile_items task."""

    def test_task_is_registered(self, mock_celery_app):
        """Task should be registered with Celery."""
        from rediska_worker.tasks.ingest import fetch_profile_items

        assert fetch_profile_items.name == "ingest.fetch_profile_items"

    def test_returns_not_implemented(self, mock_celery_app):
        """Task should return not_implemented status (stub)."""
        from rediska_worker.tasks.ingest import fetch_profile_items

        result = fetch_profile_items("reddit", "testuser")

        assert result["status"] == "not_implemented"
        assert result["provider_id"] == "reddit"
        assert result["username"] == "testuser"


class TestTaskRouting:
    """Tests for task routing configuration."""

    def test_ingest_tasks_routed_to_ingest_queue(self, mock_celery_app):
        """Ingest tasks should be routed to ingest queue."""
        routes = mock_celery_app.conf.task_routes

        assert "rediska_worker.tasks.ingest.*" in routes
        assert routes["rediska_worker.tasks.ingest.*"]["queue"] == "ingest"


class TestIngestTaskNames:
    """Tests for task naming conventions."""

    def test_all_ingest_tasks_have_correct_prefix(self, mock_celery_app):
        """All ingest tasks should have 'ingest.' prefix."""
        from rediska_worker.tasks import ingest

        tasks = [
            ingest.backfill_conversations,
            ingest.backfill_messages,
            ingest.sync_delta,
            ingest.browse_location,
            ingest.fetch_post,
            ingest.fetch_profile,
            ingest.fetch_profile_items,
        ]

        for task in tasks:
            assert task.name.startswith("ingest."), f"{task.name} should start with 'ingest.'"
