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

        # Check if message was deleted before we got here (defense-in-depth)
        from rediska_core.domain.models import Message

        message = (
            session.query(Message)
            .filter(Message.id == message_id)
            .first()
        )

        if not message:
            return {
                "status": "error",
                "error": f"Message {message_id} not found",
                "message_id": message_id,
            }

        if message.deleted_at is not None:
            # Message was deleted - don't send
            return {
                "status": "cancelled",
                "message": "Message was deleted before sending",
                "message_id": message_id,
            }

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

        creds_json = credentials_service.get_credential_decrypted(
            provider_id=provider_id,
            credential_type="oauth_tokens",
            identity_id=identity_id,
        )

        if not creds_json:
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

        # Handle attachments - append image URLs to message body
        attachment_ids = payload.get("attachment_ids", [])
        if attachment_ids:
            from rediska_core.domain.models import Attachment

            attachments = (
                session.query(Attachment)
                .filter(Attachment.id.in_(attachment_ids))
                .all()
            )

            if attachments and body_text:
                # Append attachment URLs to the message body
                attachment_section = "\n\n---\n**Attachments:**\n"
                for attachment in attachments:
                    if attachment.mime_type.startswith("image/"):
                        # For images, include them as links
                        attachment_section += f"- [Image ({attachment.mime_type})](attach:{attachment.id})\n"
                    else:
                        # For other files, include as links
                        attachment_section += f"- [File ({attachment.mime_type})](attach:{attachment.id})\n"

                body_text = body_text + attachment_section

        # Create provider adapter
        if provider_id == "reddit":
            import json
            token_data = json.loads(creds_json)
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
        # Note: Reddit API requires non-empty subject; use single space as minimal subject
        result = asyncio.run(adapter.send_message(
            recipient_username=counterpart.external_username,
            subject=" ",  # Minimal subject (Reddit requires non-empty)
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
