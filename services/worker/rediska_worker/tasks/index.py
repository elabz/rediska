"""Indexing tasks for Elasticsearch.

These tasks handle indexing content (messages, conversations, profiles, posts)
to Elasticsearch for search functionality.
"""

from typing import Any

from rediska_worker.celery_app import app


@app.task(name="index.upsert_content")
def upsert_content(doc_type: str, entity_id: int) -> dict[str, Any]:
    """Index or update content in Elasticsearch.

    Fetches the entity from the database and indexes it in ES.

    Args:
        doc_type: Type of document (message, conversation, profile, lead_post).
        entity_id: ID of the entity to index.

    Returns:
        Dictionary with status and details.
    """
    # Import here to avoid circular imports
    from rediska_core.config import get_settings
    from rediska_core.domain.services.indexing import IndexingService
    from rediska_core.infra.db import get_sync_session_factory

    settings = get_settings()
    session_factory = get_sync_session_factory()
    session = session_factory()

    try:
        service = IndexingService(
            db=session,
            es_url=settings.elastic_url,
        )

        # Ensure the index exists
        service.ensure_index()

        # Upsert the content
        success = service.upsert_content(doc_type, entity_id)

        if success:
            return {
                "status": "success",
                "doc_type": doc_type,
                "entity_id": entity_id,
            }
        else:
            return {
                "status": "not_found",
                "doc_type": doc_type,
                "entity_id": entity_id,
                "error": f"Entity {doc_type}:{entity_id} not found",
            }

    except ValueError as e:
        return {
            "status": "error",
            "doc_type": doc_type,
            "entity_id": entity_id,
            "error": str(e),
        }
    except Exception as e:
        return {
            "status": "error",
            "doc_type": doc_type,
            "entity_id": entity_id,
            "error": str(e),
        }
    finally:
        session.close()


@app.task(name="index.delete_content")
def delete_content(doc_type: str, entity_id: int) -> dict[str, Any]:
    """Delete content from Elasticsearch.

    Args:
        doc_type: Type of document (message, conversation, profile, lead_post).
        entity_id: ID of the entity to delete.

    Returns:
        Dictionary with status and details.
    """
    # Import here to avoid circular imports
    from rediska_core.config import get_settings
    from rediska_core.domain.services.indexing import IndexingService
    from rediska_core.infra.db import get_sync_session_factory

    settings = get_settings()
    session_factory = get_sync_session_factory()
    session = session_factory()

    try:
        service = IndexingService(
            db=session,
            es_url=settings.elastic_url,
        )

        success = service.delete_content(doc_type, entity_id)

        return {
            "status": "success" if success else "not_found",
            "doc_type": doc_type,
            "entity_id": entity_id,
        }

    except Exception as e:
        return {
            "status": "error",
            "doc_type": doc_type,
            "entity_id": entity_id,
            "error": str(e),
        }
    finally:
        session.close()


@app.task(name="index.bulk_index_conversation")
def bulk_index_conversation(conversation_id: int) -> dict[str, Any]:
    """Bulk index all messages in a conversation.

    Args:
        conversation_id: ID of the conversation to index.

    Returns:
        Dictionary with status and indexing results.
    """
    # Import here to avoid circular imports
    from rediska_core.config import get_settings
    from rediska_core.domain.services.indexing import IndexingService
    from rediska_core.infra.db import get_sync_session_factory

    settings = get_settings()
    session_factory = get_sync_session_factory()
    session = session_factory()

    try:
        service = IndexingService(
            db=session,
            es_url=settings.elastic_url,
        )

        # Ensure the index exists
        service.ensure_index()

        # Bulk index all messages
        result = service.bulk_index_conversation(conversation_id)

        return {
            "status": "success" if result.get("success") else "partial",
            "conversation_id": conversation_id,
            "indexed": result.get("indexed", 0),
            "error_count": result.get("error_count", 0),
        }

    except Exception as e:
        return {
            "status": "error",
            "conversation_id": conversation_id,
            "error": str(e),
        }
    finally:
        session.close()
