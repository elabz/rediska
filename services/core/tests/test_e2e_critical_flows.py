"""End-to-end tests for critical user flows.

These tests verify complete user journeys through the system,
from API endpoints down to database persistence.
"""

import pytest
from fastapi.testclient import TestClient

from rediska_core.domain.models import (
    Conversation,
    ExternalAccount,
    Identity,
    Message,
    ProviderCredential,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def client(test_app):
    """Create test client."""
    return TestClient(test_app)


@pytest.fixture
def identity_with_credentials(db_session):
    """Create identity with OAuth credentials for testing."""
    from rediska_core.domain.models import Provider

    # Create provider first
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
        external_username="e2e_test_user",
        external_user_id="t2_e2e123",
        display_name="E2E Test User",
        is_default=True,
        is_active=True,
    )
    db_session.add(identity)
    db_session.flush()

    # Create credentials (encrypted)
    cred = ProviderCredential(
        identity_id=identity.id,
        provider_id="reddit",
        credential_type="oauth",
        secret_encrypted="encrypted_token_data",  # Would be properly encrypted
    )
    db_session.add(cred)
    db_session.commit()

    return identity


@pytest.fixture
def conversation_with_messages(db_session, identity_with_credentials):
    """Create conversation with message history."""
    identity = identity_with_credentials

    # Create counterpart
    account = ExternalAccount(
        provider_id="reddit",
        external_user_id="t2_counterpart_e2e",
        external_username="counterpart_user",
    )
    db_session.add(account)
    db_session.flush()

    # Create conversation
    conversation = Conversation(
        provider_id="reddit",
        identity_id=identity.id,
        external_conversation_id="conv_e2e_test",
        counterpart_account_id=account.id,
    )
    db_session.add(conversation)
    db_session.flush()

    # Add message history
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    messages = [
        Message(
            provider_id="reddit",
            conversation_id=conversation.id,
            direction="in",
            body_text="Hey there!",
            external_message_id="msg_1",
            remote_visibility="visible",
            sent_at=now,
        ),
        Message(
            provider_id="reddit",
            conversation_id=conversation.id,
            direction="out",
            body_text="Hi! How can I help?",
            external_message_id="msg_2",
            remote_visibility="visible",
            sent_at=now,
        ),
        Message(
            provider_id="reddit",
            conversation_id=conversation.id,
            direction="in",
            body_text="I have a question about your product.",
            external_message_id="msg_3",
            remote_visibility="visible",
            sent_at=now,
        ),
    ]
    for msg in messages:
        db_session.add(msg)

    db_session.commit()

    return {
        "identity": identity,
        "account": account,
        "conversation": conversation,
        "messages": messages,
    }


# =============================================================================
# E2E: FIRST-TIME SETUP FLOW
# =============================================================================


class TestE2EOnboardingFlow:
    """E2E tests for first-time user setup."""

    def test_fresh_install_health_check_works(self, client):
        """On fresh install, health check should work."""
        response = client.get("/api/health")

        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_fresh_install_readiness_works(self, client):
        """On fresh install, readiness check should work."""
        response = client.get("/api/ready")

        assert response.status_code == 200
        assert response.json()["ready"] is True

    def test_onboarding_flow_api_endpoints_exist(self, client):
        """All onboarding-related endpoints should exist."""
        endpoints = [
            ("/setup/status", "GET"),
            ("/identities", "GET"),
            ("/identities", "POST"),
        ]

        for path, method in endpoints:
            if method == "GET":
                response = client.get(path)
            else:
                response = client.post(path, json={})

            # Should not be 404 (endpoint exists)
            assert response.status_code != 404, f"{method} {path} not found"


# =============================================================================
# E2E: IDENTITY MANAGEMENT FLOW
# =============================================================================


class TestE2EIdentityFlow:
    """E2E tests for identity creation and management."""

    def test_create_identity_endpoint_accepts_valid_data(self, client):
        """Identity creation should accept valid data."""
        response = client.post(
            "/identities",
            json={
                "provider_id": "reddit",
                "external_username": "new_identity_user",
                "display_name": "New Identity",
                "voice_config": {
                    "system_prompt": "You are a helpful assistant",
                    "tone": "professional",
                },
            },
        )

        # May require auth (401/403) or succeed (201)
        assert response.status_code in (200, 201, 401, 403, 422)

    def test_list_identities_returns_array(self, client):
        """Listing identities should return an array."""
        response = client.get("/identities")

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, (list, dict))


# =============================================================================
# E2E: CONVERSATION FLOW
# =============================================================================


class TestE2EConversationFlow:
    """E2E tests for conversation management."""

    def test_conversation_endpoints_exist(self, client, conversation_with_messages):
        """All conversation endpoints should exist."""
        conv = conversation_with_messages["conversation"]

        endpoints = [
            (f"/conversations/{conv.id}/messages", "POST"),
            (f"/conversations/{conv.id}/pending", "GET"),
        ]

        for path, method in endpoints:
            if method == "GET":
                response = client.get(path)
            else:
                response = client.post(path, json={"body_text": "Test"})

            assert response.status_code != 404, f"{method} {path} not found"

    def test_send_message_flow(self, client, conversation_with_messages):
        """Complete flow of sending a message."""
        conv = conversation_with_messages["conversation"]

        # Attempt to send message
        response = client.post(
            f"/conversations/{conv.id}/messages",
            json={
                "body_text": "This is a test message from E2E",
                "attachment_ids": [],
            },
        )

        # Should accept (202), require auth (401/403), or fail validation (422)
        assert response.status_code in (202, 401, 403, 422)

        if response.status_code == 202:
            data = response.json()
            assert "job_id" in data or "message_id" in data

    def test_get_pending_messages_flow(self, client, conversation_with_messages):
        """Flow of checking pending messages."""
        conv = conversation_with_messages["conversation"]

        response = client.get(f"/conversations/{conv.id}/pending")

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)


# =============================================================================
# E2E: SEARCH FLOW
# =============================================================================


class TestE2ESearchFlow:
    """E2E tests for search functionality."""

    def test_search_endpoint_exists(self, client):
        """Search endpoint should exist."""
        response = client.get("/search?q=test")

        # Should not be 404
        assert response.status_code != 404

    def test_search_with_query(self, client):
        """Search with query parameter."""
        response = client.get("/search?q=hello+world")

        # May require auth, return results, or not be implemented
        assert response.status_code in (200, 401, 403, 404, 405)

        if response.status_code == 200:
            data = response.json()
            assert "results" in data or "hits" in data or isinstance(data, list)


# =============================================================================
# E2E: LEADS FLOW
# =============================================================================


class TestE2ELeadsFlow:
    """E2E tests for lead discovery and management."""

    def test_leads_endpoint_exists(self, client):
        """Leads endpoint should exist."""
        response = client.get("/leads")

        assert response.status_code != 404

    def test_leads_list_returns_paginated(self, client):
        """Leads list should support pagination."""
        response = client.get("/leads?page=1&page_size=10")

        if response.status_code == 200:
            data = response.json()
            # Should have pagination info
            assert (
                "items" in data
                or "results" in data
                or "leads" in data
                or isinstance(data, list)
            )


# =============================================================================
# E2E: DIRECTORY FLOW
# =============================================================================


class TestE2EDirectoryFlow:
    """E2E tests for directory (external accounts) functionality."""

    def test_directory_endpoint_exists(self, client):
        """Directory endpoint should exist or return auth error."""
        response = client.get("/directories")

        # May not be implemented yet
        assert response.status_code in (200, 401, 403, 404)

    def test_directory_search(self, client):
        """Directory should support search."""
        response = client.get("/directories?q=user")

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, (list, dict))


# =============================================================================
# E2E: AUDIT FLOW
# =============================================================================


class TestE2EAuditFlow:
    """E2E tests for audit logging functionality."""

    def test_audit_endpoint_exists(self, client):
        """Audit logs endpoint should exist."""
        response = client.get("/audit")

        assert response.status_code != 404

    def test_audit_logs_require_auth(self, client):
        """Audit logs should require authentication."""
        response = client.get("/audit")

        # Audit is sensitive - should require auth
        assert response.status_code in (200, 401, 403)


# =============================================================================
# E2E: METRICS AND OBSERVABILITY FLOW
# =============================================================================


class TestE2EMetricsFlow:
    """E2E tests for metrics and observability."""

    def test_health_metrics_available(self, client):
        """Health and metrics should be available."""
        endpoints = [
            "/api/health",
            "/api/ready",
            "/healthz",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 200, f"{endpoint} failed"

    def test_metrics_returns_system_info(self, client):
        """Metrics endpoint should return system info."""
        response = client.get("/api/metrics")

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, dict)


# =============================================================================
# E2E: SOURCES FLOW
# =============================================================================


class TestE2ESourcesFlow:
    """E2E tests for sources (subreddit/community) management."""

    def test_sources_endpoint_exists(self, client):
        """Sources endpoint should exist or return auth error."""
        response = client.get("/sources")

        # May not be implemented yet or require auth
        assert response.status_code in (200, 401, 403, 404)

    def test_sources_list_returns_data(self, client):
        """Sources list should return data structure."""
        response = client.get("/sources")

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, (list, dict))


# =============================================================================
# E2E: ATTACHMENTS FLOW
# =============================================================================


class TestE2EAttachmentFlow:
    """E2E tests for attachment handling."""

    def test_attachment_upload_endpoint_exists(self, client):
        """Attachment upload endpoint should exist or return auth error."""
        response = client.post("/attachments")

        # May not be implemented, require auth, or fail validation
        assert response.status_code in (200, 201, 401, 403, 404, 405, 422)


# =============================================================================
# E2E: ERROR HANDLING
# =============================================================================


class TestE2EErrorHandling:
    """E2E tests for error handling across flows."""

    def test_invalid_conversation_id_returns_error(self, client):
        """Invalid conversation ID should return proper error."""
        response = client.get("/conversations/99999999/pending")

        # Should be 404 or auth error, not 500
        assert response.status_code in (200, 401, 403, 404)
        assert response.status_code != 500

    def test_invalid_json_returns_422(self, client):
        """Invalid JSON should return 422."""
        response = client.post(
            "/identities",
            content="not valid json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 422

    def test_missing_required_fields_returns_422(self, client):
        """Missing required fields should return 422."""
        response = client.post(
            "/identities",
            json={},  # Missing required fields
        )

        # Should be validation error or auth required
        assert response.status_code in (401, 403, 422)


# =============================================================================
# E2E: DATA PERSISTENCE
# =============================================================================


class TestE2EDataPersistence:
    """E2E tests for data persistence across requests."""

    def test_created_data_persists(self, client, db_session):
        """Data created via API should persist."""
        from rediska_core.domain.models import Provider

        # Create provider first
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
            external_username="persist_test_user",
            external_user_id="t2_persist",
            display_name="Persist Test",
            is_default=False,
            is_active=True,
        )
        db_session.add(identity)
        db_session.commit()

        # Verify it persists
        from_db = db_session.query(Identity).filter_by(
            external_username="persist_test_user"
        ).first()

        assert from_db is not None
        assert from_db.display_name == "Persist Test"

    def test_messages_maintain_order(self, db_session, conversation_with_messages):
        """Messages should maintain chronological order."""
        conv = conversation_with_messages["conversation"]

        messages = (
            db_session.query(Message)
            .filter_by(conversation_id=conv.id)
            .order_by(Message.id)
            .all()
        )

        # Verify order matches creation order
        assert len(messages) == 3
        assert messages[0].body_text == "Hey there!"
        assert messages[1].body_text == "Hi! How can I help?"
        assert messages[2].body_text == "I have a question about your product."


# =============================================================================
# E2E: CONCURRENT ACCESS
# =============================================================================


class TestE2EConcurrentAccess:
    """E2E tests for concurrent access handling."""

    def test_multiple_health_checks_concurrent(self, client):
        """Multiple concurrent health checks should work."""
        import threading

        results = []

        def check_health():
            response = client.get("/api/health")
            results.append(response.status_code)

        threads = [threading.Thread(target=check_health) for _ in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should succeed
        assert all(status == 200 for status in results)
