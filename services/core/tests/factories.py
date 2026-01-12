"""Test data factories for Rediska Core.

This module provides factory functions to create test data for models.
Use these instead of manually constructing objects in tests for consistency.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    AuditLog,
    Conversation,
    ExternalAccount,
    Identity,
    Job,
    LocalUser,
    Message,
    Provider,
)


def utcnow() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


# -----------------------------------------------------------------------------
# Provider Factory
# -----------------------------------------------------------------------------


def create_provider(
    session: Session,
    provider_id: str = "reddit",
    display_name: str = "Reddit",
    enabled: bool = True,
    **kwargs: Any,
) -> Provider:
    """Create a Provider record for testing."""
    provider = Provider(
        provider_id=provider_id,
        display_name=display_name,
        enabled=enabled,
        **kwargs,
    )
    session.add(provider)
    session.flush()
    return provider


# -----------------------------------------------------------------------------
# Local User Factory
# -----------------------------------------------------------------------------


def create_local_user(
    session: Session,
    username: str = "testuser",
    password_hash: str = "$argon2id$test$hash",  # Placeholder hash
    **kwargs: Any,
) -> LocalUser:
    """Create a LocalUser record for testing."""
    user = LocalUser(
        username=username,
        password_hash=password_hash,
        **kwargs,
    )
    session.add(user)
    session.flush()
    return user


# -----------------------------------------------------------------------------
# Identity Factory
# -----------------------------------------------------------------------------


def create_identity(
    session: Session,
    provider: Provider | None = None,
    provider_id: str = "reddit",
    external_username: str = "test_identity",
    external_user_id: str | None = "t2_test123",
    display_name: str = "Test Identity",
    voice_config_json: dict | None = None,
    is_default: bool = False,
    is_active: bool = True,
    **kwargs: Any,
) -> Identity:
    """Create an Identity record for testing."""
    if provider is None:
        # Try to get existing provider or create new one
        existing = session.query(Provider).filter_by(provider_id=provider_id).first()
        if existing is None:
            provider = create_provider(session, provider_id=provider_id)
        else:
            provider = existing

    identity = Identity(
        provider_id=provider.provider_id,
        external_username=external_username,
        external_user_id=external_user_id,
        display_name=display_name,
        voice_config_json=voice_config_json or {},
        is_default=is_default,
        is_active=is_active,
        **kwargs,
    )
    session.add(identity)
    session.flush()
    return identity


# -----------------------------------------------------------------------------
# External Account Factory
# -----------------------------------------------------------------------------


def create_external_account(
    session: Session,
    provider: Provider | None = None,
    provider_id: str = "reddit",
    external_username: str = "external_user",
    external_user_id: str | None = "t2_external123",
    remote_status: str = "active",
    **kwargs: Any,
) -> ExternalAccount:
    """Create an ExternalAccount record for testing."""
    if provider is None:
        existing = session.query(Provider).filter_by(provider_id=provider_id).first()
        if existing is None:
            provider = create_provider(session, provider_id=provider_id)
        else:
            provider = existing

    account = ExternalAccount(
        provider_id=provider.provider_id,
        external_username=external_username,
        external_user_id=external_user_id,
        remote_status=remote_status,
        **kwargs,
    )
    session.add(account)
    session.flush()
    return account


# -----------------------------------------------------------------------------
# Conversation Factory
# -----------------------------------------------------------------------------


def create_conversation(
    session: Session,
    identity: Identity | None = None,
    counterpart: ExternalAccount | None = None,
    provider_id: str = "reddit",
    external_conversation_id: str | None = None,
    **kwargs: Any,
) -> Conversation:
    """Create a Conversation record for testing."""
    # Ensure provider exists
    provider = session.query(Provider).filter_by(provider_id=provider_id).first()
    if provider is None:
        provider = create_provider(session, provider_id=provider_id)

    # Create identity if not provided
    if identity is None:
        identity = create_identity(session, provider=provider)

    # Create counterpart if not provided
    if counterpart is None:
        counterpart = create_external_account(
            session,
            provider=provider,
            external_username=f"counterpart_{utcnow().timestamp()}",
        )

    # Generate external_conversation_id if not provided
    if external_conversation_id is None:
        external_conversation_id = f"conv_{utcnow().timestamp()}"

    conversation = Conversation(
        provider_id=provider.provider_id,
        identity_id=identity.id,
        external_conversation_id=external_conversation_id,
        counterpart_account_id=counterpart.id,
        last_activity_at=utcnow(),
        **kwargs,
    )
    session.add(conversation)
    session.flush()
    return conversation


# -----------------------------------------------------------------------------
# Message Factory
# -----------------------------------------------------------------------------


def create_message(
    session: Session,
    conversation: Conversation | None = None,
    identity: Identity | None = None,
    direction: str = "in",
    body_text: str = "Test message content",
    external_message_id: str | None = None,
    **kwargs: Any,
) -> Message:
    """Create a Message record for testing."""
    # Create conversation if not provided
    if conversation is None:
        conversation = create_conversation(session)

    # For outgoing messages, use conversation's identity
    if direction == "out" and identity is None:
        identity = session.query(Identity).filter_by(id=conversation.identity_id).first()

    # Generate external_message_id if not provided
    if external_message_id is None:
        external_message_id = f"msg_{utcnow().timestamp()}"

    message = Message(
        provider_id=conversation.provider_id,
        identity_id=identity.id if identity else None,
        external_message_id=external_message_id,
        conversation_id=conversation.id,
        direction=direction,
        sent_at=utcnow(),
        body_text=body_text,
        **kwargs,
    )
    session.add(message)
    session.flush()
    return message


# -----------------------------------------------------------------------------
# Audit Log Factory
# -----------------------------------------------------------------------------


def create_audit_log(
    session: Session,
    actor: str = "user",
    action_type: str = "test.action",
    result: str = "ok",
    identity: Identity | None = None,
    provider_id: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    request_json: dict | None = None,
    response_json: dict | None = None,
    error_detail: str | None = None,
    **kwargs: Any,
) -> AuditLog:
    """Create an AuditLog record for testing."""
    audit = AuditLog(
        actor=actor,
        action_type=action_type,
        result=result,
        identity_id=identity.id if identity else None,
        provider_id=provider_id,
        entity_type=entity_type,
        entity_id=entity_id,
        request_json=request_json,
        response_json=response_json,
        error_detail=error_detail,
        **kwargs,
    )
    session.add(audit)
    session.flush()
    return audit


# -----------------------------------------------------------------------------
# Job Factory
# -----------------------------------------------------------------------------


def create_job(
    session: Session,
    queue_name: str = "default",
    job_type: str = "test.job",
    payload_json: dict | None = None,
    status: str = "queued",
    dedupe_key: str | None = None,
    **kwargs: Any,
) -> Job:
    """Create a Job record for testing."""
    if dedupe_key is None:
        dedupe_key = f"job_{utcnow().timestamp()}"

    job = Job(
        queue_name=queue_name,
        job_type=job_type,
        payload_json=payload_json or {},
        status=status,
        dedupe_key=dedupe_key,
        **kwargs,
    )
    session.add(job)
    session.flush()
    return job


# -----------------------------------------------------------------------------
# Batch Creation Helpers
# -----------------------------------------------------------------------------


def create_conversation_with_messages(
    session: Session,
    message_count: int = 5,
    identity: Identity | None = None,
    **conversation_kwargs: Any,
) -> tuple[Conversation, list[Message]]:
    """Create a conversation with multiple messages for testing."""
    conversation = create_conversation(session, identity=identity, **conversation_kwargs)

    messages = []
    for i in range(message_count):
        direction = "in" if i % 2 == 0 else "out"
        msg = create_message(
            session,
            conversation=conversation,
            direction=direction,
            body_text=f"Test message {i + 1}",
            identity=identity if direction == "out" else None,
        )
        messages.append(msg)

    return conversation, messages
