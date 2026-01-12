"""Ingest tasks for fetching data from providers."""

import asyncio
from typing import Optional

from rediska_worker.celery_app import app


@app.task(name="ingest.backfill_conversations")
def backfill_conversations(provider_id: str) -> dict:
    """Backfill all conversations from a provider."""
    # TODO: Implement
    return {"status": "not_implemented", "provider_id": provider_id}


@app.task(name="ingest.backfill_messages")
def backfill_messages(
    provider_id: str, external_conversation_id: str, cursor: str | None = None
) -> dict:
    """Backfill messages for a specific conversation."""
    # TODO: Implement
    return {
        "status": "not_implemented",
        "provider_id": provider_id,
        "external_conversation_id": external_conversation_id,
    }


@app.task(name="ingest.sync_delta", bind=True)
def sync_delta(self, provider_id: str | None = None, identity_id: int | None = None) -> dict:
    """Sync new messages since last sync.

    Args:
        provider_id: Provider to sync (currently only 'reddit' supported).
                    If None, syncs all providers.
        identity_id: Specific identity to sync. If None, syncs the default/active identity.

    Returns:
        Dictionary with sync results including counts and any errors.
    """
    # Import here to avoid circular imports
    from rediska_core.infra.db import get_sync_session_factory
    from rediska_core.domain.services.message_sync import MessageSyncService, SyncError

    # Get database session
    session_factory = get_sync_session_factory()
    session = session_factory()

    try:
        sync_service = MessageSyncService(db=session)

        # Currently only Reddit is supported
        if provider_id and provider_id != "reddit":
            return {
                "status": "skipped",
                "provider_id": provider_id,
                "reason": f"Provider '{provider_id}' not supported",
            }

        # Run the async sync function
        result = asyncio.run(sync_service.sync_reddit_messages(identity_id=identity_id))

        return {
            "status": "success",
            "provider_id": "reddit",
            "conversations_synced": result.conversations_synced,
            "messages_synced": result.messages_synced,
            "new_conversations": result.new_conversations,
            "new_messages": result.new_messages,
            "errors": result.errors,
        }

    except SyncError as e:
        return {
            "status": "error",
            "provider_id": provider_id or "reddit",
            "error": str(e),
        }
    except Exception as e:
        session.rollback()
        return {
            "status": "error",
            "provider_id": provider_id or "reddit",
            "error": str(e),
        }
    finally:
        session.close()


@app.task(name="ingest.browse_location")
def browse_location(provider_id: str, location: str, cursor: str | None = None) -> dict:
    """Browse posts from a provider location (e.g., subreddit)."""
    # TODO: Implement
    return {"status": "not_implemented", "provider_id": provider_id, "location": location}


@app.task(name="ingest.fetch_post")
def fetch_post(provider_id: str, external_post_id: str) -> dict:
    """Fetch a specific post from a provider."""
    # TODO: Implement
    return {"status": "not_implemented", "provider_id": provider_id, "post_id": external_post_id}


@app.task(name="ingest.fetch_profile")
def fetch_profile(provider_id: str, external_username: str) -> dict:
    """Fetch a user profile from a provider."""
    # TODO: Implement
    return {"status": "not_implemented", "provider_id": provider_id, "username": external_username}


@app.task(name="ingest.fetch_profile_items")
def fetch_profile_items(provider_id: str, external_username: str) -> dict:
    """Fetch profile items (posts, comments, images) for a user."""
    # TODO: Implement
    return {"status": "not_implemented", "provider_id": provider_id, "username": external_username}
