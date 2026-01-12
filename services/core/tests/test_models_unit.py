"""Unit tests for SQLAlchemy models.

These tests verify that models can be created, relationships work,
and constraints are properly enforced using an in-memory SQLite database.
"""

import pytest
from sqlalchemy.exc import IntegrityError

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

    def test_create_provider(self, db_session):
        """Test creating a provider."""
        provider = create_provider(db_session)

        assert provider.provider_id == "reddit"
        assert provider.display_name == "Reddit"
        assert provider.enabled is True

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

    def test_create_identity(self, db_session):
        """Test creating an identity."""
        identity = create_identity(
            db_session,
            external_username="my_reddit_account",
            display_name="My Account",
            is_default=True,
        )

        assert identity.id is not None
        assert identity.external_username == "my_reddit_account"
        assert identity.display_name == "My Account"
        assert identity.is_default is True
        assert identity.is_active is True

    def test_identity_with_voice_config(self, db_session):
        """Test creating identity with voice configuration."""
        voice_config = {
            "system_prompt": "You are a friendly assistant.",
            "tone": "casual",
            "guidelines": ["Be helpful", "Be concise"],
        }

        identity = create_identity(
            db_session,
            voice_config_json=voice_config,
        )

        assert identity.voice_config_json == voice_config

    def test_identity_requires_provider(self, db_session):
        """Test that identity requires a valid provider."""
        # Provider is auto-created by factory
        identity = create_identity(db_session)
        assert identity.provider_id == "reddit"

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


class TestConversationModel:
    """Tests for the Conversation model."""

    def test_create_conversation(self, db_session):
        """Test creating a conversation."""
        conversation = create_conversation(db_session)

        assert conversation.id is not None
        assert conversation.identity_id is not None
        assert conversation.counterpart_account_id is not None
        assert conversation.external_conversation_id is not None

    def test_conversation_requires_identity(self, db_session):
        """Test that conversation is linked to an identity."""
        identity = create_identity(db_session, is_default=True)
        conversation = create_conversation(db_session, identity=identity)

        assert conversation.identity_id == identity.id


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

    def test_message_belongs_to_conversation(self, db_session):
        """Test that message is linked to a conversation."""
        conversation = create_conversation(db_session)
        message = create_message(db_session, conversation=conversation)

        assert message.conversation_id == conversation.id


class TestConversationWithMessages:
    """Tests for conversation with multiple messages."""

    def test_create_conversation_with_messages(self, db_session):
        """Test creating a conversation with multiple messages."""
        conversation, messages = create_conversation_with_messages(
            db_session, message_count=5
        )

        assert len(messages) == 5
        assert all(m.conversation_id == conversation.id for m in messages)

    def test_message_directions_alternate(self, db_session):
        """Test that factory alternates message directions."""
        _, messages = create_conversation_with_messages(db_session, message_count=4)

        # Even indices are "in", odd indices are "out"
        assert messages[0].direction == "in"
        assert messages[1].direction == "out"
        assert messages[2].direction == "in"
        assert messages[3].direction == "out"


class TestAuditLogModel:
    """Tests for the AuditLog model."""

    def test_create_audit_log(self, db_session):
        """Test creating an audit log entry."""
        audit = create_audit_log(
            db_session,
            action_type="user.login",
            result="ok",
        )

        assert audit.id is not None
        assert audit.action_type == "user.login"
        assert audit.result == "ok"
        assert audit.ts is not None

    def test_audit_log_with_identity(self, db_session):
        """Test creating audit log with identity reference."""
        identity = create_identity(db_session)
        audit = create_audit_log(
            db_session,
            action_type="identity.create",
            identity=identity,
        )

        assert audit.identity_id == identity.id

    def test_audit_log_with_entity_reference(self, db_session):
        """Test creating audit log with entity reference."""
        audit = create_audit_log(
            db_session,
            action_type="conversation.archive",
            entity_type="conversation",
            entity_id=123,
        )

        assert audit.entity_type == "conversation"
        assert audit.entity_id == 123


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
