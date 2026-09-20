"""Indexing tasks for Elasticsearch.

These tasks handle indexing content (messages, conversations, profiles, posts)
to Elasticsearch for search functionality, and rebuilding the index into a new
version behind the alias (semantic-similarity-search).
"""

import logging
from typing import Any

from rediska_worker.celery_app import app

logger = logging.getLogger(__name__)


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


@app.task(name="index.bulk_index_all_messages")
def bulk_index_all_messages(batch_size: int = 500) -> dict[str, Any]:
    """Index all messages in the database to Elasticsearch.

    Processes messages in batches to avoid memory issues.

    Args:
        batch_size: Number of messages to process per batch.

    Returns:
        Dictionary with indexing results.
    """
    import logging
    from rediska_core.config import get_settings
    from rediska_core.domain.models import Message
    from rediska_core.domain.services.indexing import IndexingService
    from rediska_core.infra.db import get_sync_session_factory

    logger = logging.getLogger(__name__)
    settings = get_settings()
    session_factory = get_sync_session_factory()
    session = session_factory()

    total_indexed = 0
    total_errors = 0

    try:
        service = IndexingService(
            db=session,
            es_url=settings.elastic_url,
        )

        # Ensure the index exists
        service.ensure_index()

        # Get total count
        total_messages = session.query(Message.id).count()
        logger.info(f"Starting bulk index of {total_messages} messages")

        # Process in batches
        offset = 0
        batch_num = 0
        while True:
            message_ids = [
                row[0] for row in
                session.query(Message.id)
                .order_by(Message.id)
                .offset(offset)
                .limit(batch_size)
                .all()
            ]

            if not message_ids:
                break

            batch_num += 1
            result = service.bulk_index_messages(message_ids)

            indexed = result.get("indexed", 0)
            errors = result.get("error_count", 0)
            total_indexed += indexed
            total_errors += errors

            if batch_num % 10 == 0:
                logger.info(
                    f"Indexed batch {batch_num}: {total_indexed}/{total_messages} messages"
                )

            offset += batch_size

        logger.info(f"Bulk indexing complete: {total_indexed} indexed, {total_errors} errors")

        return {
            "status": "success",
            "total_messages": total_messages,
            "indexed": total_indexed,
            "error_count": total_errors,
        }

    except Exception as e:
        logger.error(f"Bulk indexing failed: {e}")
        return {
            "status": "error",
            "indexed": total_indexed,
            "error_count": total_errors,
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


# =============================================================================
# INDEX VERSION REBUILD (semantic-similarity-search)
# =============================================================================


@app.task(
    name="index.reindex_to_version",
    bind=True,
    max_retries=0,
    soft_time_limit=7200,
    time_limit=7500,
)
def reindex_to_version(
    self,
    target_index: str = "",
    switch_alias: bool = False,
    batch_size: int = 500,
) -> dict[str, Any]:
    """Rebuild the content index from MySQL into a new version.

    The vector field is excluded from `_source` in v2, which cannot be changed
    in place, so the new version is built beside the old one and the alias is
    switched only when every document type matches in count. MySQL is the
    source of truth, so the rebuild reads rows rather than copying documents
    (v1 holds no vectors worth keeping). Embeddings are queued separately by
    `embed.backfill`.

    Args:
        target_index: Index to build (defaults to the current version).
        switch_alias: Point the alias at the new index when counts match.
        batch_size: Rows per batch.

    Returns:
        Per-type counts, the parity verdict, and whether the alias moved.
    """
    from sqlalchemy import select

    from rediska_core.config import get_settings
    from rediska_core.domain.models import (
        Conversation,
        ExternalAccount,
        LeadPost,
        Message,
        ProfileItem,
        ProfileSnapshot,
        ScoutWatchPost,
    )
    from rediska_core.domain.services.indexing import IndexingService
    from rediska_core.infrastructure.elasticsearch import (
        CONTENT_DOCS_ALIAS,
        CONTENT_DOCS_INDEX_CURRENT,
        CONTENT_DOCS_MAPPING,
    )
    from rediska_core.infra.db import get_sync_session_factory

    settings = get_settings()
    index = target_index or CONTENT_DOCS_INDEX_CURRENT
    session = get_sync_session_factory()()

    try:
        service = IndexingService(db=session, es_url=settings.elastic_url)
        es = service.es_client
        if not es.create_index(index, CONTENT_DOCS_MAPPING):
            return {"status": "error", "error": f"Could not create {index}"}

        # (doc_type, model, id column, row filter) — the same set the readers use.
        sources = [
            ("message", Message, Message.id, None),
            ("conversation", Conversation, Conversation.id, None),
            ("lead_post", LeadPost, LeadPost.id, LeadPost.deleted_at.is_(None)),
            (
                "scout_post",
                ScoutWatchPost,
                ScoutWatchPost.id,
                ScoutWatchPost.analysis_status == "analyzed",
            ),
            ("profile_item", ProfileItem, ProfileItem.id, ProfileItem.deleted_at.is_(None)),
            ("profile_snapshot", ProfileSnapshot, ProfileSnapshot.id, None),
            ("account_comments", ExternalAccount, ExternalAccount.id, None),
        ]

        indexed: dict[str, int] = {}
        failed: dict[str, int] = {}
        for doc_type, model, id_column, row_filter in sources:
            stmt = select(id_column)
            if row_filter is not None:
                stmt = stmt.where(row_filter)
            ids = [row[0] for row in session.execute(stmt).all()]

            done = miss = 0
            for start in range(0, len(ids), batch_size):
                for entity_id in ids[start:start + batch_size]:
                    document = _document_for(service, doc_type, entity_id)
                    if document is None:
                        miss += 1
                        continue
                    if es.index_document(
                        index=index, doc_id=f"{doc_type}:{entity_id}", document=document
                    ):
                        done += 1
                    else:
                        miss += 1
                session.expire_all()
            indexed[doc_type] = done
            failed[doc_type] = miss
            logger.info(f"reindex {doc_type}: {done} indexed, {miss} skipped")

        es.refresh(index)
        parity = {}
        for doc_type, count in indexed.items():
            in_index = es.count(index, {"term": {"doc_type": doc_type}})
            parity[doc_type] = {"built": count, "in_index": in_index, "match": in_index == count}

        all_match = all(p["match"] for p in parity.values())
        switched = False
        if switch_alias and all_match:
            switched = es.switch_alias(CONTENT_DOCS_ALIAS, index)

        return {
            "status": "success" if all_match else "parity_mismatch",
            "index": index,
            "indexed": indexed,
            "skipped": failed,
            "parity": parity,
            "alias_switched": switched,
            "alias": CONTENT_DOCS_ALIAS,
        }

    except Exception as e:
        logger.error(f"index.reindex_to_version failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        session.close()


def _document_for(service, doc_type: str, entity_id: int):
    """Build one document for the rebuild, or None when the row is gone."""
    from rediska_core.domain.models import (
        Conversation,
        LeadPost,
        Message,
        ProfileItem,
        ProfileSnapshot,
        ScoutWatchPost,
    )

    builders = {
        "message": (Message, service.message_to_document),
        "conversation": (Conversation, service.conversation_to_document),
        "lead_post": (LeadPost, service.lead_post_to_document),
        "scout_post": (ScoutWatchPost, service.scout_post_to_document),
        "profile_item": (ProfileItem, service.profile_item_to_document),
        "profile_snapshot": (ProfileSnapshot, service.profile_snapshot_to_document),
    }
    if doc_type == "account_comments":
        return service.account_comments_to_document(entity_id)
    model, builder = builders[doc_type]
    row = service.db.get(model, entity_id)
    return builder(row) if row is not None else None
