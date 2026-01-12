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


# Maximum text length before truncation (chars)
MAX_TEXT_LENGTH = 8000


# =============================================================================
# SERVICE
# =============================================================================


class EmbeddingService:
    """Service for generating and storing embeddings.

    Coordinates between the embeddings client (llama.cpp) and
    Elasticsearch to generate and store embeddings.
    """

    def __init__(
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
            self._embeddings_client = EmbeddingsClient(
                url=self._embeddings_url,
                model=self._embeddings_model,
                api_key=self._embeddings_api_key,
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
