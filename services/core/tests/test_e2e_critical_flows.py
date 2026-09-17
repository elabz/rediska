"""End-to-end tests for critical user flows.

These tests verify complete user journeys through the system,
from API endpoints down to database persistence.
"""

import pytest
from fastapi.testclient import TestClient

from rediska_core.api.deps import get_current_user
from rediska_core.domain.models import (
    Conversation,
    ExternalAccount,
    Identity,
    LocalUser,
    Message,
    ProviderCredential,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def client(test_app):
    """Create an *unauthenticated* test client."""
    return TestClient(test_app)


@pytest.fixture
def auth_client(test_app, db_session):
    """Create a test client whose requests are authenticated.

    The shared `client` fixture carries no session cookie, so every endpoint
    guarded by `CurrentUser` answers 401 and the request never reaches the
    route body. Overriding `get_current_user` is how the rest of this suite
    (see tests/test_sources_integration.py) exercises protected routes.

    No `session` cookie is set, which also means OnboardingGateMiddleware
    short-circuits before its identity check -- the gate only engages for
    cookie-bearing requests.
    """
    user = LocalUser(username="e2e_tester", password_hash="not-a-real-hash")
    db_session.add(user)
    db_session.flush()

    test_app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(test_app)
    test_app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def reddit_provider(db_session):
    """Create the reddit provider row that identity creation requires."""
    from rediska_core.domain.models import Provider

    provider = Provider(provider_id="reddit", display_name="Reddit", enabled=True)
    db_session.add(provider)
    db_session.commit()
    return provider


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

    def test_onboarding_endpoints_require_authentication(self, client):
        """All onboarding-related endpoints reject unauthenticated callers."""
        assert client.get("/setup/status").status_code == 401
        assert client.get("/identities").status_code == 401
        assert client.post("/identities", json={}).status_code == 401

    def test_onboarding_endpoints_reachable_when_authenticated(self, auth_client):
        """With auth, the onboarding endpoints execute their route bodies."""
        status_response = auth_client.get("/setup/status")
        assert status_response.status_code == 200
        assert status_response.json() == {"has_identity": False, "is_complete": False}

        list_response = auth_client.get("/identities")
        assert list_response.status_code == 200
        assert list_response.json() == {"identities": [], "total": 0}

        # An empty body now fails schema validation rather than auth, which
        # proves the request reached the route.
        assert auth_client.post("/identities", json={}).status_code == 422


# =============================================================================
# E2E: IDENTITY MANAGEMENT FLOW
# =============================================================================


class TestE2EIdentityFlow:
    """E2E tests for identity creation and management."""

    def test_create_identity_endpoint_accepts_valid_data(
        self, auth_client, reddit_provider
    ):
        """Identity creation should accept valid data."""
        response = auth_client.post(
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

        assert response.status_code == 201
        data = response.json()
        assert data["external_username"] == "new_identity_user"
        assert data["display_name"] == "New Identity"
        assert data["voice_config"]["tone"] == "professional"

    def test_list_identities_returns_array(self, auth_client, identity_with_credentials):
        """Listing identities should return an array."""
        response = auth_client.get("/identities")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert [i["external_username"] for i in data["identities"]] == [
            "e2e_test_user"
        ]


# =============================================================================
# E2E: CONVERSATION FLOW
# =============================================================================


class TestE2EConversationFlow:
    """E2E tests for conversation management."""

    def test_conversation_endpoints_require_authentication(
        self, client, conversation_with_messages
    ):
        """Conversation endpoints exist and reject unauthenticated callers."""
        conv = conversation_with_messages["conversation"]

        send = client.post(
            f"/conversations/{conv.id}/messages", json={"body_text": "Test"}
        )
        assert send.status_code == 401

        pending = client.get(f"/conversations/{conv.id}/pending")
        assert pending.status_code == 401

    def test_send_message_flow(self, auth_client, conversation_with_messages):
        """Complete flow of sending a message."""
        from unittest.mock import patch

        conv = conversation_with_messages["conversation"]

        # No broker is running under pytest; without this the route spends ~20s
        # in Celery's connection retries before swallowing the error.
        with patch("celery.Celery.send_task") as send_task:
            response = auth_client.post(
                f"/conversations/{conv.id}/messages",
                json={
                    "body_text": "This is a test message from E2E",
                    "attachment_ids": [],
                },
            )

        # 202: the send is queued for the worker, never performed inline.
        assert response.status_code == 202
        data = response.json()
        assert isinstance(data["job_id"], int)
        assert isinstance(data["message_id"], int)
        assert data["status"] == "queued"

        # The task must actually be handed to the worker queue.
        send_task.assert_called_once()
        assert send_task.call_args.args[0] == "message.send_manual"
        assert send_task.call_args.kwargs["queue"] == "messages"

    def test_get_pending_messages_flow(self, auth_client, conversation_with_messages):
        """Flow of checking pending messages."""
        conv = conversation_with_messages["conversation"]

        response = auth_client.get(f"/conversations/{conv.id}/pending")

        assert response.status_code == 200
        # The fixture's messages are all 'visible', so nothing is pending yet.
        assert response.json() == []


# =============================================================================
# E2E: SEARCH FLOW
# =============================================================================


class TestE2ESearchFlow:
    """E2E tests for search functionality."""

    def test_search_is_post_only(self, client):
        """/search is declared POST-only, so GET is 405 (not 404)."""
        response = client.get("/search?q=test")

        assert response.status_code == 405

    def test_search_requires_authentication(self, client):
        """Search should reject unauthenticated callers."""
        response = client.post("/search", json={"query": "hello world"})

        assert response.status_code == 401

    def test_search_with_query(self, test_app, auth_client):
        """Search returns the hybrid-search results in the response envelope."""
        from rediska_core.api.routes.search import get_search_service

        class StubSearchService:
            """Stands in for Elasticsearch, which is not running under pytest."""

            def hybrid_search(self, **kwargs):
                assert kwargs["query"] == "hello world"
                return {
                    "total": 1,
                    "max_score": 1.5,
                    "hits": [
                        {"id": "message:1", "score": 1.5, "source": {"body": "hello"}}
                    ],
                }

        test_app.dependency_overrides[get_search_service] = StubSearchService
        try:
            response = auth_client.post("/search", json={"query": "hello world"})
        finally:
            test_app.dependency_overrides.pop(get_search_service, None)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["max_score"] == 1.5
        assert data["hits"][0]["id"] == "message:1"
        assert data["hits"][0]["source"] == {"body": "hello"}


# =============================================================================
# E2E: LEADS FLOW
# =============================================================================


class TestE2ELeadsFlow:
    """E2E tests for lead discovery and management."""

    def test_leads_endpoint_requires_authentication(self, client):
        """Leads endpoint exists and rejects unauthenticated callers."""
        response = client.get("/leads")

        assert response.status_code == 401

    def test_leads_list_returns_paginated(self, auth_client):
        """Leads list should support pagination."""
        response = auth_client.get("/leads?offset=0&limit=10")

        assert response.status_code == 200
        data = response.json()
        assert data == {"leads": [], "total": 0}


# =============================================================================
# E2E: DIRECTORY FLOW
# =============================================================================


class TestE2EDirectoryFlow:
    """E2E tests for directory (external accounts) functionality."""

    def test_directory_endpoints_require_authentication(self, client):
        """Directory endpoints reject unauthenticated callers."""
        assert client.get("/directories/analyzed").status_code == 401
        assert client.get("/directories/counts").status_code == 401

    def test_directory_counts_on_empty_install(self, auth_client):
        """Counts should be zero for every directory on a fresh install."""
        response = auth_client.get("/directories/counts")

        assert response.status_code == 200
        assert response.json() == {
            "analyzed": 0,
            "contacted": 0,
            "engaged": 0,
            "starred": 0,
        }

    def test_directory_search(self, auth_client, conversation_with_messages):
        """Directory should support search."""
        response = auth_client.get("/directories/analyzed?search=counterpart")

        assert response.status_code == 200
        data = response.json()
        assert data["directory_type"] == "analyzed"
        # The fixture's counterpart has never been analyzed, so it is excluded.
        assert data["entries"] == []
        assert data["total"] == 0


# =============================================================================
# E2E: AUDIT FLOW
# =============================================================================


class TestE2EAuditFlow:
    """E2E tests for audit logging functionality."""

    def test_audit_logs_require_auth(self, client):
        """Audit is sensitive and must reject unauthenticated callers."""
        response = client.get("/audit")

        assert response.status_code == 401

    def test_audit_logs_readable_when_authenticated(self, auth_client):
        """With auth, /audit returns its list envelope."""
        response = auth_client.get("/audit")

        assert response.status_code == 200
        data = response.json()
        assert data["entries"] == []
        assert data["total"] == 0


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

    def test_metrics_requires_authentication(self, client):
        """Metrics expose system internals and must require auth."""
        response = client.get("/api/metrics")

        assert response.status_code == 401

    def test_metrics_returns_system_info(self, auth_client):
        """Metrics endpoint should return system info."""
        response = auth_client.get("/api/metrics")

        assert response.status_code == 200
        data = response.json()
        assert "collected_at" in data
        assert isinstance(data["application"], dict)
        assert isinstance(data["system"], dict)


# =============================================================================
# E2E: ATTACHMENTS FLOW
# =============================================================================


class TestE2EAttachmentFlow:
    """E2E tests for attachment handling."""

    def test_attachment_upload_requires_authentication(self, client):
        """Attachment upload exists at /attachments/upload and requires auth."""
        response = client.post(
            "/attachments/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )

        assert response.status_code == 401


# =============================================================================
# E2E: ERROR HANDLING
# =============================================================================


class TestE2EErrorHandling:
    """E2E tests for error handling across flows."""

    def test_invalid_conversation_id_returns_error(self, auth_client):
        """Unknown conversation ID yields an empty pending list, never a 500."""
        response = auth_client.get("/conversations/99999999/pending")

        assert response.status_code == 200
        assert response.json() == []

    def test_invalid_json_returns_422(self, client):
        """Invalid JSON should return 422."""
        response = client.post(
            "/identities",
            content="not valid json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 422

    def test_missing_required_fields_returns_422(self, auth_client):
        """Missing required fields should return 422."""
        response = auth_client.post(
            "/identities",
            json={},  # Missing required fields
        )

        assert response.status_code == 422
        missing = {tuple(e["loc"]) for e in response.json()["detail"]}
        assert ("body", "provider_id") in missing
        assert ("body", "external_username") in missing
        assert ("body", "display_name") in missing


# =============================================================================
# E2E: DATA PERSISTENCE
# =============================================================================


class TestE2EDataPersistence:
    """E2E tests for data persistence across requests."""

    def test_created_data_persists(self, auth_client, db_session, reddit_provider):
        """Data created via API should persist to the database."""
        response = auth_client.post(
            "/identities",
            json={
                "provider_id": "reddit",
                "external_username": "persist_test_user",
                "external_user_id": "t2_persist",
                "display_name": "Persist Test",
            },
        )
        assert response.status_code == 201

        # The row must exist in the DB, not just in the response body.
        from_db = (
            db_session.query(Identity)
            .filter_by(external_username="persist_test_user")
            .first()
        )
        assert from_db is not None
        assert from_db.display_name == "Persist Test"
        assert from_db.id == response.json()["id"]

        # And it must be visible to a subsequent request.
        listed = auth_client.get("/identities")
        assert listed.status_code == 200
        assert [i["external_username"] for i in listed.json()["identities"]] == [
            "persist_test_user"
        ]

    def test_messages_maintain_order(self, auth_client, conversation_with_messages):
        """The messages API returns a conversation's messages newest-first."""
        conv = conversation_with_messages["conversation"]

        response = auth_client.get(f"/conversations/{conv.id}/messages")

        assert response.status_code == 200
        data = response.json()
        assert data["has_more"] is False
        # Ordered by (sent_at DESC, id DESC); the fixture shares one sent_at,
        # so this is exactly reverse insertion order.
        assert [m["body_text"] for m in data["messages"]] == [
            "I have a question about your product.",
            "Hi! How can I help?",
            "Hey there!",
        ]


# =============================================================================
# E2E: CONCURRENT ACCESS
# =============================================================================


class TestE2EConcurrentAccess:
    """E2E tests for concurrent access handling."""

    def test_multiple_health_checks_concurrent(self, client):
        """Multiple concurrent health checks should work."""
        import threading

        results = []
        errors = []

        def check_health():
            try:
                response = client.get("/api/health")
                results.append(response.status_code)
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [threading.Thread(target=check_health) for _ in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exceptions inside a thread do not propagate to the test, so an
        # unchecked `all(...)` over an empty list would pass vacuously.
        assert errors == []
        assert len(results) == 5
        assert all(status == 200 for status in results)
