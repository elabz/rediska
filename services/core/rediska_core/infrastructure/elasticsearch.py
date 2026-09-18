"""Elasticsearch client wrapper for Rediska.

This module provides a high-level Elasticsearch client with:
- Index creation and management
- Document CRUD operations
- Bulk indexing
- Search with filters

Usage:
    from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

    client = ElasticsearchClient(url="http://localhost:9200")

    # Create index
    client.create_index("rediska_content_docs_v1")

    # Index document
    client.index_document(
        index="rediska_content_docs_v1",
        doc_id="message:123",
        document={"doc_type": "message", "content": "Hello world"}
    )

    # Search
    results = client.search(
        index="rediska_content_docs_v1",
        query={"match": {"content": "hello"}},
        filters={"provider_id": "reddit"}
    )
"""

from typing import Any, Optional

from elasticsearch import Elasticsearch, NotFoundError


# =============================================================================
# INDEX MAPPING
# =============================================================================


# Content docs index mapping for hybrid search (BM25 + kNN)
CONTENT_DOCS_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {
            "analyzer": {
                "content_analyzer": {
                    "type": "standard",
                    "stopwords": "_english_",
                }
            }
        }
    },
    "mappings": {
        "properties": {
            # Document identification
            "doc_type": {
                "type": "keyword",
                "doc_values": True,
            },
            "entity_id": {
                "type": "long",
            },

            # Provider and identity for filtering
            "provider_id": {
                "type": "keyword",
                "doc_values": True,
            },
            "identity_id": {
                "type": "long",
            },

            # For external account filtering
            "account_id": {
                "type": "long",
            },

            # Conversation context
            "conversation_id": {
                "type": "long",
            },

            # Timestamps
            "created_at": {
                "type": "date",
            },
            "indexed_at": {
                "type": "date",
            },

            # Content fields for BM25 search
            "content": {
                "type": "text",
                "analyzer": "content_analyzer",
            },
            "title": {
                "type": "text",
                "analyzer": "content_analyzer",
            },

            # Visibility filtering
            "remote_visibility": {
                "type": "keyword",
            },
            "local_deleted": {
                "type": "boolean",
            },

            # Embedding vector for kNN search
            # Dimension should match your embeddings model
            # Using 768 for nomic-embed-text
            "embedding": {
                "type": "dense_vector",
                "dims": 768,
                "index": True,
                "similarity": "cosine",
            },

            # Message-specific fields
            "direction": {
                "type": "keyword",
            },
            "counterpart_username": {
                "type": "keyword",
            },

            # Lead post-specific fields
            "source_location": {
                "type": "keyword",
            },
            "post_url": {
                "type": "keyword",
                "index": False,
            },

            # Profile item-specific fields
            "item_type": {
                "type": "keyword",
            },

            # Metadata
            "metadata": {
                "type": "object",
                "enabled": False,  # Not indexed, just stored
            },
        }
    }
}


# Index name constant
CONTENT_DOCS_INDEX = "rediska_content_docs_v1"


# =============================================================================
# EXCEPTIONS
# =============================================================================


class UnsupportedFilterError(ValueError):
    """Raised when a supplied filter cannot be turned into a query clause.

    A filter the client cannot express must fail the request rather than be
    dropped: silently skipping it would return a wider result set than the
    caller asked for, which is the failure mode this client is guarding
    against.
    """


# =============================================================================
# CLIENT
# =============================================================================


class ElasticsearchClient:
    """High-level Elasticsearch client wrapper.

    Provides a simplified interface for common Elasticsearch operations
    with error handling and convenience methods.
    """

    def __init__(
        self,
        url: str,
        api_key: Optional[str] = None,
        timeout: int = 30,
    ):
        """Initialize the Elasticsearch client.

        Args:
            url: Elasticsearch URL (e.g., "http://localhost:9200").
            api_key: Optional API key for authentication.
            timeout: Request timeout in seconds.
        """
        self.url = url

        if api_key:
            self._client = Elasticsearch(
                [url],
                api_key=api_key,
                request_timeout=timeout,
            )
        else:
            self._client = Elasticsearch(
                [url],
                request_timeout=timeout,
            )

    def ping(self) -> bool:
        """Check if Elasticsearch is reachable.

        Returns:
            True if ES responds to ping, False otherwise.
        """
        try:
            return self._client.ping()
        except Exception:
            return False

    # =========================================================================
    # INDEX MANAGEMENT
    # =========================================================================

    def index_exists(self, index: str) -> bool:
        """Check if an index exists.

        Args:
            index: Index name.

        Returns:
            True if index exists, False otherwise.
        """
        try:
            result = self._client.indices.exists(index=index)
            # ES v9 returns HeadApiResponse, convert to bool
            return bool(result)
        except Exception:
            return False

    def create_index(
        self,
        index: str,
        mapping: Optional[dict] = None,
    ) -> bool:
        """Create an index with mapping.

        Args:
            index: Index name.
            mapping: Optional custom mapping (defaults to CONTENT_DOCS_MAPPING).

        Returns:
            True if created or already exists, False on error.
        """
        if self.index_exists(index):
            return True

        try:
            body = mapping or CONTENT_DOCS_MAPPING
            self._client.indices.create(index=index, body=body)
            return True
        except Exception:
            return False

    def delete_index(self, index: str) -> bool:
        """Delete an index.

        Args:
            index: Index name.

        Returns:
            True if deleted, False otherwise.
        """
        try:
            self._client.indices.delete(index=index)
            return True
        except NotFoundError:
            return True  # Already deleted
        except Exception:
            return False

    def ensure_index(self, index: str = CONTENT_DOCS_INDEX) -> bool:
        """Ensure the content docs index exists.

        Creates the index with default mapping if it doesn't exist.

        Args:
            index: Index name (defaults to CONTENT_DOCS_INDEX).

        Returns:
            True if index exists or was created.
        """
        return self.create_index(index, CONTENT_DOCS_MAPPING)

    # =========================================================================
    # DOCUMENT OPERATIONS
    # =========================================================================

    def index_document(
        self,
        index: str,
        doc_id: str,
        document: dict[str, Any],
        refresh: bool = False,
    ) -> bool:
        """Index (create or update) a document.

        Args:
            index: Index name.
            doc_id: Document ID.
            document: Document body.
            refresh: Whether to refresh immediately.

        Returns:
            True if successful, False otherwise.
        """
        try:
            self._client.index(
                index=index,
                id=doc_id,
                body=document,
                refresh=refresh,
            )
            return True
        except Exception:
            return False

    def get_document(
        self,
        index: str,
        doc_id: str,
    ) -> Optional[dict[str, Any]]:
        """Get a document by ID.

        Args:
            index: Index name.
            doc_id: Document ID.

        Returns:
            Document source if found, None otherwise.
        """
        try:
            result = self._client.get(index=index, id=doc_id)
            return result.get("_source")
        except NotFoundError:
            return None
        except Exception:
            return None

    def delete_document(
        self,
        index: str,
        doc_id: str,
        refresh: bool = False,
    ) -> bool:
        """Delete a document by ID.

        Args:
            index: Index name.
            doc_id: Document ID.
            refresh: Whether to refresh immediately.

        Returns:
            True if deleted, False if not found or error.
        """
        try:
            self._client.delete(index=index, id=doc_id, refresh=refresh)
            return True
        except NotFoundError:
            return False
        except Exception:
            return False

    def update_document(
        self,
        index: str,
        doc_id: str,
        updates: dict[str, Any],
        refresh: bool = False,
    ) -> bool:
        """Partially update a document.

        Args:
            index: Index name.
            doc_id: Document ID.
            updates: Fields to update.
            refresh: Whether to refresh immediately.

        Returns:
            True if updated, False otherwise.
        """
        try:
            self._client.update(
                index=index,
                id=doc_id,
                body={"doc": updates},
                refresh=refresh,
            )
            return True
        except NotFoundError:
            return False
        except Exception:
            return False

    # =========================================================================
    # BULK OPERATIONS
    # =========================================================================

    def bulk_index(
        self,
        index: str,
        documents: list[dict[str, Any]],
        refresh: bool = False,
    ) -> dict[str, Any]:
        """Bulk index multiple documents.

        Each document should have an "_id" field for the document ID.

        Args:
            index: Index name.
            documents: List of documents with "_id" fields.
            refresh: Whether to refresh after bulk.

        Returns:
            Dict with "success", "indexed", "error_count", and "errors".
        """
        if not documents:
            return {"success": True, "indexed": 0, "error_count": 0, "errors": []}

        # Build bulk request body
        body = []
        for doc in documents:
            doc_id = doc.pop("_id", None)
            body.append({"index": {"_index": index, "_id": doc_id}})
            body.append(doc)

        try:
            result = self._client.bulk(body=body, refresh=refresh)

            errors = []
            error_count = 0

            if result.get("errors"):
                for item in result.get("items", []):
                    action = item.get("index", {})
                    if action.get("error"):
                        error_count += 1
                        errors.append({
                            "id": action.get("_id"),
                            "error": action.get("error"),
                        })

            return {
                "success": error_count == 0,
                "indexed": len(documents) - error_count,
                "error_count": error_count,
                "errors": errors,
            }

        except Exception as e:
            return {
                "success": False,
                "indexed": 0,
                "error_count": len(documents),
                "errors": [{"error": str(e)}],
            }

    # =========================================================================
    # SEARCH
    # =========================================================================

    @staticmethod
    def _build_clauses(fields: Optional[dict[str, Any]]) -> list[dict]:
        """Turn a field->value mapping into `term`/`terms` clauses.

        A `None` value means "no constraint on this field" and is dropped; an
        empty list means the same. Any other value the client cannot express
        raises rather than being skipped, so a filter is never silently lost.

        Raises:
            UnsupportedFilterError: If a value cannot become a clause.
        """
        clauses: list[dict] = []

        for field, value in (fields or {}).items():
            if value is None:
                continue

            if isinstance(value, (list, tuple, set)):
                values = [v for v in value if v is not None]
                if not values:
                    continue
                clauses.append({"terms": {field: list(values)}})
            elif isinstance(value, (str, bool, int, float)):
                clauses.append({"term": {field: value}})
            else:
                raise UnsupportedFilterError(
                    f"Cannot build a query clause for filter {field!r} "
                    f"of type {type(value).__name__}"
                )

        return clauses

    def search(
        self,
        index: str,
        query: dict[str, Any],
        filters: Optional[dict[str, Any]] = None,
        must_not: Optional[dict[str, Any]] = None,
        from_: int = 0,
        size: int = 10,
        sort: Optional[list[dict]] = None,
        highlight: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Search for documents.

        Args:
            index: Index name.
            query: Elasticsearch query DSL.
            filters: Optional field filters (provider_id, identity_id, etc.).
            must_not: Optional field exclusions, same shape as `filters`.
                Emitted as a `must_not` clause list beside `must`/`filter`, so
                a document missing the field is NOT excluded.
            from_: Starting offset.
            size: Number of results.
            sort: Optional sort specification.
            highlight: Optional highlight specification.

        Returns:
            Dict with "total", "hits", and "max_score".

        Raises:
            UnsupportedFilterError: If a filter or exclusion cannot be applied.
        """
        # Build the query with filters. Clause building happens before the
        # request so an inapplicable filter raises instead of being swallowed
        # by the error handling below.
        must = [query]
        filter_clauses = self._build_clauses(filters)
        must_not_clauses = self._build_clauses(must_not)

        bool_query: dict[str, Any] = {
            "must": must,
            "filter": filter_clauses,
        }
        # Omit the key entirely when nothing is excluded.
        if must_not_clauses:
            bool_query["must_not"] = must_not_clauses

        body = {
            "query": {"bool": bool_query},
            "from": from_,
            "size": size,
        }

        if sort:
            body["sort"] = sort

        if highlight:
            body["highlight"] = highlight

        try:
            result = self._client.search(
                index=index,
                body=body,
            )

            hits = result.get("hits", {})

            formatted = []
            for hit in hits.get("hits", []):
                entry = {
                    "id": hit.get("_id"),
                    "score": hit.get("_score"),
                    "source": hit.get("_source"),
                }
                # Only present when highlighting was requested; carrying it
                # through is the whole point of having asked for it.
                if "highlight" in hit:
                    entry["highlight"] = hit["highlight"]
                formatted.append(entry)

            return {
                "total": hits.get("total", {}).get("value", 0),
                "max_score": hits.get("max_score"),
                "hits": formatted,
            }

        except Exception as e:
            return {
                "total": 0,
                "max_score": None,
                "hits": [],
                "error": str(e),
            }

    def knn_search(
        self,
        index: str,
        vector: list[float],
        k: int = 10,
        num_candidates: int = 100,
        filters: Optional[dict[str, Any]] = None,
        must_not: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Perform k-nearest neighbors search.

        Args:
            index: Index name.
            vector: Query vector (embedding).
            k: Number of nearest neighbors.
            num_candidates: Number of candidates to consider.
            filters: Optional field filters.
            must_not: Optional field exclusions, same shape as `filters`.

        Returns:
            Dict with "total", "hits", and "max_score".

        Raises:
            UnsupportedFilterError: If a filter or exclusion cannot be applied.
        """
        filter_clauses = self._build_clauses(filters)
        must_not_clauses = self._build_clauses(must_not)

        body = {
            "knn": {
                "field": "embedding",
                "query_vector": vector,
                "k": k,
                "num_candidates": num_candidates,
            },
            "size": k,
        }

        if filter_clauses or must_not_clauses:
            knn_bool: dict[str, Any] = {}
            if filter_clauses:
                knn_bool["filter"] = filter_clauses
            if must_not_clauses:
                knn_bool["must_not"] = must_not_clauses
            body["knn"]["filter"] = {"bool": knn_bool}

        try:
            result = self._client.search(index=index, body=body)

            hits = result.get("hits", {})

            return {
                "total": len(hits.get("hits", [])),
                "max_score": hits.get("max_score"),
                "hits": [
                    {
                        "id": hit.get("_id"),
                        "score": hit.get("_score"),
                        "source": hit.get("_source"),
                    }
                    for hit in hits.get("hits", [])
                ],
            }

        except Exception as e:
            return {
                "total": 0,
                "max_score": None,
                "hits": [],
                "error": str(e),
            }


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "ElasticsearchClient",
    "CONTENT_DOCS_MAPPING",
    "CONTENT_DOCS_INDEX",
    "NotFoundError",
    "UnsupportedFilterError",
]
