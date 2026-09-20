"""Indexing service for Elasticsearch content indexing.

This service handles:
1. Converting DB entities to ES documents
2. Upserting content to the search index
3. Deleting content from the search index
4. Bulk indexing operations

Usage:
    service = IndexingService(db=session, es_url="http://localhost:9200")

    # Index a single message
    service.upsert_content("message", message_id)

    # Bulk index all messages in a conversation
    service.bulk_index_conversation(conversation_id)

    # Delete content
    service.delete_content("message", message_id)
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    Conversation,
    ExternalAccount,
    ScoutWatchPost,
    LeadPost,
    Message,
    ProfileItem,
    ProfileSnapshot,
)
from rediska_core.infrastructure.elasticsearch import (
    CONTENT_DOCS_INDEX,
    ElasticsearchClient,
)

logger = logging.getLogger(__name__)

# Indexing is queued from write paths (saving a lead, syncing a message), so a
# broker that is down must cost those writes nothing. The connection is given
# one second, publishing is never retried, and after a failure dispatch is
# skipped entirely for a short while rather than paying the timeout per row.
_DISPATCH_TIMEOUT_SECONDS = 1.0
_DISPATCH_BACKOFF_SECONDS = 60.0
_dispatch_blocked_until = 0.0
_celery_app = None


def _get_celery_app():
    global _celery_app
    if _celery_app is None:
        from celery import Celery

        from rediska_core.config import get_settings

        _celery_app = Celery("rediska_core", broker=get_settings().celery_broker_url)
        _celery_app.conf.update(
            broker_connection_retry=False,
            broker_connection_retry_on_startup=False,
            broker_connection_max_retries=0,
            broker_transport_options={
                "socket_connect_timeout": _DISPATCH_TIMEOUT_SECONDS,
                "socket_timeout": _DISPATCH_TIMEOUT_SECONDS,
                "max_retries": 0,
            },
        )
    return _celery_app


def _dispatch(task_name: str, kwargs: dict[str, Any], queue: str) -> bool:
    """Send a task without waiting on, or failing because of, the broker."""
    global _dispatch_blocked_until

    if time.monotonic() < _dispatch_blocked_until:
        return False
    try:
        _get_celery_app().send_task(task_name, kwargs=kwargs, queue=queue, retry=False)
        return True
    except Exception as e:  # noqa: BLE001 - search must not break writes
        _dispatch_blocked_until = time.monotonic() + _DISPATCH_BACKOFF_SECONDS
        logger.warning("Could not queue %s for %s: %s", task_name, kwargs, e)
        return False


# =============================================================================
# SUPPORTED DOCUMENT TYPES
# =============================================================================


SUPPORTED_DOC_TYPES = {
    "message",
    "conversation",
    "lead_post",
    "scout_post",
    "profile_item",
    "profile_snapshot",
    "account_comments",
}

# Types whose text is worth a vector (conversations carry no text of their own).
EMBEDDABLE_DOC_TYPES = SUPPORTED_DOC_TYPES - {"conversation"}

# Post-like types, for the probable-rewrite pass and similarity defaults.
POST_DOC_TYPES = ("lead_post", "scout_post", "profile_item")


# =============================================================================
# SERVICE
# =============================================================================


class IndexingService:
    """Service for indexing content in Elasticsearch.

    Provides methods to convert DB entities to ES documents and
    upsert them to the search index.
    """

    def __init__(
        self,
        db: Session,
        es_url: Optional[str] = None,
    ):
        """Initialize the indexing service.

        Args:
            db: SQLAlchemy database session.
            es_url: Elasticsearch URL (defaults to localhost:9200).
        """
        self.db = db
        self.es_url = es_url or "http://localhost:9200"
        self._es_client: Optional[ElasticsearchClient] = None

    @property
    def es_client(self) -> ElasticsearchClient:
        """Get or create ES client (lazy initialization)."""
        if self._es_client is None:
            self._es_client = ElasticsearchClient(url=self.es_url)
        return self._es_client

    # =========================================================================
    # DOCUMENT CONVERSION
    # =========================================================================

    def message_to_document(self, message: Message) -> dict[str, Any]:
        """Convert a Message entity to an ES document.

        Args:
            message: The Message entity.

        Returns:
            Dictionary suitable for ES indexing.
        """
        # Try to get counterpart username from conversation relationship
        counterpart_username = None
        if message.conversation and message.conversation.counterpart_account:
            counterpart_username = message.conversation.counterpart_account.external_username

        return {
            "doc_type": "message",
            "entity_id": message.id,
            "provider_id": message.provider_id,
            "identity_id": message.identity_id,
            "conversation_id": message.conversation_id,
            "direction": message.direction,
            "content": message.body_text or "",
            "remote_visibility": message.remote_visibility or "unknown",
            "local_deleted": False,
            "created_at": message.sent_at.isoformat() if message.sent_at else None,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "counterpart_username": counterpart_username,
        }

    def conversation_to_document(self, conversation: Conversation) -> dict[str, Any]:
        """Convert a Conversation entity to an ES document.

        Args:
            conversation: The Conversation entity.

        Returns:
            Dictionary suitable for ES indexing.
        """
        return {
            "doc_type": "conversation",
            "entity_id": conversation.id,
            "provider_id": conversation.provider_id,
            "identity_id": conversation.identity_id,
            "account_id": conversation.counterpart_account_id,
            "content": "",  # Conversations don't have content themselves
            "local_deleted": False,
            "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }

    def lead_post_to_document(self, lead_post: LeadPost) -> dict[str, Any]:
        """Convert a LeadPost entity to an ES document.

        Args:
            lead_post: The LeadPost entity.

        Returns:
            Dictionary suitable for ES indexing.
        """
        author = lead_post.author_account.external_username if lead_post.author_account else None
        return {
            "doc_type": "lead_post",
            "entity_id": lead_post.id,
            "provider_id": lead_post.provider_id,
            "source_location": lead_post.source_location,
            "location": lead_post.source_location,
            "author_username": (author or "").lower() or None,
            "account_id": lead_post.author_account_id,
            "title": lead_post.title or "",
            "content": lead_post.body_text or "",
            "post_url": lead_post.post_url,
            "remote_visibility": lead_post.remote_visibility or "unknown",
            "local_deleted": lead_post.deleted_at is not None,
            "created_at": lead_post.post_created_at.isoformat() if lead_post.post_created_at else None,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }

    def scout_post_to_document(self, post: "ScoutWatchPost") -> dict[str, Any]:
        """Convert an analysed scout post to an ES document.

        Only analysed posts are indexed: unanalysed sightings are deleted by
        the 3-day history cleanup, so indexing them would leave dangling hits.
        """
        watch = post.watch if hasattr(post, "watch") else None
        return {
            "doc_type": "scout_post",
            "entity_id": post.id,
            "provider_id": watch.provider_id if watch else "reddit",
            "source_location": watch.source_location if watch else None,
            "location": watch.source_location if watch else None,
            "author_username": (post.post_author or "").lower() or None,
            "title": post.post_title or "",
            "content": post.post_body or "",
            "remote_visibility": "unknown",
            "local_deleted": False,
            "created_at": post.first_seen_at.isoformat() if post.first_seen_at else None,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "external_post_id": post.external_post_id,
                "watch_id": post.watch_id,
                "analysis_recommendation": post.analysis_recommendation,
            },
        }

    def account_comments_to_document(self, account_id: int) -> Optional[dict[str, Any]]:
        """One merged document holding an account's recent comments.

        Comments average ~108 characters; embedding them one by one would
        double the index while each vector said almost nothing. Instead the
        account's comments are merged newest first, each line prefixed with its
        community, up to the input budget — so the vector describes how the
        person talks and where. Individual comments stay text-searchable as
        their own `profile_item` documents.
        """
        from rediska_core.config import get_settings

        account = self.db.get(ExternalAccount, account_id)
        if account is None:
            return None

        budget = get_settings().embed_max_chars
        rows = (
            self.db.query(ProfileItem)
            .filter(
                ProfileItem.account_id == account_id,
                ProfileItem.item_type == "comment",
                ProfileItem.deleted_at.is_(None),
            )
            .order_by(
                ProfileItem.item_created_at.desc().nullslast(),
                ProfileItem.id.desc(),
            )
            .limit(500)
            .all()
        )

        lines: list[str] = []
        used = 0
        newest = None
        for row in rows:
            text = (row.text_content or "").strip()
            if not text:
                continue
            line = f"r/{row.subreddit}: {text}" if row.subreddit else text
            if used + len(line) + 1 > budget:
                break
            lines.append(line)
            used += len(line) + 1
            if newest is None:
                newest = row.item_created_at
        if not lines:
            return None

        return {
            "doc_type": "account_comments",
            "entity_id": account_id,
            "provider_id": account.provider_id,
            "account_id": account_id,
            "author_username": (account.external_username or "").lower() or None,
            "item_type": "comment",
            "content": "\n".join(lines),
            "local_deleted": False,
            "created_at": newest.isoformat() if newest else None,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {"comment_count": len(lines)},
        }

    def profile_item_to_document(self, profile_item: ProfileItem) -> dict[str, Any]:
        """Convert a ProfileItem entity to an ES document.

        Args:
            profile_item: The ProfileItem entity.

        Returns:
            Dictionary suitable for ES indexing.
        """
        # Derive provider_id from the account relationship
        provider_id = None
        if profile_item.account:
            provider_id = profile_item.account.provider_id

        author = profile_item.account.external_username if profile_item.account else None
        return {
            "doc_type": "profile_item",
            "entity_id": profile_item.id,
            "provider_id": provider_id,
            "account_id": profile_item.account_id,
            "author_username": (author or "").lower() or None,
            "location": f"r/{profile_item.subreddit}" if profile_item.subreddit else None,
            "item_type": profile_item.item_type,
            "content": profile_item.text_content or "",
            "remote_visibility": profile_item.remote_visibility or "unknown",
            "local_deleted": profile_item.deleted_at is not None,
            "created_at": profile_item.item_created_at.isoformat() if profile_item.item_created_at else None,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }

    def profile_snapshot_to_document(self, snapshot: ProfileSnapshot) -> dict[str, Any]:
        """Convert a ProfileSnapshot entity to an ES document.

        Args:
            snapshot: The ProfileSnapshot entity.

        Returns:
            Dictionary suitable for ES indexing.
        """
        # Derive provider_id from the account relationship
        provider_id = None
        if snapshot.account:
            provider_id = snapshot.account.provider_id

        author = snapshot.account.external_username if snapshot.account else None
        return {
            "doc_type": "profile_snapshot",
            "entity_id": snapshot.id,
            "provider_id": provider_id,
            "account_id": snapshot.account_id,
            "author_username": (author or "").lower() or None,
            "content": snapshot.summary_text or "",
            "local_deleted": False,  # Snapshots don't have deleted_at
            "created_at": snapshot.fetched_at.isoformat() if snapshot.fetched_at else None,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "signals_json": snapshot.signals_json,
                "risk_flags_json": snapshot.risk_flags_json,
                "model_info_json": snapshot.model_info_json,
            },
        }

    # =========================================================================
    # UPSERT OPERATIONS
    # =========================================================================

    def upsert_content(
        self,
        doc_type: str,
        entity_id: int,
    ) -> bool:
        """Upsert content to the search index.

        Fetches the entity from the database and indexes it in ES.

        Args:
            doc_type: Type of document (message, conversation, etc.).
            entity_id: ID of the entity to index.

        Returns:
            True if indexed successfully, False otherwise.

        Raises:
            ValueError: If doc_type is not supported.
        """
        if doc_type not in SUPPORTED_DOC_TYPES:
            raise ValueError(f"Unknown doc_type: {doc_type}")

        # Fetch entity and convert to document
        if doc_type == "message":
            entity = self.db.query(Message).filter(Message.id == entity_id).first()
            if not entity:
                return False
            document = self.message_to_document(entity)

        elif doc_type == "conversation":
            entity = self.db.query(Conversation).filter(Conversation.id == entity_id).first()
            if not entity:
                return False
            document = self.conversation_to_document(entity)

        elif doc_type == "lead_post":
            entity = self.db.query(LeadPost).filter(LeadPost.id == entity_id).first()
            if not entity:
                return False
            document = self.lead_post_to_document(entity)

        elif doc_type == "profile_item":
            entity = self.db.query(ProfileItem).filter(ProfileItem.id == entity_id).first()
            if not entity:
                return False
            document = self.profile_item_to_document(entity)

        elif doc_type == "profile_snapshot":
            entity = self.db.query(ProfileSnapshot).filter(ProfileSnapshot.id == entity_id).first()
            if not entity:
                return False
            document = self.profile_snapshot_to_document(entity)

        elif doc_type == "scout_post":
            entity = (
                self.db.query(ScoutWatchPost).filter(ScoutWatchPost.id == entity_id).first()
            )
            # Only analysed posts are indexed; the rest are deleted by cleanup.
            if not entity or entity.analysis_status != "analyzed":
                return False
            document = self.scout_post_to_document(entity)

        elif doc_type == "account_comments":
            built = self.account_comments_to_document(entity_id)
            if built is None:
                # No comments left to merge: drop any stale document.
                self.delete_content("account_comments", entity_id)
                return False
            document = built

        else:
            # Unknown type
            return False

        # Index the document
        doc_id = f"{doc_type}:{entity_id}"
        indexed = self.es_client.index_document(
            index=CONTENT_DOCS_INDEX,
            doc_id=doc_id,
            document=document,
        )
        if indexed:
            # Embedding is chained, never inline: a document without a vector
            # is still text-searchable, and the sweeper picks it up later.
            self.enqueue_embedding(doc_type, entity_id)
        return indexed

    @staticmethod
    def enqueue_index(doc_type: str, entity_id: int) -> bool:
        """Queue `index.upsert_content`, best-effort.

        The indexing task chains embedding itself, so callers hook this one
        place after writing content. Never raises and never waits: search is a
        read model, and losing an index write must not fail the write that
        produced it.
        """
        return _dispatch(
            "index.upsert_content",
            {"doc_type": doc_type, "entity_id": entity_id},
            "index",
        )

    @staticmethod
    def enqueue_delete(doc_type: str, entity_id: int) -> bool:
        """Queue `index.delete_content`, best-effort."""
        return _dispatch(
            "index.delete_content",
            {"doc_type": doc_type, "entity_id": entity_id},
            "index",
        )

    @staticmethod
    def enqueue_embedding(doc_type: str, entity_id: int) -> bool:
        """Queue `embed.generate_for_entity`, best-effort.

        Returns False when embeddings are disabled, the type carries no text,
        or the broker is unreachable — indexing never fails because of it.
        """
        from rediska_core.config import get_settings

        if not get_settings().embeddings_enabled or doc_type not in EMBEDDABLE_DOC_TYPES:
            return False
        return _dispatch(
            "embed.generate_for_entity",
            {"doc_type": doc_type, "entity_id": entity_id},
            "embed",
        )

    def delete_content(
        self,
        doc_type: str,
        entity_id: int,
    ) -> bool:
        """Delete content from the search index.

        Args:
            doc_type: Type of document.
            entity_id: ID of the entity to delete.

        Returns:
            True if deleted, False otherwise.
        """
        doc_id = f"{doc_type}:{entity_id}"
        return self.es_client.delete_document(
            index=CONTENT_DOCS_INDEX,
            doc_id=doc_id,
        )

    # =========================================================================
    # INDEX MANAGEMENT
    # =========================================================================

    def ensure_index(self) -> bool:
        """Ensure the content docs index exists.

        Creates the index with default mapping if it doesn't exist.

        Returns:
            True if index exists or was created.
        """
        return self.es_client.ensure_index(CONTENT_DOCS_INDEX)

    # =========================================================================
    # BULK OPERATIONS
    # =========================================================================

    def bulk_index_conversation(
        self,
        conversation_id: int,
    ) -> dict[str, Any]:
        """Bulk index all messages in a conversation.

        Args:
            conversation_id: The conversation ID.

        Returns:
            Dict with indexing results.
        """
        # Fetch all messages for the conversation
        messages = (
            self.db.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .all()
        )

        if not messages:
            return {"success": True, "indexed": 0}

        # Convert to documents
        documents = []
        for message in messages:
            doc = self.message_to_document(message)
            doc["_id"] = f"message:{message.id}"
            documents.append(doc)

        # Bulk index
        return self.es_client.bulk_index(
            index=CONTENT_DOCS_INDEX,
            documents=documents,
        )

    def bulk_index_messages(
        self,
        message_ids: list[int],
    ) -> dict[str, Any]:
        """Bulk index specific messages.

        Args:
            message_ids: List of message IDs to index.

        Returns:
            Dict with indexing results.
        """
        if not message_ids:
            return {"success": True, "indexed": 0}

        from sqlalchemy.orm import joinedload

        # Fetch messages with conversation and counterpart for username
        messages = (
            self.db.query(Message)
            .options(
                joinedload(Message.conversation).joinedload(Conversation.counterpart_account)
            )
            .filter(Message.id.in_(message_ids))
            .all()
        )

        if not messages:
            return {"success": True, "indexed": 0}

        # Convert to documents
        documents = []
        for message in messages:
            doc = self.message_to_document(message)
            doc["_id"] = f"message:{message.id}"
            documents.append(doc)

        # Bulk index
        return self.es_client.bulk_index(
            index=CONTENT_DOCS_INDEX,
            documents=documents,
        )


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "IndexingService",
    "SUPPORTED_DOC_TYPES",
]
