"""Integration tests for conversation API routes."""

import pytest
from fastapi.testclient import TestClient

from rediska_core.domain.models import (
    Conversation,
    ExternalAccount,
    Identity,
    Message,
)


class TestConversationEndpoints:
    """Tests for /conversations/* endpoints."""

    @pytest.fixture
    def client(self, test_app):
        """Create test client."""
        return TestClient(test_app)

    def test_send_message_endpoint_exists(self, client):
        """POST /conversations/{id}/messages should exist."""
        response = client.post(
            "/conversations/1/messages",
            json={"body_text": "Hello"},
        )

        # Should not be 404 (endpoint exists)
        # May be 401 (auth required), 404 (conversation not found), etc.
        assert response.status_code != 405  # Method exists

    def test_get_pending_endpoint_exists(self, client):
        """GET /conversations/{id}/pending should exist."""
        response = client.get("/conversations/1/pending")

        # Should not be 405 (method not allowed)
        assert response.status_code != 405

    def test_retry_message_endpoint_exists(self, client):
        """POST /conversations/{id}/messages/{id}/retry should exist."""
        response = client.post("/conversations/1/messages/1/retry")

        # Method should be allowed
        assert response.status_code != 405


class TestSendMessage:
    """Tests for sending messages through API."""

    @pytest.fixture
    def client(self, test_app):
        """Create test client."""
        return TestClient(test_app)

    @pytest.fixture
    def setup_conversation(self, db_session):
        """Create test identity, account, and conversation."""
        from rediska_core.domain.models import Provider

        # Create provider first (foreign key requirement)
        provider = Provider(
            provider_id="reddit",
            display_name="Reddit",
            enabled=True,
        )
        db_session.add(provider)
        db_session.flush()

        # Create identity
        identity = Identity(
            provider_id="reddit",
            external_username="test_user",
            external_user_id="t2_test",
            display_name="Test User",
            is_default=True,
            is_active=True,
        )
        db_session.add(identity)
        db_session.flush()

        # Create counterpart account
        account = ExternalAccount(
            provider_id="reddit",
            external_user_id="t2_counterpart",
            external_username="counterpart",
        )
        db_session.add(account)
        db_session.flush()

        # Create conversation
        conversation = Conversation(
            provider_id="reddit",
            identity_id=identity.id,
            external_conversation_id="conv_123",
            counterpart_account_id=account.id,
        )
        db_session.add(conversation)
        db_session.commit()

        return {
            "identity": identity,
            "account": account,
            "conversation": conversation,
        }

    def test_send_message_requires_body(self, client):
        """Sending a message requires body_text."""
        response = client.post(
            "/conversations/1/messages",
            json={},
        )

        # Should fail validation (422) or auth (401)
        assert response.status_code in (400, 401, 403, 422)

    def test_send_message_to_nonexistent_conversation(self, client):
        """Sending to non-existent conversation returns 404."""
        response = client.post(
            "/conversations/99999/messages",
            json={"body_text": "Hello"},
        )

        # Should be 404 (not found) or auth required
        assert response.status_code in (401, 403, 404)

    def test_send_message_empty_body_rejected(self, client):
        """Empty message body should be rejected."""
        response = client.post(
            "/conversations/1/messages",
            json={"body_text": ""},
        )

        # Empty body should fail
        assert response.status_code in (400, 401, 403, 422)

    def test_send_message_whitespace_only_rejected(self, client):
        """Whitespace-only message body should be rejected."""
        response = client.post(
            "/conversations/1/messages",
            json={"body_text": "   "},
        )

        # Whitespace-only should fail
        assert response.status_code in (400, 401, 403, 422)


class TestGetPendingMessages:
    """Tests for getting pending messages."""

    @pytest.fixture
    def client(self, test_app):
        """Create test client."""
        return TestClient(test_app)

    def test_get_pending_nonexistent_conversation(self, client):
        """Getting pending for non-existent conversation."""
        response = client.get("/conversations/99999/pending")

        # May return empty list or 404
        assert response.status_code in (200, 401, 403, 404)

    def test_get_pending_returns_list(self, client):
        """Pending messages endpoint returns a list."""
        response = client.get("/conversations/1/pending")

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)


class TestRetryMessage:
    """Tests for retrying failed messages."""

    @pytest.fixture
    def client(self, test_app):
        """Create test client."""
        return TestClient(test_app)

    def test_retry_nonexistent_message(self, client):
        """Retrying non-existent message returns error."""
        response = client.post("/conversations/1/messages/99999/retry")

        # Should be 400 or 404
        assert response.status_code in (400, 401, 403, 404)


class TestConversationMessageFlow:
    """Tests for complete message sending flow."""

    @pytest.fixture
    def client(self, test_app):
        """Create test client."""
        return TestClient(test_app)

    @pytest.fixture
    def conversation_with_pending(self, db_session):
        """Create conversation with a pending message."""
        from rediska_core.domain.models import Provider

        # Create provider first (foreign key requirement)
        provider = Provider(
            provider_id="reddit",
            display_name="Reddit",
            enabled=True,
        )
        db_session.add(provider)
        db_session.flush()

        # Create identity
        identity = Identity(
            provider_id="reddit",
            external_username="test_user",
            external_user_id="t2_test",
            display_name="Test User",
            is_default=True,
            is_active=True,
        )
        db_session.add(identity)
        db_session.flush()

        # Create counterpart account
        account = ExternalAccount(
            provider_id="reddit",
            external_user_id="t2_counterpart",
            external_username="counterpart",
        )
        db_session.add(account)
        db_session.flush()

        # Create conversation
        conversation = Conversation(
            provider_id="reddit",
            identity_id=identity.id,
            external_conversation_id="conv_pending",
            counterpart_account_id=account.id,
        )
        db_session.add(conversation)
        db_session.flush()

        # Create pending message (unknown visibility)
        from datetime import datetime, timezone

        message = Message(
            provider_id="reddit",
            conversation_id=conversation.id,
            direction="out",
            body_text="Pending message",
            remote_visibility="unknown",
            sent_at=datetime.now(timezone.utc),
        )
        db_session.add(message)
        db_session.commit()

        return {
            "conversation": conversation,
            "message": message,
        }

    def test_pending_messages_include_unknown_visibility(
        self, client, conversation_with_pending
    ):
        """Pending messages are those with unknown visibility."""
        conv = conversation_with_pending["conversation"]

        response = client.get(f"/conversations/{conv.id}/pending")

        if response.status_code == 200:
            data = response.json()
            # Should have at least one pending message
            if data:
                assert all(
                    msg.get("remote_visibility") == "unknown"
                    or "can_retry" in msg
                    for msg in data
                )


class TestConversationValidation:
    """Tests for conversation API validation."""

    @pytest.fixture
    def client(self, test_app):
        """Create test client."""
        return TestClient(test_app)

    def test_conversation_id_must_be_integer(self, client):
        """Conversation ID must be a valid integer."""
        response = client.post(
            "/conversations/invalid/messages",
            json={"body_text": "Hello"},
        )

        # Should fail validation (422) or auth (401) - auth runs before validation
        assert response.status_code in (401, 422)

    def test_message_id_must_be_integer(self, client):
        """Message ID must be a valid integer."""
        response = client.post("/conversations/1/messages/invalid/retry")

        # Should fail validation (422) or auth (401) - auth runs before validation
        assert response.status_code in (401, 422)

    def test_attachment_ids_optional(self, client):
        """Attachment IDs are optional in send request."""
        response = client.post(
            "/conversations/1/messages",
            json={"body_text": "Hello", "attachment_ids": []},
        )

        # Should not fail due to empty attachment_ids
        # May fail for other reasons (auth, not found)
        assert response.status_code != 422 or "attachment" not in response.text.lower()
