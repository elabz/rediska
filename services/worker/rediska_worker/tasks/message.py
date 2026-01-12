"""Message sending tasks.

These tasks handle sending messages through provider adapters
with at-most-once delivery semantics.
"""

import asyncio
from typing import Any

from rediska_worker.celery_app import app


@app.task(
    name="message.send_manual",
    bind=True,
    max_retries=0,  # At-most-once: no automatic retries for this task
    acks_late=False,  # Acknowledge immediately to prevent redelivery
)
def send_manual(self, payload: dict[str, Any]) -> dict:
    """Send a message manually through the provider.

    This task implements at-most-once delivery semantics:
    - If the send succeeds, mark message as 'visible'
    - If the send fails ambiguously (timeout), mark job as failed with no retry
    - If the send fails clearly (rate limit), allow retry

    Args:
        payload: Dictionary containing:
            - message_id: Local message ID
            - conversation_id: Local conversation ID
            - identity_id: Identity ID to use for sending
            - provider_id: Provider ID (e.g., 'reddit')
            - body_text: Message body text
            - attachment_ids: List of attachment IDs

    Returns:
        Dictionary with status and details.
    """
    # Import here to avoid circular imports
    from rediska_core.config import get_settings
    from rediska_core.domain.models import Conversation, ExternalAccount
    from rediska_core.domain.services.credentials import CredentialsService
    from rediska_core.domain.services.send_message import SendMessageService
    from rediska_core.infra.db import get_sync_session_factory
    from rediska_core.infrastructure.crypto import CryptoService
    from rediska_core.providers.reddit.adapter import RedditAdapter

    message_id = payload.get("message_id")
    conversation_id = payload.get("conversation_id")
    identity_id = payload.get("identity_id")
    provider_id = payload.get("provider_id")
    body_text = payload.get("body_text")

    if not all([message_id, conversation_id, identity_id, provider_id, body_text]):
        return {
            "status": "error",
            "error": "Missing required payload fields",
            "message_id": message_id,
        }

    # Get database session
    settings = get_settings()
    session_factory = get_sync_session_factory()
    session = session_factory()

    try:
        send_service = SendMessageService(db=session)

        # Get conversation and counterpart username
        conversation = (
            session.query(Conversation)
            .filter(Conversation.id == conversation_id)
            .first()
        )

        if not conversation:
            return {
                "status": "error",
                "error": f"Conversation {conversation_id} not found",
                "message_id": message_id,
            }

        counterpart = (
            session.query(ExternalAccount)
            .filter(ExternalAccount.id == conversation.counterpart_account_id)
            .first()
        )

        if not counterpart:
            return {
                "status": "error",
                "error": "Counterpart account not found",
                "message_id": message_id,
            }

        # Get credentials for identity
        crypto = CryptoService(settings.encryption_key)
        credentials_service = CredentialsService(db=session, crypto=crypto)

        creds = credentials_service.get_credential(
            provider_id=provider_id,
            credential_type="oauth",
            identity_id=identity_id,
        )

        if not creds:
            send_service.handle_send_failure(
                job_id=self.request.id,
                message_id=message_id,
                error="No credentials found",
                is_ambiguous=False,
            )
            session.commit()
            return {
                "status": "error",
                "error": "No credentials found",
                "message_id": message_id,
            }

        # Create provider adapter
        if provider_id == "reddit":
            import json
            token_data = json.loads(creds)
            adapter = RedditAdapter(
                access_token=token_data.get("access_token", ""),
                refresh_token=token_data.get("refresh_token", ""),
                client_id=settings.provider_reddit_client_id,
                client_secret=settings.provider_reddit_client_secret,
                user_agent="Rediska/1.0",
            )
        else:
            return {
                "status": "error",
                "error": f"Unknown provider: {provider_id}",
                "message_id": message_id,
            }

        # Send the message
        result = asyncio.run(adapter.send_message(
            recipient_username=counterpart.external_username,
            subject="Re: Conversation",  # Reddit requires a subject
            body=body_text,
        ))

        if result.success:
            # Mark message as sent
            send_service.mark_message_sent(
                message_id=message_id,
                external_message_id=result.external_message_id,
            )
            session.commit()

            return {
                "status": "success",
                "message_id": message_id,
                "external_message_id": result.external_message_id,
            }
        else:
            # Handle failure
            send_service.handle_send_failure(
                job_id=self.request.id if self.request else 0,
                message_id=message_id,
                error=result.error_message or "Unknown error",
                is_ambiguous=result.is_ambiguous,
            )
            session.commit()

            return {
                "status": "failed",
                "message_id": message_id,
                "error": result.error_message,
                "is_ambiguous": result.is_ambiguous,
            }

    except Exception as e:
        # Unknown exception - treat as ambiguous
        session.rollback()
        return {
            "status": "error",
            "error": str(e),
            "message_id": message_id,
            "is_ambiguous": True,
        }
    finally:
        session.close()
