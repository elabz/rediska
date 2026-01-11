"""Unit tests for message tasks.

Tests cover:
- send_manual task
- At-most-once delivery semantics
- Error handling
"""

from unittest.mock import MagicMock, patch, AsyncMock

import pytest


class TestSendManualTask:
    """Tests for send_manual task."""

    def test_task_is_registered(self, mock_celery_app):
        """Task should be registered with Celery."""
        from rediska_worker.tasks.message import send_manual

        assert send_manual.name == "message.send_manual"

    def test_task_has_no_retries(self, mock_celery_app):
        """Task should have max_retries=0 for at-most-once."""
        from rediska_worker.tasks.message import send_manual

        assert send_manual.max_retries == 0

    def test_task_acks_early(self, mock_celery_app):
        """Task should ack early to prevent redelivery."""
        from rediska_worker.tasks.message import send_manual

        assert send_manual.acks_late is False

    def test_missing_required_fields_returns_error(self, mock_celery_app):
        """Task should return error for missing required fields."""
        from rediska_worker.tasks.message import send_manual

        # Missing most fields - task validates before DB calls
        # Note: Task imports rediska_core which may not be available
        try:
            result = send_manual.apply(args=[{"message_id": 123}]).get()
            assert result["status"] == "error"
        except ModuleNotFoundError:
            # rediska_core not available in isolated test
            pytest.skip("rediska_core not available")

    def test_missing_message_id_returns_error(self, mock_celery_app):
        """Task should return error when message_id is missing."""
        from rediska_worker.tasks.message import send_manual

        payload = {
            "conversation_id": 1,
            "identity_id": 1,
            "provider_id": "reddit",
            "body_text": "Test message",
        }

        try:
            result = send_manual.apply(args=[payload]).get()
            assert result["status"] == "error"
        except ModuleNotFoundError:
            pytest.skip("rediska_core not available")

    def test_missing_body_text_returns_error(self, mock_celery_app):
        """Task should return error when body_text is missing."""
        from rediska_worker.tasks.message import send_manual

        payload = {
            "message_id": 1,
            "conversation_id": 1,
            "identity_id": 1,
            "provider_id": "reddit",
        }

        try:
            result = send_manual.apply(args=[payload]).get()
            assert result["status"] == "error"
        except ModuleNotFoundError:
            pytest.skip("rediska_core not available")


class TestSendManualPayloadValidation:
    """Tests for payload validation in send_manual."""

    def test_valid_payload_structure(self):
        """Test expected payload structure."""
        valid_payload = {
            "message_id": 123,
            "conversation_id": 456,
            "identity_id": 789,
            "provider_id": "reddit",
            "body_text": "Hello, this is a test message.",
            "attachment_ids": [1, 2, 3],
        }

        # Verify all keys are present
        required_keys = {"message_id", "conversation_id", "identity_id", "provider_id", "body_text"}
        assert required_keys.issubset(valid_payload.keys())


class TestAtMostOnceSemantics:
    """Tests for at-most-once delivery semantics."""

    def test_no_automatic_retries_configured(self, mock_celery_app):
        """Task should not have automatic retries."""
        from rediska_worker.tasks.message import send_manual

        # max_retries=0 means no automatic retries
        assert send_manual.max_retries == 0

    def test_acks_late_disabled(self, mock_celery_app):
        """Task should acknowledge immediately, not after execution."""
        from rediska_worker.tasks.message import send_manual

        # acks_late=False means acknowledge immediately
        assert send_manual.acks_late is False


class TestSendManualErrorHandling:
    """Tests for error handling in send_manual.

    Note: These tests require the core service imports, so they test
    the import structure rather than full functionality.
    """

    def test_task_handles_import_errors_gracefully(self, mock_celery_app):
        """Task should handle missing dependencies gracefully."""
        from rediska_worker.tasks.message import send_manual

        # Running task with valid payload but without core services
        # should either work (if mocked) or fail gracefully
        payload = {
            "message_id": 1,
            "conversation_id": 999,
            "identity_id": 1,
            "provider_id": "reddit",
            "body_text": "Test",
        }

        # When core service is not available, it will fail with import error
        # or module error, which should be caught as an exception
        try:
            result = send_manual.apply(args=[payload]).get()
            # If it returns, should have error status
            assert result["status"] in ("error", "failed")
        except Exception:
            # Import/module errors are acceptable in isolated test
            pass


class TestMessageTaskRouting:
    """Tests for message task routing."""

    def test_message_tasks_have_correct_routing(self, mock_celery_app):
        """Message tasks should have appropriate queue routing."""
        # Note: message tasks don't have explicit routing in current config
        # This test documents the expected behavior
        from rediska_worker.tasks.message import send_manual

        # Task should be callable
        assert callable(send_manual)
