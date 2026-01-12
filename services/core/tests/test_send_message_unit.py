"""Unit tests for Epic 5.2 - Manual Send Message service.

Tests cover:
1. Send validation logic (counterpart status, body validation)
2. Job creation for message sending
3. At-most-once semantics for ambiguous failures
4. Message state management
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rediska_core.domain.models import (
    Conversation,
    ExternalAccount,
    Identity,
    Job,
    Message,
    Provider,
    ProviderCredential,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def setup_provider(db_session):
    """Set up a test provider."""
    provider = Provider(
        provider_id="reddit",
        display_name="Reddit",
        enabled=True,
    )
    db_session.add(provider)
    db_session.flush()
    return provider


@pytest.fixture
def setup_identity(db_session, setup_provider):
    """Set up a test identity."""
    identity = Identity(
        provider_id=setup_provider.provider_id,
        external_username="my_account",
        external_user_id="t2_myid",
        display_name="My Account",
        is_default=True,
        is_active=True,
    )
    db_session.add(identity)
    db_session.flush()
    return identity


@pytest.fixture
def setup_counterpart(db_session, setup_provider):
    """Set up a counterpart account."""
    account = ExternalAccount(
        provider_id=setup_provider.provider_id,
        external_username="counterpart_user",
        external_user_id="t2_other",
        remote_status="active",
    )
    db_session.add(account)
    db_session.flush()
    return account


@pytest.fixture
def setup_conversation(db_session, setup_provider, setup_identity, setup_counterpart):
    """Set up a test conversation."""
    conversation = Conversation(
        provider_id=setup_provider.provider_id,
        identity_id=setup_identity.id,
        counterpart_account_id=setup_counterpart.id,
        external_conversation_id="conv_123",
    )
    db_session.add(conversation)
    db_session.flush()
    return conversation


@pytest.fixture
def setup_credentials(db_session, setup_provider, setup_identity, test_settings):
    """Set up OAuth credentials for the identity."""
    from rediska_core.infrastructure.crypto import CryptoService

    crypto = CryptoService(test_settings.encryption_key)
    encrypted_token = crypto.encrypt('{"access_token": "test", "refresh_token": "test"}')

    credential = ProviderCredential(
        provider_id=setup_provider.provider_id,
        identity_id=setup_identity.id,
        credential_type="oauth",
        secret_encrypted=encrypted_token,
    )
    db_session.add(credential)
    db_session.flush()
    return credential


# =============================================================================
# SEND VALIDATION TESTS
# =============================================================================


class TestSendValidation:
    """Tests for send message validation logic."""

    def test_send_requires_existing_conversation(
        self, db_session, setup_provider, setup_identity
    ):
        """Sending to non-existent conversation should fail."""
        from rediska_core.domain.services.send_message import (
            ConversationNotFoundError,
            SendMessageService,
        )

        service = SendMessageService(db=db_session)

        with pytest.raises(ConversationNotFoundError):
            service.validate_send(
                conversation_id=99999,
                body_text="Hello!",
            )

    def test_send_rejects_deleted_counterpart(
        self, db_session, setup_conversation, setup_counterpart
    ):
        """Sending to deleted counterpart should fail."""
        from rediska_core.domain.services.send_message import (
            CounterpartStatusError,
            SendMessageService,
        )

        # Mark counterpart as deleted
        setup_counterpart.remote_status = "deleted"
        db_session.flush()

        service = SendMessageService(db=db_session)

        with pytest.raises(CounterpartStatusError) as exc_info:
            service.validate_send(
                conversation_id=setup_conversation.id,
                body_text="Hello!",
            )

        assert "deleted" in str(exc_info.value)

    def test_send_rejects_suspended_counterpart(
        self, db_session, setup_conversation, setup_counterpart
    ):
        """Sending to suspended counterpart should fail."""
        from rediska_core.domain.services.send_message import (
            CounterpartStatusError,
            SendMessageService,
        )

        # Mark counterpart as suspended
        setup_counterpart.remote_status = "suspended"
        db_session.flush()

        service = SendMessageService(db=db_session)

        with pytest.raises(CounterpartStatusError) as exc_info:
            service.validate_send(
                conversation_id=setup_conversation.id,
                body_text="Hello!",
            )

        assert "suspended" in str(exc_info.value)

    def test_send_allows_active_counterpart(
        self, db_session, setup_conversation, setup_counterpart
    ):
        """Sending to active counterpart should succeed validation."""
        from rediska_core.domain.services.send_message import SendMessageService

        service = SendMessageService(db=db_session)

        # Should not raise
        result = service.validate_send(
            conversation_id=setup_conversation.id,
            body_text="Hello!",
        )

        assert result.conversation_id == setup_conversation.id

    def test_send_allows_unknown_status_counterpart(
        self, db_session, setup_conversation, setup_counterpart
    ):
        """Sending to unknown status counterpart should succeed (benefit of doubt)."""
        from rediska_core.domain.services.send_message import SendMessageService

        setup_counterpart.remote_status = "unknown"
        db_session.flush()

        service = SendMessageService(db=db_session)

        # Should not raise
        result = service.validate_send(
            conversation_id=setup_conversation.id,
            body_text="Hello!",
        )

        assert result.conversation_id == setup_conversation.id

    def test_send_rejects_empty_body(
        self, db_session, setup_conversation
    ):
        """Sending empty message should fail."""
        from rediska_core.domain.services.send_message import (
            EmptyMessageError,
            SendMessageService,
        )

        service = SendMessageService(db=db_session)

        with pytest.raises(EmptyMessageError):
            service.validate_send(
                conversation_id=setup_conversation.id,
                body_text="",
            )

    def test_send_rejects_whitespace_only_body(
        self, db_session, setup_conversation
    ):
        """Sending whitespace-only message should fail."""
        from rediska_core.domain.services.send_message import (
            EmptyMessageError,
            SendMessageService,
        )

        service = SendMessageService(db=db_session)

        with pytest.raises(EmptyMessageError):
            service.validate_send(
                conversation_id=setup_conversation.id,
                body_text="   \n\t  ",
            )


# =============================================================================
# JOB CREATION TESTS
# =============================================================================


class TestJobCreation:
    """Tests for job creation when sending messages."""

    def test_enqueue_creates_job(
        self, db_session, setup_conversation, setup_credentials
    ):
        """Enqueuing send should create a job record."""
        from rediska_core.domain.services.send_message import SendMessageService

        service = SendMessageService(db=db_session)

        result = service.enqueue_send(
            conversation_id=setup_conversation.id,
            body_text="Hello world!",
        )

        assert result.job_id is not None

        # Verify job was created
        job = db_session.query(Job).filter(Job.id == result.job_id).first()
        assert job is not None
        assert job.job_type == "message.send_manual"
        assert job.status == "queued"

    def test_enqueue_creates_pending_message(
        self, db_session, setup_conversation, setup_credentials
    ):
        """Enqueuing send should create a pending message record."""
        from rediska_core.domain.services.send_message import SendMessageService

        service = SendMessageService(db=db_session)

        result = service.enqueue_send(
            conversation_id=setup_conversation.id,
            body_text="Hello world!",
        )

        assert result.message_id is not None

        # Verify message was created
        message = db_session.query(Message).filter(Message.id == result.message_id).first()
        assert message is not None
        assert message.direction == "out"
        assert message.body_text == "Hello world!"
        assert message.remote_visibility == "unknown"  # Pending send

    def test_enqueue_links_message_to_identity(
        self, db_session, setup_conversation, setup_identity, setup_credentials
    ):
        """Outgoing message should be linked to the conversation's identity."""
        from rediska_core.domain.services.send_message import SendMessageService

        service = SendMessageService(db=db_session)

        result = service.enqueue_send(
            conversation_id=setup_conversation.id,
            body_text="Hello world!",
        )

        message = db_session.query(Message).filter(Message.id == result.message_id).first()
        assert message.identity_id == setup_identity.id

    def test_enqueue_uses_dedupe_key(
        self, db_session, setup_conversation, setup_credentials
    ):
        """Job should have a dedupe key to prevent duplicates."""
        from rediska_core.domain.services.send_message import SendMessageService

        service = SendMessageService(db=db_session)

        result = service.enqueue_send(
            conversation_id=setup_conversation.id,
            body_text="Hello world!",
        )

        job = db_session.query(Job).filter(Job.id == result.job_id).first()
        assert job.dedupe_key is not None

    def test_enqueue_validates_before_creating(
        self, db_session, setup_conversation, setup_counterpart
    ):
        """Enqueue should validate and reject invalid sends."""
        from rediska_core.domain.services.send_message import (
            CounterpartStatusError,
            SendMessageService,
        )

        setup_counterpart.remote_status = "deleted"
        db_session.flush()

        service = SendMessageService(db=db_session)

        with pytest.raises(CounterpartStatusError):
            service.enqueue_send(
                conversation_id=setup_conversation.id,
                body_text="Hello world!",
            )

        # Verify no job was created
        job_count = db_session.query(Job).filter(
            Job.job_type == "message.send_manual"
        ).count()
        assert job_count == 0


# =============================================================================
# MESSAGE STATE TESTS
# =============================================================================


class TestMessageState:
    """Tests for message state management."""

    def test_pending_message_has_unknown_visibility(
        self, db_session, setup_conversation, setup_credentials
    ):
        """Pending outgoing message should have unknown visibility."""
        from rediska_core.domain.services.send_message import SendMessageService

        service = SendMessageService(db=db_session)

        result = service.enqueue_send(
            conversation_id=setup_conversation.id,
            body_text="Hello world!",
        )

        message = db_session.query(Message).filter(Message.id == result.message_id).first()
        assert message.remote_visibility == "unknown"

    def test_mark_message_sent_updates_visibility(
        self, db_session, setup_conversation, setup_credentials
    ):
        """After successful send, visibility should be 'visible'."""
        from rediska_core.domain.services.send_message import SendMessageService

        service = SendMessageService(db=db_session)

        result = service.enqueue_send(
            conversation_id=setup_conversation.id,
            body_text="Hello world!",
        )

        # Simulate successful send
        service.mark_message_sent(
            message_id=result.message_id,
            external_message_id="t4_abc123",
        )

        message = db_session.query(Message).filter(Message.id == result.message_id).first()
        assert message.remote_visibility == "visible"
        assert message.external_message_id == "t4_abc123"

    def test_mark_message_failed_keeps_unknown_visibility(
        self, db_session, setup_conversation, setup_credentials
    ):
        """After ambiguous failure, visibility should remain 'unknown'."""
        from rediska_core.domain.services.send_message import SendMessageService

        service = SendMessageService(db=db_session)

        result = service.enqueue_send(
            conversation_id=setup_conversation.id,
            body_text="Hello world!",
        )

        # Simulate ambiguous failure
        service.mark_message_failed(
            message_id=result.message_id,
            error="Network timeout - unknown if sent",
            is_ambiguous=True,
        )

        message = db_session.query(Message).filter(Message.id == result.message_id).first()
        assert message.remote_visibility == "unknown"


# =============================================================================
# AT-MOST-ONCE SEMANTICS TESTS
# =============================================================================


class TestAtMostOnceSemantics:
    """Tests for at-most-once delivery semantics."""

    def test_ambiguous_failure_does_not_retry(
        self, db_session, setup_conversation, setup_credentials
    ):
        """Ambiguous failures should not auto-retry (at-most-once)."""
        from rediska_core.domain.services.send_message import SendMessageService

        service = SendMessageService(db=db_session)

        result = service.enqueue_send(
            conversation_id=setup_conversation.id,
            body_text="Hello world!",
        )

        # Get the job
        job = db_session.query(Job).filter(Job.id == result.job_id).first()

        # Simulate claiming and running the job
        from rediska_core.domain.services.jobs import JobService
        job_service = JobService(db=db_session)
        job_service.claim_job(job.id)

        # Simulate ambiguous failure (e.g., timeout)
        service.handle_send_failure(
            job_id=job.id,
            message_id=result.message_id,
            error="Connection timeout",
            is_ambiguous=True,
        )

        # Job should be marked as failed, not retrying
        db_session.refresh(job)
        assert job.status == "failed"

    def test_clear_failure_can_retry(
        self, db_session, setup_conversation, setup_credentials
    ):
        """Clear failures (e.g., validation error) can retry."""
        from rediska_core.domain.services.send_message import SendMessageService

        service = SendMessageService(db=db_session)

        result = service.enqueue_send(
            conversation_id=setup_conversation.id,
            body_text="Hello world!",
        )

        # Get the job
        job = db_session.query(Job).filter(Job.id == result.job_id).first()

        # Simulate claiming and running the job
        from rediska_core.domain.services.jobs import JobService
        job_service = JobService(db=db_session)
        job_service.claim_job(job.id)

        # Simulate clear failure (e.g., rate limited)
        service.handle_send_failure(
            job_id=job.id,
            message_id=result.message_id,
            error="Rate limited - try again later",
            is_ambiguous=False,
        )

        # Job should be marked as retrying
        db_session.refresh(job)
        assert job.status == "retrying"

    def test_manual_retry_allowed_for_ambiguous_failure(
        self, db_session, setup_conversation, setup_credentials
    ):
        """User should be able to manually retry ambiguous failures."""
        from rediska_core.domain.services.send_message import SendMessageService

        service = SendMessageService(db=db_session)

        result = service.enqueue_send(
            conversation_id=setup_conversation.id,
            body_text="Hello world!",
        )

        # Simulate ambiguous failure
        job = db_session.query(Job).filter(Job.id == result.job_id).first()
        from rediska_core.domain.services.jobs import JobService
        job_service = JobService(db=db_session)
        job_service.claim_job(job.id)

        service.handle_send_failure(
            job_id=job.id,
            message_id=result.message_id,
            error="Connection timeout",
            is_ambiguous=True,
        )

        # User explicitly requests retry
        new_job = service.retry_failed_send(message_id=result.message_id)

        assert new_job is not None
        assert new_job.job_id != result.job_id
        assert new_job.status == "queued"


# =============================================================================
# CREDENTIAL VALIDATION TESTS
# =============================================================================


class TestCredentialValidation:
    """Tests for credential validation when sending."""

    def test_send_requires_identity_credentials(
        self, db_session, setup_conversation
    ):
        """Sending requires valid credentials for the identity."""
        from rediska_core.domain.services.send_message import (
            MissingCredentialsError,
            SendMessageService,
        )

        # No credentials set up
        service = SendMessageService(db=db_session)

        with pytest.raises(MissingCredentialsError):
            service.enqueue_send(
                conversation_id=setup_conversation.id,
                body_text="Hello world!",
            )

    def test_send_succeeds_with_valid_credentials(
        self, db_session, setup_conversation, setup_credentials
    ):
        """Sending should succeed when identity has valid credentials."""
        from rediska_core.domain.services.send_message import SendMessageService

        service = SendMessageService(db=db_session)

        # Should not raise
        result = service.enqueue_send(
            conversation_id=setup_conversation.id,
            body_text="Hello world!",
        )

        assert result.job_id is not None
        assert result.message_id is not None
