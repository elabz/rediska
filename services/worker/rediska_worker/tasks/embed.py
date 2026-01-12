"""Embedding generation tasks.

These tasks handle generating embeddings for content (messages, profiles, posts)
and storing them in Elasticsearch for semantic search.
"""

from typing import Any

from rediska_worker.celery_app import app


@app.task(name="embed.generate")
def generate(doc_type: str, entity_id: int, text: str) -> dict[str, Any]:
    """Generate embedding for text content and store in ES.

    Fetches text, generates embedding via llama.cpp, and updates
    the corresponding ES document with the embedding vector.

    Args:
        doc_type: Type of document (message, conversation, profile, lead_post).
        entity_id: ID of the entity.
        text: Text content to embed.

    Returns:
        Dictionary with status and details.
    """
    # Import here to avoid circular imports
    from rediska_core.config import get_settings
    from rediska_core.domain.services.embedding import EmbeddingService
    from rediska_core.infra.db import get_sync_session_factory

    settings = get_settings()

    # Check if embeddings are configured
    if not settings.embeddings_url or not settings.embeddings_model:
        return {
            "status": "skipped",
            "doc_type": doc_type,
            "entity_id": entity_id,
            "reason": "Embeddings not configured",
        }

    session_factory = get_sync_session_factory()
    session = session_factory()

    try:
        service = EmbeddingService(
            db=session,
            embeddings_url=settings.embeddings_url,
            embeddings_model=settings.embeddings_model,
            embeddings_api_key=settings.embeddings_api_key,
            es_url=settings.elastic_url,
        )

        result = service.generate_embedding(
            doc_type=doc_type,
            entity_id=entity_id,
            text=text,
        )

        return {
            "status": "success" if result.get("success") else "error",
            "doc_type": doc_type,
            "entity_id": entity_id,
            **result,
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


@app.task(name="embed.generate_batch")
def generate_batch(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate embeddings for multiple items in batch.

    More efficient for bulk embedding operations.

    Args:
        items: List of dicts with doc_type, entity_id, and text.

    Returns:
        Dictionary with batch processing results.
    """
    # Import here to avoid circular imports
    from rediska_core.config import get_settings
    from rediska_core.domain.services.embedding import EmbeddingService
    from rediska_core.infra.db import get_sync_session_factory

    settings = get_settings()

    # Check if embeddings are configured
    if not settings.embeddings_url or not settings.embeddings_model:
        return {
            "status": "skipped",
            "reason": "Embeddings not configured",
            "processed": 0,
        }

    session_factory = get_sync_session_factory()
    session = session_factory()

    try:
        service = EmbeddingService(
            db=session,
            embeddings_url=settings.embeddings_url,
            embeddings_model=settings.embeddings_model,
            embeddings_api_key=settings.embeddings_api_key,
            es_url=settings.elastic_url,
        )

        result = service.generate_embeddings_batch(items)

        return {
            "status": "success" if result.get("success") else "partial",
            **result,
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "processed": 0,
        }
    finally:
        session.close()


@app.task(name="embed.generate_for_entity")
def generate_for_entity(doc_type: str, entity_id: int) -> dict[str, Any]:
    """Generate embedding for an entity by fetching its text from DB.

    Convenience task that fetches the entity's text content automatically.

    Args:
        doc_type: Type of document (message, conversation, etc.).
        entity_id: ID of the entity.

    Returns:
        Dictionary with status and details.
    """
    # Import here to avoid circular imports
    from rediska_core.config import get_settings
    from rediska_core.domain.models import Message
    from rediska_core.domain.services.embedding import EmbeddingService
    from rediska_core.infra.db import get_sync_session_factory

    settings = get_settings()

    # Check if embeddings are configured
    if not settings.embeddings_url or not settings.embeddings_model:
        return {
            "status": "skipped",
            "doc_type": doc_type,
            "entity_id": entity_id,
            "reason": "Embeddings not configured",
        }

    session_factory = get_sync_session_factory()
    session = session_factory()

    try:
        # Fetch text based on doc_type
        text = ""

        if doc_type == "message":
            message = session.query(Message).filter(Message.id == entity_id).first()
            if message:
                text = message.body_text or ""

        # Add other doc_types as needed
        # elif doc_type == "lead_post":
        #     ...

        if not text:
            return {
                "status": "skipped",
                "doc_type": doc_type,
                "entity_id": entity_id,
                "reason": "No text content found",
            }

        service = EmbeddingService(
            db=session,
            embeddings_url=settings.embeddings_url,
            embeddings_model=settings.embeddings_model,
            embeddings_api_key=settings.embeddings_api_key,
            es_url=settings.elastic_url,
        )

        result = service.generate_embedding(
            doc_type=doc_type,
            entity_id=entity_id,
            text=text,
        )

        return {
            "status": "success" if result.get("success") else "error",
            "doc_type": doc_type,
            "entity_id": entity_id,
            **result,
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
