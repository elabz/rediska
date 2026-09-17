"""Integration tests for conversation API routes."""

import pytest
from fastapi.testclient import TestClient

from rediska_core.api.deps import get_current_user
from rediska_core.domain.models import (
    Conversation,
    ExternalAccount,
    Identity,
    LocalUser,
    Message,
)


@pytest.fixture
def client(test_app):
    """Create an *unauthenticated* test client."""
    return TestClient(test_app)


@pytest.fixture
def auth_client(test_app, db_session):
    """Create a test client whose requests are authenticated.

    Every /conversations/* route depends on `CurrentUser`. Without this
    override each request stops at a 401 and the route body -- the thing these
    tests exist to cover -- never runs.
    """
    user = LocalUser(username="conversation_tester", password_hash="not-a-real-hash")
    db_session.add(user)
    db_session.flush()

    test_app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(test_app)
    test_app.dependency_overrides.pop(get_current_user, None)


class TestConversationEndpoints:
    """Tests for /conversations/* endpoints."""

    def test_send_message_endpoint_requires_auth(self, client):
        """POST /conversations/{id}/messages rejects unauthenticated callers."""
        response = client.post(
            "/conversations/1/messages",
            json={"body_text": "Hello"},
        )

        assert response.status_code == 401

    def test_get_pending_endpoint_requires_auth(self, client):
        """GET /conversations/{id}/pending rejects unauthenticated callers."""
        response = client.get("/conversations/1/pending")

        assert response.status_code == 401

    def test_retry_message_endpoint_requires_auth(self, client):
        """POST /conversations/{id}/messages/{id}/retry rejects unauthenticated."""
        response = client.post("/conversations/1/messages/1/retry")

        assert response.status_code == 401


class TestSendMessage:
    """Tests for sending messages through API."""

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

    def test_send_message_requires_body(self, auth_client):
        """Sending a message requires body_text."""
        response = auth_client.post(
            "/conversations/1/messages",
            json={},
        )

        assert response.status_code == 422
        assert ["body", "body_text"] in [e["loc"] for e in response.json()["detail"]]

    def test_send_message_to_nonexistent_conversation(self, auth_client):
        """Sending to non-existent conversation returns 404."""
        response = auth_client.post(
            "/conversations/99999/messages",
            json={"body_text": "Hello"},
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_send_message_empty_body_rejected(self, auth_client):
        """Empty message body should be rejected."""
        response = auth_client.post(
            "/conversations/1/messages",
            json={"body_text": ""},
        )

        # Rejected by the schema (body_text has min_length=1).
        assert response.status_code == 422

    def test_send_message_whitespace_only_rejected(
        self, auth_client, setup_conversation
    ):
        """Whitespace-only message body should be rejected."""
        conv = setup_conversation["conversation"]

        response = auth_client.post(
            f"/conversations/{conv.id}/messages",
            json={"body_text": "   "},
        )

        # Passes min_length but the service rejects it -> EmptyMessageError -> 400.
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_send_message_without_credentials_is_forbidden(
        self, auth_client, setup_conversation
    ):
        """An identity with no stored OAuth credentials cannot send."""
        conv = setup_conversation["conversation"]

        response = auth_client.post(
            f"/conversations/{conv.id}/messages",
            json={"body_text": "Hello"},
        )

        # MissingCredentialsError maps to 403.
        assert response.status_code == 403
        assert "credentials" in response.json()["detail"].lower()


class TestGetPendingMessages:
    """Tests for getting pending messages."""

    def test_get_pending_nonexistent_conversation(self, auth_client):
        """Getting pending for non-existent conversation returns an empty list."""
        response = auth_client.get("/conversations/99999/pending")

        assert response.status_code == 200
        assert response.json() == []

    def test_get_pending_returns_list(self, auth_client):
        """Pending messages endpoint returns a list."""
        response = auth_client.get("/conversations/1/pending")

        assert response.status_code == 200
        assert response.json() == []


class TestRetryMessage:
    """Tests for retrying failed messages."""

    def test_retry_nonexistent_message(self, auth_client):
        """Retrying non-existent message returns error."""
        response = auth_client.post("/conversations/1/messages/99999/retry")

        assert response.status_code == 400
        assert "cannot be retried" in response.json()["detail"].lower()


class TestConversationMessageFlow:
    """Tests for complete message sending flow."""

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
        self, auth_client, conversation_with_pending
    ):
        """Pending messages are those with unknown visibility."""
        conv = conversation_with_pending["conversation"]

        response = auth_client.get(f"/conversations/{conv.id}/pending")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["body_text"] == "Pending message"
        assert data[0]["remote_visibility"] == "unknown"
        assert data[0]["can_retry"] is True


class TestConversationValidation:
    """Tests for conversation API validation."""

    def test_conversation_id_must_be_integer(self, auth_client):
        """Conversation ID must be a valid integer."""
        response = auth_client.post(
            "/conversations/invalid/messages",
            json={"body_text": "Hello"},
        )

        assert response.status_code == 422

    def test_message_id_must_be_integer(self, auth_client):
        """Message ID must be a valid integer."""
        response = auth_client.post("/conversations/1/messages/invalid/retry")

        assert response.status_code == 422

    def test_attachment_ids_optional(self, auth_client):
        """Attachment IDs are optional in send request."""
        response = auth_client.post(
            "/conversations/1/messages",
            json={"body_text": "Hello", "attachment_ids": []},
        )

        # Conversation 1 does not exist -> 404, i.e. the empty attachment list
        # itself was accepted by the schema.
        assert response.status_code == 404


class TestListConversationsListFilter:
    """The list filter runs server-side, so members beyond the first page are found."""

    @pytest.fixture
    def many_conversations(self, db_session):
        from datetime import datetime, timedelta, timezone

        from rediska_core.domain.models import ConversationList, ConversationListMember, Provider

        db_session.add(Provider(provider_id="reddit", display_name="Reddit", enabled=True))
        db_session.flush()
        identity = Identity(
            provider_id="reddit",
            external_username="test_identity",
            external_user_id="t2_test_identity",
            display_name="Test Identity",
            is_default=True,
            is_active=True,
        )
        db_session.add(identity)
        db_session.flush()

        now = datetime.now(timezone.utc)
        conversations = []
        for i in range(60):
            account = ExternalAccount(
                provider_id="reddit",
                external_user_id=f"t2_test_{i}",
                external_username=f"test_user_{i}",
            )
            db_session.add(account)
            db_session.flush()
            conv = Conversation(
                provider_id="reddit",
                identity_id=identity.id,
                external_conversation_id=f"test_conv_{i}",
                counterpart_account_id=account.id,
            )
            db_session.add(conv)
            db_session.flush()
            # i=0 is the newest, i=59 the oldest
            db_session.add(Message(
                provider_id="reddit",
                conversation_id=conv.id,
                direction="in",
                body_text=f"test message {i}",
                remote_visibility="visible",
                sent_at=now - timedelta(hours=i),
            ))
            conversations.append(conv)

        lst = ConversationList(name="test_bad_contact")
        db_session.add(lst)
        db_session.flush()
        db_session.add(ConversationListMember(list_id=lst.id, conversation_id=conversations[59].id))
        db_session.commit()
        return {"list": lst, "oldest": conversations[59]}

    def test_member_beyond_first_page_is_returned(self, auth_client, many_conversations):
        unfiltered = auth_client.get("/conversations?limit=50").json()
        assert many_conversations["oldest"].id not in [c["id"] for c in unfiltered["conversations"]]

        response = auth_client.get(
            f"/conversations?limit=50&list_id={many_conversations['list'].id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert [c["id"] for c in data["conversations"]] == [many_conversations["oldest"].id]
        assert data["has_more"] is False
