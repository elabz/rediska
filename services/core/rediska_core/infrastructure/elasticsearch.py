"""Elasticsearch client wrapper for Rediska.

This module provides a high-level Elasticsearch client with:
- Index creation and management
- Document CRUD operations
- Bulk indexing
- Search with filters

Usage:
    from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

    client = ElasticsearchClient(url="http://localhost:9200")

    # Create the current index version and point the alias at it
    client.ensure_index()

    # Index document (readers and writers address the alias)
    client.index_document(
        index="rediska_content_docs",
        doc_id="message:123",
        document={"doc_type": "message", "content": "Hello world"}
    )

    # Search
    results = client.search(
        index="rediska_content_docs",
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
        # The vector is indexed but never returned: keeping it in _source cost
        # 15.8 KB per document against ~4 KB without it. Excluding a field from
        # _source cannot be changed in place, which is why this is a new index
        # version behind an alias (see index_version.py).
        "_source": {"excludes": ["embedding"]},
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

            # Embedding provenance: which model produced the vector, which
            # text-preparation rule was used, and a hash of the prepared text
            # so re-indexing unchanged text does not re-embed it.
            "embedding_model": {
                "type": "keyword",
            },
            "embedding_prep": {
                "type": "keyword",
            },
            "embedding_text_hash": {
                "type": "keyword",
            },
            "embedded_at": {
                "type": "date",
            },
            # Set when a document has no embeddable text at all (an image with
            # no caption, an empty post). Without it, such documents come back
            # in every "needs a vector" query forever, because the only thing
            # that would clear them is a vector they can never have.
            "embedding_skipped": {
                "type": "boolean",
            },

            # Similarity filters
            "author_username": {
                "type": "keyword",
            },
            "location": {
                "type": "keyword",
            },
            # Reserved for lead-affinity-signal.
            "outcome_label": {
                "type": "keyword",
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


# Index names. Readers and writers address the ALIAS; the versioned names
# exist so a new version can be built from MySQL and switched atomically.
CONTENT_DOCS_ALIAS = "rediska_content_docs"
CONTENT_DOCS_INDEX_V1 = "rediska_content_docs_v1"
CONTENT_DOCS_INDEX_V2 = "rediska_content_docs_v2"
CONTENT_DOCS_INDEX_CURRENT = CONTENT_DOCS_INDEX_V2

# What every reader and writer passes as `index`.
CONTENT_DOCS_INDEX = CONTENT_DOCS_ALIAS


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

    def alias_exists(self, alias: str) -> bool:
        """Whether an alias (or an index of that name) exists."""
        try:
            return bool(self._client.indices.exists_alias(name=alias))
        except Exception:
            return False

    def get_alias_indices(self, alias: str) -> list[str]:
        """Concrete indices behind an alias (empty when it does not exist)."""
        try:
            return sorted(self._client.indices.get_alias(name=alias).keys())
        except Exception:
            return []

    def switch_alias(self, alias: str, to_index: str) -> bool:
        """Point an alias at one index atomically, removing it from others."""
        actions: list[dict] = [
            {"remove": {"index": old, "alias": alias}}
            for old in self.get_alias_indices(alias)
            if old != to_index
        ]
        actions.append({"add": {"index": to_index, "alias": alias}})
        try:
            self._client.indices.update_aliases(body={"actions": actions})
            return True
        except Exception:
            return False

    def refresh(self, index: str) -> bool:
        """Make recent writes searchable (used after a rebuild, before parity)."""
        try:
            self._client.indices.refresh(index=index)
            return True
        except Exception:
            return False

    def count(self, index: str, query: Optional[dict] = None) -> int:
        """Document count, optionally for a query (-1 when unavailable)."""
        try:
            body = {"query": query} if query else None
            return int(self._client.count(index=index, body=body)["count"])
        except Exception:
            return -1

    def ensure_index(self, index: str = CONTENT_DOCS_INDEX) -> bool:
        """Ensure the content docs index exists and is reachable by the alias.

        On a clean host this creates the current version (v2) and points the
        alias at it. Called with a concrete index name it just creates that
        index with the standard mapping.
        """
        if index != CONTENT_DOCS_ALIAS:
            return self.create_index(index, CONTENT_DOCS_MAPPING)

        if self.alias_exists(CONTENT_DOCS_ALIAS):
            return True
        if not self.create_index(CONTENT_DOCS_INDEX_CURRENT, CONTENT_DOCS_MAPPING):
            return False
        return self.switch_alias(CONTENT_DOCS_ALIAS, CONTENT_DOCS_INDEX_CURRENT)

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

    @staticmethod
    def _build_range_clauses(ranges: Optional[dict[str, dict[str, Any]]]) -> list[dict]:
        """Turn a field->{gte,lte,...} mapping into `range` clauses.

        Same contract as `_build_clauses`: a `None` bound is no constraint, and
        anything that cannot become a clause raises instead of vanishing.

        Raises:
            UnsupportedFilterError: If a bound cannot become a clause.
        """
        allowed = {"gt", "gte", "lt", "lte"}
        clauses: list[dict] = []

        for field, bounds in (ranges or {}).items():
            if bounds is None:
                continue
            if not isinstance(bounds, dict):
                raise UnsupportedFilterError(
                    f"Cannot build a range clause for filter {field!r} "
                    f"of type {type(bounds).__name__}"
                )
            kept = {k: v for k, v in bounds.items() if v is not None}
            unknown = set(kept) - allowed
            if unknown:
                raise UnsupportedFilterError(
                    f"Unsupported range bound(s) {sorted(unknown)} for filter {field!r}"
                )
            if kept:
                clauses.append({"range": {field: kept}})

        return clauses

    def search(
        self,
        index: str,
        query: dict[str, Any],
        filters: Optional[dict[str, Any]] = None,
        must_not: Optional[dict[str, Any]] = None,
        ranges: Optional[dict[str, dict[str, Any]]] = None,
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
        filter_clauses += self._build_range_clauses(ranges)
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
        ranges: Optional[dict[str, dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Perform k-nearest neighbors search.

        Args:
            index: Index name.
            vector: Query vector (embedding).
            k: Number of nearest neighbors.
            num_candidates: Number of candidates to consider.
            filters: Optional field filters.
            must_not: Optional field exclusions, same shape as `filters`.
            ranges: Optional field->{gte,lte} range filters, applied inside the
                kNN filter so `k` results satisfying them are returned.

        Returns:
            Dict with "total", "hits", and "max_score".

        Raises:
            UnsupportedFilterError: If a filter or exclusion cannot be applied.
        """
        filter_clauses = self._build_clauses(filters)
        filter_clauses += self._build_range_clauses(ranges)
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
    "CONTENT_DOCS_ALIAS",
    "CONTENT_DOCS_INDEX_V1",
    "CONTENT_DOCS_INDEX_V2",
    "CONTENT_DOCS_INDEX_CURRENT",
    "NotFoundError",
    "UnsupportedFilterError",
]
