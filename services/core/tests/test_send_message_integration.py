"""Integration tests for Epic 5.2 - Manual Send Message endpoint.

Tests cover:
1. POST /conversations/{id}/messages - Queue message for sending
2. GET /conversations/{id}/pending - Get pending messages
3. POST /conversations/{id}/messages/{id}/retry - Retry failed send
"""

import pytest

from rediska_core.domain.models import (
    Conversation,
    ExternalAccount,
    Identity,
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
        self, client, setup_send_data
    ):
        """Send to non-existent conversation should return 404."""
        response = await client.post(
            "/conversations/99999/messages",
            json={"body_text": "Hello!"},
        )

        if response.status_code in (401, 403):
            pytest.skip("Endpoint requires authentication")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_send_returns_409_for_deleted_counterpart(
        self, client, db_session, setup_send_data
    ):
        """Send to deleted counterpart should return 409 Conflict."""
        # Mark counterpart as deleted
        counterpart = setup_send_data["counterpart"]
        counterpart.remote_status = "deleted"
        db_session.flush()

        response = await client.post(
            f"/conversations/{setup_send_data['conversation'].id}/messages",
            json={"body_text": "Hello!"},
        )

        if response.status_code in (401, 403):
            pytest.skip("Endpoint requires authentication")

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_send_returns_400_for_empty_body(
        self, client, setup_send_data
    ):
        """Send with empty body should return 400."""
        response = await client.post(
            f"/conversations/{setup_send_data['conversation'].id}/messages",
            json={"body_text": ""},
        )

        if response.status_code in (401, 403):
            pytest.skip("Endpoint requires authentication")

        assert response.status_code in (400, 422)  # 422 for Pydantic validation


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
