"""Integration tests for Epic 5.2 - Manual Send Message endpoint.

Tests cover:
1. POST /conversations/{id}/messages - Queue message for sending
2. GET /conversations/{id}/pending - Get pending messages
3. POST /conversations/{id}/messages/{id}/retry - Retry failed send
"""

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from rediska_core.api.deps import get_current_user
from rediska_core.domain.models import (
    AuditLog,
    Conversation,
    ExternalAccount,
    Identity,
    Job,
    LocalUser,
    Message,
    Provider,
    ProviderCredential,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def setup_send_data(db_session, test_settings):
    """Set up complete data for send message tests."""
    from rediska_core.infrastructure.crypto import CryptoService

    # Create provider
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
        external_username="my_account",
        external_user_id="t2_myid",
        display_name="My Account",
        is_default=True,
        is_active=True,
    )
    db_session.add(identity)
    db_session.flush()

    # Create counterpart account
    counterpart = ExternalAccount(
        provider_id="reddit",
        external_username="counterpart_user",
        external_user_id="t2_other",
        remote_status="active",
    )
    db_session.add(counterpart)
    db_session.flush()

    # Create conversation
    conversation = Conversation(
        provider_id="reddit",
        identity_id=identity.id,
        counterpart_account_id=counterpart.id,
        external_conversation_id="conv_123",
    )
    db_session.add(conversation)
    db_session.flush()

    # Create credentials
    crypto = CryptoService(test_settings.encryption_key)
    encrypted_token = crypto.encrypt('{"access_token": "test", "refresh_token": "test"}')

    credential = ProviderCredential(
        provider_id="reddit",
        identity_id=identity.id,
        credential_type="oauth",
        secret_encrypted=encrypted_token,
    )
    db_session.add(credential)
    db_session.flush()

    return {
        "provider": provider,
        "identity": identity,
        "counterpart": counterpart,
        "conversation": conversation,
        "credential": credential,
    }


@pytest.fixture
def mock_user():
    """Create a mock authenticated user."""
    user = MagicMock(spec=LocalUser)
    user.id = 1
    user.username = "test_user"
    return user


@pytest.fixture
async def auth_client(test_app, db_session, mock_user):
    """Authenticated client so the send endpoints actually execute.

    Without this the send/pending/retry endpoints return 401/403 and the tests
    that used to guard on that skipped, leaving the endpoint uncovered.
    """
    test_app.dependency_overrides[get_current_user] = lambda: mock_user

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac

    test_app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def captured_celery_sends():
    """Intercept Celery dispatch so no broker is required.

    The route builds its own Celery app and calls send_task; the call is
    wrapped in try/except in the route, so without this patch a broker
    connection failure would be swallowed and we could not tell a dispatched
    send from a silently dropped one.
    """
    sends = []

    def fake_send_task(self, name, **kwargs):
        sends.append((name, kwargs))
        return MagicMock(id="fake-task-id")

    with patch("celery.Celery.send_task", new=fake_send_task):
        yield sends


# =============================================================================
# SEND MESSAGE ENDPOINT TESTS
# =============================================================================


class TestSendMessageEndpoint:
    """Tests for POST /conversations/{id}/messages endpoint."""

    @pytest.mark.asyncio
    async def test_send_requires_authentication(self, client):
        """Send endpoint should require authentication."""
        response = await client.post(
            "/conversations/1/messages",
            json={"body_text": "Hello!"},
        )

        assert response.status_code in (401, 403, 404)

    @pytest.mark.asyncio
    async def test_send_returns_404_for_missing_conversation(
        self, auth_client, setup_send_data, captured_celery_sends
    ):
        """Send to non-existent conversation should return 404 and dispatch nothing."""
        response = await auth_client.post(
            "/conversations/99999/messages",
            json={"body_text": "Hello!"},
        )

        assert response.status_code == 404
        assert captured_celery_sends == []

    @pytest.mark.asyncio
    async def test_send_returns_409_for_deleted_counterpart(
        self, auth_client, db_session, setup_send_data, captured_celery_sends
    ):
        """Send to deleted counterpart should return 409 Conflict."""
        counterpart = setup_send_data["counterpart"]
        counterpart.remote_status = "deleted"
        db_session.flush()

        response = await auth_client.post(
            f"/conversations/{setup_send_data['conversation'].id}/messages",
            json={"body_text": "Hello!"},
        )

        assert response.status_code == 409
        # No message row and no dispatch may result from a blocked counterpart.
        assert db_session.query(Message).count() == 0
        assert captured_celery_sends == []

    @pytest.mark.asyncio
    async def test_send_returns_422_for_empty_body(
        self, auth_client, db_session, setup_send_data, captured_celery_sends
    ):
        """Empty body is rejected by the request schema (min_length=1)."""
        response = await auth_client.post(
            f"/conversations/{setup_send_data['conversation'].id}/messages",
            json={"body_text": ""},
        )

        assert response.status_code == 422
        assert db_session.query(Message).count() == 0
        assert captured_celery_sends == []

    @pytest.mark.asyncio
    async def test_send_returns_403_without_credentials(
        self, auth_client, db_session, setup_send_data, captured_celery_sends
    ):
        """An identity with no stored OAuth credentials cannot send."""
        db_session.delete(setup_send_data["credential"])
        db_session.flush()

        response = await auth_client.post(
            f"/conversations/{setup_send_data['conversation'].id}/messages",
            json={"body_text": "Hello!"},
        )

        assert response.status_code == 403
        assert captured_celery_sends == []

    @pytest.mark.asyncio
    async def test_send_queues_message_and_dispatches_once(
        self, auth_client, db_session, setup_send_data, captured_celery_sends
    ):
        """Happy path: 202 + queued job + pending message + exactly one dispatch."""
        conversation = setup_send_data["conversation"]

        response = await auth_client.post(
            f"/conversations/{conversation.id}/messages",
            json={"body_text": "  Hello there!  "},
        )

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "queued"
        assert isinstance(body["job_id"], int)
        assert isinstance(body["message_id"], int)

        # Message is persisted as an unsent outgoing message. 'unknown' (not
        # 'visible') is the at-most-once contract: the API never claims a send
        # it has not confirmed.
        message = db_session.query(Message).filter(
            Message.id == body["message_id"]
        ).first()
        assert message is not None
        assert message.direction == "out"
        assert message.body_text == "Hello there!"  # stripped
        assert message.remote_visibility == "unknown"
        assert message.external_message_id is None
        assert message.identity_id == setup_send_data["identity"].id

        # Job ledger entry exists and is queued, not executed inline.
        job = db_session.query(Job).filter(Job.id == body["job_id"]).first()
        assert job is not None
        assert job.job_type == "message.send_manual"
        assert job.queue_name == "messages"
        assert job.status == "queued"
        assert job.payload_json["message_id"] == body["message_id"]

        # NO AUTOSEND: the HTTP call dispatches the send task exactly once,
        # and only because the user explicitly POSTed.
        assert len(captured_celery_sends) == 1
        name, kwargs = captured_celery_sends[0]
        assert name == "message.send_manual"
        assert kwargs["queue"] == "messages"
        assert kwargs["kwargs"]["payload"]["message_id"] == body["message_id"]

        # Mutating endpoint must be audited.
        audit = db_session.query(AuditLog).filter(
            AuditLog.action_type == "message.send"
        ).all()
        assert len(audit) == 1
        assert audit[0].result == "ok"
        assert audit[0].entity_type == "message"
        assert audit[0].entity_id == body["message_id"]


# =============================================================================
# PENDING MESSAGES ENDPOINT TESTS
# =============================================================================


class TestPendingMessagesEndpoint:
    """Tests for GET /conversations/{id}/pending endpoint."""

    @pytest.mark.asyncio
    async def test_pending_requires_authentication(self, client):
        """Pending endpoint should require authentication."""
        response = await client.get("/conversations/1/pending")

        assert response.status_code in (401, 403, 404)

    @pytest.mark.asyncio
    async def test_pending_lists_only_unsent_outgoing_messages(
        self, auth_client, db_session, setup_send_data, captured_celery_sends
    ):
        """A queued send shows up as pending until it is confirmed sent."""
        conversation = setup_send_data["conversation"]

        send = await auth_client.post(
            f"/conversations/{conversation.id}/messages",
            json={"body_text": "Still pending"},
        )
        message_id = send.json()["message_id"]

        response = await auth_client.get(f"/conversations/{conversation.id}/pending")
        assert response.status_code == 200
        pending = response.json()
        assert [p["id"] for p in pending] == [message_id]
        assert pending[0]["remote_visibility"] == "unknown"
        assert pending[0]["can_retry"] is True

        # Once confirmed sent it must drop off the pending list, otherwise a
        # user could be prompted to re-send an already-delivered message.
        db_session.query(Message).filter(Message.id == message_id).update(
            {Message.remote_visibility: "visible"}, synchronize_session=False
        )
        db_session.commit()

        response = await auth_client.get(f"/conversations/{conversation.id}/pending")
        assert response.status_code == 200
        assert response.json() == []


# =============================================================================
# RETRY MESSAGE ENDPOINT TESTS
# =============================================================================


class TestRetryMessageEndpoint:
    """Tests for POST /conversations/{id}/messages/{id}/retry endpoint."""

    @pytest.mark.asyncio
    async def test_retry_requires_authentication(self, client):
        """Retry endpoint should require authentication."""
        response = await client.post("/conversations/1/messages/1/retry")

        assert response.status_code in (401, 403, 404)

    @pytest.mark.asyncio
    async def test_retry_of_pending_message_creates_single_attempt_job(
        self, auth_client, db_session, setup_send_data, captured_celery_sends
    ):
        """Manual retry is explicit, creates a NEW job, and stays at-most-once."""
        conversation = setup_send_data["conversation"]

        send = await auth_client.post(
            f"/conversations/{conversation.id}/messages",
            json={"body_text": "Retry me"},
        )
        message_id = send.json()["message_id"]
        original_job_id = send.json()["job_id"]
        assert len(captured_celery_sends) == 1

        response = await auth_client.post(
            f"/conversations/{conversation.id}/messages/{message_id}/retry"
        )

        assert response.status_code == 202
        body = response.json()
        assert body["message_id"] == message_id
        assert body["job_id"] != original_job_id
        assert body["status"] == "queued"

        job = db_session.query(Job).filter(Job.id == body["job_id"]).first()
        assert job is not None
        assert job.status == "queued"
        # max_attempts=1 keeps a manual retry from silently re-sending on failure.
        assert job.max_attempts == 1
        assert job.payload_json["is_retry"] is True
        assert job.payload_json["message_id"] == message_id

        # The retry dispatched exactly one additional task (2 total), never more.
        assert len(captured_celery_sends) == 2
        assert captured_celery_sends[1][0] == "message.send_manual"

    @pytest.mark.asyncio
    async def test_retry_rejected_for_already_sent_message(
        self, auth_client, db_session, setup_send_data, captured_celery_sends
    ):
        """A confirmed-sent message must never be re-sendable (at-most-once)."""
        conversation = setup_send_data["conversation"]

        send = await auth_client.post(
            f"/conversations/{conversation.id}/messages",
            json={"body_text": "Already delivered"},
        )
        message_id = send.json()["message_id"]

        db_session.query(Message).filter(Message.id == message_id).update(
            {Message.remote_visibility: "visible"}, synchronize_session=False
        )
        db_session.commit()

        dispatches_before = len(captured_celery_sends)
        response = await auth_client.post(
            f"/conversations/{conversation.id}/messages/{message_id}/retry"
        )

        assert response.status_code == 400
        # Critically: no new job and no new dispatch for a delivered message.
        assert len(captured_celery_sends) == dispatches_before
        assert db_session.query(Job).filter(
            Job.job_type == "message.send_manual"
        ).count() == 1
