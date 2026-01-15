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

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    Conversation,
    LeadPost,
    Message,
    ProfileItem,
    ProfileSnapshot,
)
from rediska_core.infrastructure.elasticsearch import (
    CONTENT_DOCS_INDEX,
    ElasticsearchClient,
)


# =============================================================================
# SUPPORTED DOCUMENT TYPES
# =============================================================================


SUPPORTED_DOC_TYPES = {
    "message",
    "conversation",
    "lead_post",
    "profile_item",
    "profile_snapshot",
}


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
        return {
            "doc_type": "lead_post",
            "entity_id": lead_post.id,
            "provider_id": lead_post.provider_id,
            "source_location": lead_post.source_location,
            "account_id": lead_post.author_account_id,
            "title": lead_post.title or "",
            "content": lead_post.body_text or "",
            "post_url": lead_post.post_url,
            "remote_visibility": lead_post.remote_visibility or "unknown",
            "local_deleted": lead_post.deleted_at is not None,
            "created_at": lead_post.post_created_at.isoformat() if lead_post.post_created_at else None,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
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

        return {
            "doc_type": "profile_item",
            "entity_id": profile_item.id,
            "provider_id": provider_id,
            "account_id": profile_item.account_id,
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

        return {
            "doc_type": "profile_snapshot",
            "entity_id": snapshot.id,
            "provider_id": provider_id,
            "account_id": snapshot.account_id,
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

        else:
            # Unknown type
            return False

        # Index the document
        doc_id = f"{doc_type}:{entity_id}"
        return self.es_client.index_document(
            index=CONTENT_DOCS_INDEX,
            doc_id=doc_id,
            document=document,
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
