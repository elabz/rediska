"""Embedding service for generating and storing embeddings.

This service handles:
1. Generating embeddings for text content
2. Updating ES documents with embeddings
3. Batch embedding generation

Usage:
    service = EmbeddingService(
        db=session,
        embeddings_url="http://localhost:8080",
        embeddings_model="nomic-embed-text",
        es_url="http://localhost:9200",
    )

    # Generate embedding for a single document
    result = service.generate_embedding(
        doc_type="message",
        entity_id=123,
        text="Hello world!",
    )

    # Batch generate embeddings
    items = [
        {"doc_type": "message", "entity_id": 1, "text": "Text 1"},
        {"doc_type": "message", "entity_id": 2, "text": "Text 2"},
    ]
    result = service.generate_embeddings_batch(items)
"""

from typing import Any, Optional

from sqlalchemy.orm import Session

from rediska_core.infrastructure.elasticsearch import (
    CONTENT_DOCS_INDEX,
    ElasticsearchClient,
)
from rediska_core.infrastructure.embeddings import (
    EmbeddingsClient,
    EmbeddingsError,
)


# =============================================================================
# CONSTANTS
# =============================================================================


# Maximum text length before truncation (chars). Only the legacy
# `generate_embedding` path uses this; `embed_entity` chunks to the server's
# input budget instead (see embedding_text.py).
MAX_TEXT_LENGTH = 8000


def _utcnow_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# SERVICE
# =============================================================================


class EmbeddingService:
    """Service for generating and storing embeddings.

    Coordinates between the embeddings client (llama.cpp) and
    Elasticsearch to generate and store embeddings.
    """

    def __init__(  # noqa: PLR0913 - client wiring
        self,
        db: Session,
        embeddings_url: str,
        embeddings_model: str,
        es_url: str,
        embeddings_api_key: Optional[str] = None,
        es_api_key: Optional[str] = None,
    ):
        """Initialize the embedding service.

        Args:
            db: SQLAlchemy database session.
            embeddings_url: URL for the embeddings API.
            embeddings_model: Model name for embeddings.
            es_url: Elasticsearch URL.
            embeddings_api_key: Optional API key for embeddings.
            es_api_key: Optional API key for ES.
        """
        self.db = db
        self._embeddings_client: Optional[EmbeddingsClient] = None
        self._es_client: Optional[ElasticsearchClient] = None

        self._embeddings_url = embeddings_url
        self._embeddings_model = embeddings_model
        self._embeddings_api_key = embeddings_api_key
        self._es_url = es_url
        self._es_api_key = es_api_key

    @property
    def embeddings_client(self) -> EmbeddingsClient:
        """Get or create embeddings client (lazy initialization)."""
        if self._embeddings_client is None:
            from rediska_core.config import get_settings

            self._embeddings_client = EmbeddingsClient(
                url=self._embeddings_url,
                model=self._embeddings_model,
                api_key=self._embeddings_api_key,
                max_chars=get_settings().embed_max_chars,
            )
        return self._embeddings_client

    @property
    def es_client(self) -> ElasticsearchClient:
        """Get or create ES client (lazy initialization)."""
        if self._es_client is None:
            self._es_client = ElasticsearchClient(
                url=self._es_url,
                api_key=self._es_api_key,
            )
        return self._es_client

    # =========================================================================
    # PER-ENTITY PIPELINE
    # =========================================================================

    def text_for_entity(self, doc_type: str, entity_id: int) -> Optional[str]:
        """Prepared embedding text for one entity, or None when there is none.

        One rule per type (see `embedding_text.prepare_embedding_text`), so the
        embed task, the sweeper and the backfill all embed the same string.
        """
        from rediska_core.domain.models import (
            ExternalAccount,
            LeadPost,
            Message,
            ProfileItem,
            ProfileSnapshot,
            ScoutWatchPost,
        )
        from rediska_core.domain.services.embedding_text import prepare_embedding_text

        if doc_type == "message":
            row = self.db.get(Message, entity_id)
            return prepare_embedding_text(None, row.body_text) if row else None

        if doc_type == "lead_post":
            row = self.db.get(LeadPost, entity_id)
            return prepare_embedding_text(row.title, row.body_text) if row else None

        if doc_type == "scout_post":
            row = self.db.get(ScoutWatchPost, entity_id)
            if row is None or row.analysis_status != "analyzed":
                return None
            return prepare_embedding_text(row.post_title, row.post_body)

        if doc_type == "profile_item":
            row = self.db.get(ProfileItem, entity_id)
            if row is None:
                return None
            return prepare_embedding_text(row.link_title, row.text_content)

        if doc_type == "profile_snapshot":
            row = self.db.get(ProfileSnapshot, entity_id)
            return prepare_embedding_text(None, row.summary_text) if row else None

        if doc_type == "account_comments":
            from rediska_core.domain.services.indexing import IndexingService

            if self.db.get(ExternalAccount, entity_id) is None:
                return None
            document = IndexingService(
                db=self.db, es_url=self._es_url
            ).account_comments_to_document(entity_id)
            return prepare_embedding_text(None, document["content"]) if document else None

        return None

    def embed_entity(
        self,
        doc_type: str,
        entity_id: int,
        force: bool = False,
    ) -> dict[str, Any]:
        """Embed one indexed entity and stamp the document with its provenance.

        Skips work when the prepared text and the model are unchanged, so
        re-indexing a document does not re-embed it. The vector is written with
        a partial update and never read back (it is excluded from `_source`).
        """
        from rediska_core.domain.services.embedding_text import PREP_VERSION, text_hash

        doc_id = f"{doc_type}:{entity_id}"
        text = self.text_for_entity(doc_type, entity_id)
        if not text:
            # Mark it, or every sweep and backfill will pick this document up
            # again forever: the only thing that would take it out of the
            # "needs a vector" query is a vector it can never have. An image
            # with no caption is not a failure, it is simply not embeddable.
            # Re-indexing clears the mark, so text arriving later still counts.
            self.es_client.update_document(
                index=CONTENT_DOCS_INDEX,
                doc_id=doc_id,
                updates={"embedding_skipped": True},
            )
            return {
                "success": True,
                "status": "skipped",
                "reason": "No text content found",
                "doc_type": doc_type,
                "entity_id": entity_id,
            }

        digest = text_hash(text)
        if not force:
            existing = self.es_client.get_document(index=CONTENT_DOCS_INDEX, doc_id=doc_id) or {}
            source = existing.get("_source", existing) or {}
            if (
                source.get("embedding_text_hash") == digest
                and source.get("embedding_model") == self._embeddings_model
                and source.get("embedded_at")
            ):
                return {
                    "success": True,
                    "status": "skipped",
                    "reason": "Unchanged text already embedded",
                    "doc_type": doc_type,
                    "entity_id": entity_id,
                }

        try:
            vector = self.embeddings_client.embed_document(text)
        except EmbeddingsError as e:
            return {
                "success": False,
                "error": str(e),
                "doc_type": doc_type,
                "entity_id": entity_id,
            }
        if vector is None:
            return {
                "success": True,
                "status": "skipped",
                "reason": "Empty text after processing",
                "doc_type": doc_type,
                "entity_id": entity_id,
            }

        updated = self.es_client.update_document(
            index=CONTENT_DOCS_INDEX,
            doc_id=doc_id,
            updates={
                "embedding": vector,
                "embedding_model": self._embeddings_model,
                "embedding_prep": PREP_VERSION,
                "embedding_text_hash": digest,
                "embedded_at": _utcnow_iso(),
                # It had text after all.
                "embedding_skipped": False,
            },
        )
        if not updated:
            return {
                "success": False,
                "error": "ES update failed",
                "doc_type": doc_type,
                "entity_id": entity_id,
            }
        return {
            "success": True,
            "status": "embedded",
            "doc_type": doc_type,
            "entity_id": entity_id,
            "dimensions": len(vector),
            "chars": len(text),
            # Handed back so the probable-rewrite pass can run its kNN on the
            # vector we just paid for, instead of embedding the text twice.
            "vector": vector,
        }

    # =========================================================================
    # SINGLE EMBEDDING
    # =========================================================================

    def generate_embedding(
        self,
        doc_type: str,
        entity_id: int,
        text: str,
    ) -> dict[str, Any]:
        """Generate embedding for a document and update ES.

        Args:
            doc_type: Type of document (message, conversation, etc.).
            entity_id: ID of the entity.
            text: Text content to embed.

        Returns:
            Dict with success status and details.
        """
        # Skip empty text
        if not text or not text.strip():
            return {
                "success": True,
                "status": "skipped",
                "reason": "Empty text",
                "doc_type": doc_type,
                "entity_id": entity_id,
            }

        try:
            # Truncate long text
            if len(text) > MAX_TEXT_LENGTH:
                text = self.embeddings_client.truncate_text(text, MAX_TEXT_LENGTH)

            # Generate embedding
            embedding = self.embeddings_client.embed(text)

            if embedding is None:
                return {
                    "success": True,
                    "status": "skipped",
                    "reason": "Empty text after processing",
                    "doc_type": doc_type,
                    "entity_id": entity_id,
                }

            # Update ES document with embedding
            doc_id = f"{doc_type}:{entity_id}"
            success = self.es_client.update_document(
                index=CONTENT_DOCS_INDEX,
                doc_id=doc_id,
                updates={"embedding": embedding},
            )

            if not success:
                return {
                    "success": False,
                    "error": "ES update failed",
                    "doc_type": doc_type,
                    "entity_id": entity_id,
                }

            return {
                "success": True,
                "status": "embedded",
                "doc_type": doc_type,
                "entity_id": entity_id,
                "dimensions": len(embedding),
            }

        except EmbeddingsError as e:
            return {
                "success": False,
                "error": str(e),
                "doc_type": doc_type,
                "entity_id": entity_id,
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {e}",
                "doc_type": doc_type,
                "entity_id": entity_id,
            }

    # =========================================================================
    # BATCH EMBEDDING
    # =========================================================================

    def generate_embeddings_batch(
        self,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Generate embeddings for multiple documents.

        Args:
            items: List of dicts with doc_type, entity_id, and text.

        Returns:
            Dict with success status and processing counts.
        """
        if not items:
            return {
                "success": True,
                "processed": 0,
                "skipped": 0,
                "errors": 0,
            }

        # Filter and prepare texts
        valid_items = []
        texts = []
        skipped = 0

        for item in items:
            text = item.get("text", "")
            if not text or not text.strip():
                skipped += 1
                continue

            # Truncate if needed
            if len(text) > MAX_TEXT_LENGTH:
                text = self.embeddings_client.truncate_text(text, MAX_TEXT_LENGTH)

            valid_items.append(item)
            texts.append(text)

        if not texts:
            return {
                "success": True,
                "processed": 0,
                "skipped": skipped,
                "errors": 0,
            }

        try:
            # Generate embeddings in batch
            embeddings = self.embeddings_client.embed_batch(texts)

            if len(embeddings) != len(valid_items):
                return {
                    "success": False,
                    "error": "Embedding count mismatch",
                    "processed": 0,
                    "skipped": skipped,
                    "errors": len(valid_items),
                }

            # Build bulk update documents
            documents = []
            for item, embedding in zip(valid_items, embeddings):
                doc_id = f"{item['doc_type']}:{item['entity_id']}"
                documents.append({
                    "_id": doc_id,
                    "embedding": embedding,
                })

            # Bulk update ES
            result = self.es_client.bulk_index(
                index=CONTENT_DOCS_INDEX,
                documents=documents,
            )

            return {
                "success": result.get("success", False),
                "processed": result.get("indexed", 0),
                "skipped": skipped,
                "errors": result.get("error_count", 0),
            }

        except EmbeddingsError as e:
            return {
                "success": False,
                "error": str(e),
                "processed": 0,
                "skipped": skipped,
                "errors": len(valid_items),
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {e}",
                "processed": 0,
                "skipped": skipped,
                "errors": len(valid_items),
            }


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "EmbeddingService",
    "MAX_TEXT_LENGTH",
]
