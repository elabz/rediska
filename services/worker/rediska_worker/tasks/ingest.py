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
    # TODO: Implement standalone profile fetch
    return {"status": "not_implemented", "provider_id": provider_id, "username": external_username}


@app.task(name="ingest.fetch_profile_items")
def fetch_profile_items(provider_id: str, external_username: str) -> dict:
    """Fetch profile items (posts, comments, images) for a user."""
    # TODO: Implement standalone profile items fetch
    return {"status": "not_implemented", "provider_id": provider_id, "username": external_username}


@app.task(name="ingest.analyze_lead_profile", bind=True)
def analyze_lead_profile(
    self,
    lead_id: int,
    run_multi_agent: bool = False,
) -> dict:
    """Analyze a lead's author profile.

    Fetches the author's profile and content from the provider,
    stores profile data locally, indexes for search, and generates embeddings.
    Optionally triggers multi-agent analysis after profile is ready.

    Args:
        lead_id: ID of the lead to analyze.
        run_multi_agent: Whether to trigger multi-agent analysis after profile fetch.

    Returns:
        Dictionary with analysis results.
    """
    import logging
    from rediska_core.infra.db import get_sync_session_factory
    from rediska_core.domain.services.leads import LeadsService
    from rediska_core.domain.services.analysis import AnalysisService, AnalysisError
    from rediska_core.providers.reddit.client import RedditAdapter
    from rediska_core.domain.services.indexing import IndexingService
    from rediska_core.domain.services.embedding import EmbeddingService
    from rediska_core.domain.models import Identity

    logger = logging.getLogger(__name__)
    logger.info(f"Analyzing profile for lead {lead_id}")

    session_factory = get_sync_session_factory()
    session = session_factory()

    try:
        # Get the lead
        leads_service = LeadsService(db=session)
        lead = leads_service.get_lead(lead_id)

        if not lead:
            return {
                "status": "error",
                "lead_id": lead_id,
                "error": f"Lead {lead_id} not found",
            }

        if not lead.author_account_id:
            return {
                "status": "error",
                "lead_id": lead_id,
                "error": "Lead has no author - cannot analyze",
            }

        # Get provider adapter (currently only Reddit supported)
        if lead.provider_id != "reddit":
            return {
                "status": "error",
                "lead_id": lead_id,
                "error": f"Provider '{lead.provider_id}' not supported",
            }

        # Get default identity for Reddit
        identity = (
            session.query(Identity)
            .filter(Identity.provider_id == "reddit", Identity.is_default == True)
            .first()
        )

        if not identity:
            return {
                "status": "error",
                "lead_id": lead_id,
                "error": "No default Reddit identity configured",
            }

        # Create services
        provider_adapter = RedditAdapter(db=session, identity_id=identity.id)
        indexing_service = IndexingService(db=session)
        embedding_service = EmbeddingService(db=session)

        analysis_service = AnalysisService(
            db=session,
            provider_adapter=provider_adapter,
            indexing_service=indexing_service,
            embedding_service=embedding_service,
        )

        # Run analysis
        result = asyncio.run(analysis_service.analyze_lead(lead_id))

        if not result.success:
            logger.error(f"Profile analysis failed for lead {lead_id}: {result.error}")
            return {
                "status": "error",
                "lead_id": lead_id,
                "error": result.error,
            }

        logger.info(
            f"Profile analysis complete for lead {lead_id}: "
            f"snapshot_id={result.profile_snapshot_id}, items={result.profile_items_count}"
        )

        # Optionally trigger multi-agent analysis
        multi_agent_task_id = None
        if run_multi_agent:
            from rediska_worker.tasks.multi_agent_analysis import analyze_lead as analyze_lead_multi
            multi_agent_task = analyze_lead_multi.delay(lead_id)
            multi_agent_task_id = multi_agent_task.id
            logger.info(f"Queued multi-agent analysis for lead {lead_id}: task_id={multi_agent_task_id}")

        session.commit()

        return {
            "status": "success",
            "lead_id": lead_id,
            "profile_snapshot_id": result.profile_snapshot_id,
            "profile_items_count": result.profile_items_count,
            "indexed_count": result.indexed_count,
            "embedded_count": result.embedded_count,
            "multi_agent_task_id": multi_agent_task_id,
        }

    except AnalysisError as e:
        logger.error(f"Analysis error for lead {lead_id}: {e}")
        return {
            "status": "error",
            "lead_id": lead_id,
            "error": str(e),
        }
    except Exception as e:
        logger.exception(f"Unexpected error analyzing lead {lead_id}")
        return {
            "status": "error",
            "lead_id": lead_id,
            "error": str(e),
        }
    finally:
        session.close()


@app.task(name="ingest.redownload_attachments", bind=True)
def redownload_attachments(
    self,
    conversation_id: Optional[int] = None,
    limit: int = 100,
) -> dict:
    """Re-download missing attachments from message body text.

    This task scans messages for image URLs and attempts to download
    any images that are not already stored as attachments. It does NOT
    call the Reddit API - it only extracts URLs from locally stored body_text.

    Args:
        conversation_id: Specific conversation, or None for all conversations.
        limit: Maximum number of new attachments to create.

    Returns:
        Dictionary with redownload results.
    """
    from rediska_core.infra.db import get_sync_session_factory
    from rediska_core.domain.services.message_sync import MessageSyncService

    session_factory = get_sync_session_factory()
    session = session_factory()

    try:
        sync_service = MessageSyncService(db=session)

        # Run the async redownload function
        result = asyncio.run(
            sync_service.redownload_missing_attachments(
                conversation_id=conversation_id,
                limit=limit,
            )
        )

        return {
            "status": "success",
            "conversation_id": conversation_id,
            "messages_scanned": result.get("messages_scanned", 0),
            "urls_found": result.get("urls_found", 0),
            "attachments_created": result.get("attachments_created", 0),
            "already_exists": result.get("already_exists", 0),
            "download_failed": result.get("download_failed", 0),
            "errors": result.get("errors", []),
        }

    except Exception as e:
        session.rollback()
        return {
            "status": "error",
            "conversation_id": conversation_id,
            "error": str(e),
        }
    finally:
        session.close()
