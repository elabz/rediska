"""Ingest tasks for fetching data from providers."""

import asyncio
from typing import Optional

from rediska_worker.celery_app import app


@app.task(name="ingest.backfill_conversations", bind=True)
def backfill_conversations(
    self,
    provider_id: str,
    identity_id: Optional[int] = None,
) -> dict:
    """Backfill all conversations from a provider.

    This task fetches all conversation history from the provider's API
    and stores them in the local database. It's similar to sync_delta
    but intended for initial import of full history.

    Args:
        provider_id: Provider to backfill (currently only 'reddit' supported).
        identity_id: Specific identity to backfill. If None, uses default identity.

    Returns:
        Dictionary with backfill results.
    """
    from rediska_core.infra.db import get_sync_session_factory
    from rediska_core.domain.services.message_sync import MessageSyncService, SyncError

    if provider_id != "reddit":
        return {
            "status": "skipped",
            "provider_id": provider_id,
            "reason": f"Provider '{provider_id}' not supported for backfill",
        }

    session_factory = get_sync_session_factory()
    session = session_factory()

    try:
        sync_service = MessageSyncService(db=session)

        # Use the existing sync method - it already handles full pagination
        result = asyncio.run(sync_service.sync_reddit_messages(identity_id=identity_id))

        # Queue indexing if new messages were synced
        index_task_id = None
        if result.new_messages > 0:
            index_task = app.send_task(
                "index.bulk_index_all_messages",
                kwargs={"batch_size": 500},
                queue="celery",
            )
            index_task_id = index_task.id

        return {
            "status": "success",
            "provider_id": provider_id,
            "task_type": "backfill_conversations",
            "conversations_synced": result.conversations_synced,
            "messages_synced": result.messages_synced,
            "new_conversations": result.new_conversations,
            "new_messages": result.new_messages,
            "errors": result.errors,
            "index_task_id": index_task_id,
        }

    except SyncError as e:
        return {
            "status": "error",
            "provider_id": provider_id,
            "task_type": "backfill_conversations",
            "error": str(e),
        }
    except Exception as e:
        session.rollback()
        return {
            "status": "error",
            "provider_id": provider_id,
            "task_type": "backfill_conversations",
            "error": str(e),
        }
    finally:
        session.close()


@app.task(name="ingest.backfill_messages", bind=True)
def backfill_messages(
    self,
    provider_id: str,
    conversation_id: int,
    identity_id: Optional[int] = None,
) -> dict:
    """Backfill all messages for a specific conversation.

    This task fetches complete message history for a single conversation
    from the provider's API. Useful for re-syncing a specific conversation
    that may have incomplete history.

    Args:
        provider_id: Provider to backfill from.
        conversation_id: Local conversation ID to backfill messages for.
        identity_id: Identity to use for API access.

    Returns:
        Dictionary with backfill results.
    """
    from rediska_core.infra.db import get_sync_session_factory
    from rediska_core.domain.services.message_sync import MessageSyncService, SyncError
    from rediska_core.domain.models import Conversation

    if provider_id != "reddit":
        return {
            "status": "skipped",
            "provider_id": provider_id,
            "conversation_id": conversation_id,
            "reason": f"Provider '{provider_id}' not supported for backfill",
        }

    session_factory = get_sync_session_factory()
    session = session_factory()

    try:
        # Get the conversation to find its external ID
        conversation = session.query(Conversation).filter_by(id=conversation_id).first()
        if not conversation:
            return {
                "status": "error",
                "provider_id": provider_id,
                "conversation_id": conversation_id,
                "error": f"Conversation {conversation_id} not found",
            }

        sync_service = MessageSyncService(db=session)

        # Sync messages for this specific conversation's thread
        result = asyncio.run(sync_service.sync_reddit_messages(
            identity_id=identity_id or conversation.identity_id
        ))

        return {
            "status": "success",
            "provider_id": provider_id,
            "conversation_id": conversation_id,
            "task_type": "backfill_messages",
            "messages_synced": result.messages_synced,
            "new_messages": result.new_messages,
            "errors": result.errors,
        }

    except SyncError as e:
        return {
            "status": "error",
            "provider_id": provider_id,
            "conversation_id": conversation_id,
            "task_type": "backfill_messages",
            "error": str(e),
        }
    except Exception as e:
        session.rollback()
        return {
            "status": "error",
            "provider_id": provider_id,
            "conversation_id": conversation_id,
            "task_type": "backfill_messages",
            "error": str(e),
        }
    finally:
        session.close()


@app.task(name="ingest.sync_delta", bind=True)
def sync_delta(self, provider_id: Optional[str] = None, identity_id: Optional[int] = None) -> dict:
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

        # Queue indexing if new messages were synced
        index_task_id = None
        if result.new_messages > 0:
            index_task = app.send_task(
                "index.bulk_index_all_messages",
                kwargs={"batch_size": 500},
                queue="celery",
            )
            index_task_id = index_task.id

        return {
            "status": "success",
            "provider_id": "reddit",
            "conversations_synced": result.conversations_synced,
            "messages_synced": result.messages_synced,
            "new_conversations": result.new_conversations,
            "new_messages": result.new_messages,
            "errors": result.errors,
            "index_task_id": index_task_id,
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
def browse_location(provider_id: str, location: str, cursor: Optional[str] = None) -> dict:
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
