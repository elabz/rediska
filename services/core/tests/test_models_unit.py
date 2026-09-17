"""Unit tests for SQLAlchemy models.

These tests verify that models can be created, relationships work,
and constraints are properly enforced using an in-memory SQLite database.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from rediska_core.domain.models import Identity

from tests.factories import (
    create_audit_log,
    create_conversation,
    create_conversation_with_messages,
    create_external_account,
    create_identity,
    create_job,
    create_local_user,
    create_message,
    create_provider,
)


class TestProviderModel:
    """Tests for the Provider model."""

    def test_provider_requires_unique_id(self, db_session):
        """Test that provider_id must be unique."""
        create_provider(db_session, provider_id="reddit")

        with pytest.raises(IntegrityError):
            create_provider(db_session, provider_id="reddit")


class TestLocalUserModel:
    """Tests for the LocalUser model."""

    def test_create_local_user(self, db_session):
        """Test creating a local user."""
        user = create_local_user(db_session, username="admin")

        assert user.id is not None
        assert user.username == "admin"
        assert user.created_at is not None

    def test_user_requires_unique_username(self, db_session):
        """Test that username must be unique."""
        create_local_user(db_session, username="admin")

        with pytest.raises(IntegrityError):
            create_local_user(db_session, username="admin")


class TestIdentityModel:
    """Tests for the Identity model."""

    def test_identity_voice_config_survives_db_round_trip(self, db_session):
        """Nested voice config JSON must round-trip through the JSON column."""
        voice_config = {
            "system_prompt": "You are a friendly assistant.",
            "tone": "casual",
            "guidelines": ["Be helpful", "Be concise"],
        }

        identity = create_identity(db_session, voice_config_json=voice_config)
        identity_id = identity.id

        # commit() expires the instance (expire_on_commit=True), so the requery
        # below genuinely re-reads and re-deserializes the JSON column.
        db_session.commit()

        reloaded = db_session.get(Identity, identity_id)
        assert reloaded is not None
        assert reloaded.voice_config_json == voice_config
        assert reloaded.voice_config_json["guidelines"] == ["Be helpful", "Be concise"]

    def test_identity_requires_existing_provider(self, db_session):
        """A non-existent provider_id must be rejected by the FK constraint."""
        create_provider(db_session, provider_id="reddit")

        identity = Identity(
            provider_id="does_not_exist",
            external_username="orphan",
            external_user_id="t2_orphan",
            display_name="Orphan",
            voice_config_json={},
        )
        db_session.add(identity)

        with pytest.raises(IntegrityError):
            db_session.flush()

        # Leave the session usable for teardown after the failed flush.
        db_session.rollback()

    def test_identity_unique_per_provider_username(self, db_session):
        """Test that (provider_id, external_username) must be unique."""
        create_identity(
            db_session,
            provider_id="reddit",
            external_username="same_user",
        )

        with pytest.raises(IntegrityError):
            create_identity(
                db_session,
                provider_id="reddit",
                external_username="same_user",
            )


class TestExternalAccountModel:
    """Tests for the ExternalAccount model."""

    def test_create_external_account(self, db_session):
        """Test creating an external account."""
        account = create_external_account(
            db_session,
            external_username="reddit_user",
            remote_status="active",
        )

        assert account.id is not None
        assert account.external_username == "reddit_user"
        assert account.remote_status == "active"

    def test_account_default_states(self, db_session):
        """Test that account has correct default state values."""
        account = create_external_account(db_session)

        assert account.analysis_state == "not_analyzed"
        assert account.contact_state == "not_contacted"
        assert account.engagement_state == "not_engaged"


class TestMessageModel:
    """Tests for the Message model."""

    def test_create_incoming_message(self, db_session):
        """Test creating an incoming message."""
        message = create_message(
            db_session,
            direction="in",
            body_text="Hello!",
        )

        assert message.id is not None
        assert message.direction == "in"
        assert message.body_text == "Hello!"
        assert message.identity_id is None  # Incoming messages don't have identity

    def test_create_outgoing_message(self, db_session):
        """Test creating an outgoing message with identity."""
        identity = create_identity(db_session)
        conversation = create_conversation(db_session, identity=identity)
        message = create_message(
            db_session,
            conversation=conversation,
            identity=identity,
            direction="out",
            body_text="Hi there!",
        )

        assert message.direction == "out"
        assert message.identity_id == identity.id


class TestConversationWithMessages:
    """Tests for conversation with multiple messages."""

    def test_create_conversation_with_messages(self, db_session):
        """Test creating a conversation with multiple messages."""
        conversation, messages = create_conversation_with_messages(
            db_session, message_count=5
        )

        assert len(messages) == 5
        assert all(m.conversation_id == conversation.id for m in messages)


class TestAuditLogModel:
    """Tests for the AuditLog model."""

    def test_audit_log_ts_defaults_on_insert(self, db_session):
        """`ts` is populated by the column default, not by the caller."""
        before = datetime.now(timezone.utc).replace(tzinfo=None)
        audit = create_audit_log(db_session, action_type="user.login", result="ok")
        after = datetime.now(timezone.utc).replace(tzinfo=None)

        # No ts was passed in, so a non-null value proves the model default ran.
        # Columns are naive DATETIME storing UTC by convention.
        assert audit.ts is not None
        assert before <= audit.ts <= after


class TestJobModel:
    """Tests for the Job model."""

    def test_create_job(self, db_session):
        """Test creating a job."""
        job = create_job(
            db_session,
            job_type="sync.messages",
            payload_json={"conversation_id": 1},
        )

        assert job.id is not None
        assert job.job_type == "sync.messages"
        assert job.status == "queued"
        assert job.attempts == 0

    def test_job_dedupe_key_unique(self, db_session):
        """Test that dedupe_key must be unique."""
        create_job(db_session, dedupe_key="unique-key-1")

        with pytest.raises(IntegrityError):
            create_job(db_session, dedupe_key="unique-key-1")
