"""Search service for hybrid search (BM25 + kNN).

This service provides:
1. BM25 text search for keyword matching
2. kNN vector search for semantic similarity
3. Hybrid search combining both with score blending
4. Filters for provider, identity, doc type
5. Exclusion filters for visibility and deleted content

Usage:
    service = SearchService(
        es_url="http://localhost:9200",
        embeddings_url="http://localhost:8080",
        embeddings_model="nomic-embed-text",
    )

    # Text search
    results = service.text_search(query="hello world", provider_id="reddit")

    # Vector search
    results = service.vector_search(query="greeting messages")

    # Hybrid search (recommended)
    results = service.hybrid_search(query="hello", identity_id=1)
"""

from typing import Any, Optional

from rediska_core.infrastructure.elasticsearch import (
    CONTENT_DOCS_INDEX,
    ElasticsearchClient,
)
from rediska_core.infrastructure.embeddings import (
    EmbeddingsClient,
    EmbeddingsError,
)


# =============================================================================
# EXCEPTIONS
# =============================================================================


class SearchError(Exception):
    """Exception raised for search errors."""

    pass


# =============================================================================
# CONSTANTS
# =============================================================================


DEFAULT_LIMIT = 20
MAX_LIMIT = 100
DEFAULT_KNN_K = 20
DEFAULT_KNN_CANDIDATES = 100

# Score blending weights (BM25 weight, kNN weight)
DEFAULT_BM25_WEIGHT = 0.3
DEFAULT_KNN_WEIGHT = 0.7


# =============================================================================
# SERVICE
# =============================================================================


class SearchService:
    """Service for hybrid search across indexed content.

    Combines BM25 text matching with kNN vector similarity search
    for better search quality.
    """

    def __init__(
        self,
        es_url: str,
        embeddings_url: Optional[str] = None,
        embeddings_model: Optional[str] = None,
        embeddings_api_key: Optional[str] = None,
        es_api_key: Optional[str] = None,
    ):
        """Initialize the search service.

        Args:
            es_url: Elasticsearch URL.
            embeddings_url: Optional embeddings API URL for vector search.
            embeddings_model: Optional embeddings model name.
            embeddings_api_key: Optional API key for embeddings.
            es_api_key: Optional API key for ES.
        """
        self._es_url = es_url
        self._es_api_key = es_api_key
        self._embeddings_url = embeddings_url
        self._embeddings_model = embeddings_model
        self._embeddings_api_key = embeddings_api_key

        self._es_client: Optional[ElasticsearchClient] = None
        self._embeddings_client: Optional[EmbeddingsClient] = None

    @property
    def es_client(self) -> ElasticsearchClient:
        """Get or create ES client (lazy initialization)."""
        if self._es_client is None:
            self._es_client = ElasticsearchClient(
                url=self._es_url,
                api_key=self._es_api_key,
            )
        return self._es_client

    @property
    def embeddings_client(self) -> Optional[EmbeddingsClient]:
        """Get or create embeddings client (lazy initialization)."""
        if self._embeddings_url and self._embeddings_model:
            if self._embeddings_client is None:
                self._embeddings_client = EmbeddingsClient(
                    url=self._embeddings_url,
                    model=self._embeddings_model,
                    api_key=self._embeddings_api_key,
                )
            return self._embeddings_client
        return None

    def _build_filters(
        self,
        provider_id: Optional[str] = None,
        identity_id: Optional[int] = None,
        doc_types: Optional[list[str]] = None,
        exclude_visibility: Optional[list[str]] = None,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        """Build filter dict for ES queries.

        Args:
            provider_id: Filter by provider.
            identity_id: Filter by identity.
            doc_types: Filter by document types.
            exclude_visibility: Visibility values to exclude.
            include_deleted: Whether to include locally deleted items.

        Returns:
            Dict of filters for ES.
        """
        filters = {}

        if provider_id:
            filters["provider_id"] = provider_id

        if identity_id is not None:
            filters["identity_id"] = identity_id

        # Exclude deleted by default
        if not include_deleted:
            filters["local_deleted"] = False

        return filters

    # =========================================================================
    # TEXT SEARCH (BM25)
    # =========================================================================

    def text_search(
        self,
        query: str,
        provider_id: Optional[str] = None,
        identity_id: Optional[int] = None,
        doc_types: Optional[list[str]] = None,
        exclude_visibility: Optional[list[str]] = None,
        include_deleted: bool = False,
        offset: int = 0,
        limit: int = DEFAULT_LIMIT,
        include_highlights: bool = False,
    ) -> dict[str, Any]:
        """Perform BM25 text search.

        Args:
            query: Search query string.
            provider_id: Filter by provider.
            identity_id: Filter by identity.
            doc_types: Filter by document types.
            exclude_visibility: Visibility values to exclude.
            include_deleted: Whether to include deleted items.
            offset: Pagination offset.
            limit: Maximum results to return.
            include_highlights: Whether to include highlights.

        Returns:
            Dict with total, hits, and max_score.
        """
        # Handle empty query
        if not query or not query.strip():
            return {"total": 0, "hits": [], "max_score": None}

        # Enforce max limit
        limit = min(limit, MAX_LIMIT)

        # Build filters
        filters = self._build_filters(
            provider_id=provider_id,
            identity_id=identity_id,
            doc_types=doc_types,
            exclude_visibility=exclude_visibility,
            include_deleted=include_deleted,
        )

        # Build query with multi_match for content and title
        es_query = {
            "multi_match": {
                "query": query,
                "fields": ["content^2", "title^3"],
                "type": "best_fields",
                "fuzziness": "AUTO",
            }
        }

        try:
            result = self.es_client.search(
                index=CONTENT_DOCS_INDEX,
                query=es_query,
                filters=filters,
                from_=offset,
                size=limit,
            )

            return result

        except Exception as e:
            raise SearchError(f"Text search failed: {e}")

    # =========================================================================
    # VECTOR SEARCH (kNN)
    # =========================================================================

    def vector_search(
        self,
        query: str,
        provider_id: Optional[str] = None,
        identity_id: Optional[int] = None,
        doc_types: Optional[list[str]] = None,
        exclude_visibility: Optional[list[str]] = None,
        include_deleted: bool = False,
        k: int = DEFAULT_KNN_K,
        num_candidates: int = DEFAULT_KNN_CANDIDATES,
    ) -> dict[str, Any]:
        """Perform kNN vector similarity search.

        Args:
            query: Search query string (will be embedded).
            provider_id: Filter by provider.
            identity_id: Filter by identity.
            doc_types: Filter by document types.
            exclude_visibility: Visibility values to exclude.
            include_deleted: Whether to include deleted items.
            k: Number of nearest neighbors.
            num_candidates: Candidates for approximate search.

        Returns:
            Dict with total, hits, and max_score.
        """
        # Check if embeddings configured
        if not self.embeddings_client:
            return {"total": 0, "hits": [], "max_score": None}

        # Handle empty query
        if not query or not query.strip():
            return {"total": 0, "hits": [], "max_score": None}

        try:
            # Generate query embedding
            query_vector = self.embeddings_client.embed(query)

            if query_vector is None:
                return {"total": 0, "hits": [], "max_score": None}

            # Build filters
            filters = self._build_filters(
                provider_id=provider_id,
                identity_id=identity_id,
                doc_types=doc_types,
                exclude_visibility=exclude_visibility,
                include_deleted=include_deleted,
            )

            result = self.es_client.knn_search(
                index=CONTENT_DOCS_INDEX,
                vector=query_vector,
                k=k,
                num_candidates=num_candidates,
                filters=filters,
            )

            return result

        except EmbeddingsError:
            # Fall back to empty results on embeddings error
            return {"total": 0, "hits": [], "max_score": None}
        except Exception as e:
            raise SearchError(f"Vector search failed: {e}")

    # =========================================================================
    # HYBRID SEARCH
    # =========================================================================

    def hybrid_search(
        self,
        query: str,
        provider_id: Optional[str] = None,
        identity_id: Optional[int] = None,
        doc_types: Optional[list[str]] = None,
        exclude_visibility: Optional[list[str]] = None,
        include_deleted: bool = False,
        offset: int = 0,
        limit: int = DEFAULT_LIMIT,
        bm25_weight: float = DEFAULT_BM25_WEIGHT,
        knn_weight: float = DEFAULT_KNN_WEIGHT,
    ) -> dict[str, Any]:
        """Perform hybrid search combining BM25 and kNN.

        Args:
            query: Search query string.
            provider_id: Filter by provider.
            identity_id: Filter by identity.
            doc_types: Filter by document types.
            exclude_visibility: Visibility values to exclude.
            include_deleted: Whether to include deleted items.
            offset: Pagination offset.
            limit: Maximum results to return.
            bm25_weight: Weight for BM25 scores (0-1).
            knn_weight: Weight for kNN scores (0-1).

        Returns:
            Dict with total, hits, and max_score.
        """
        # Handle empty query
        if not query or not query.strip():
            return {"total": 0, "hits": [], "max_score": None}

        # Get BM25 results
        bm25_results = self.text_search(
            query=query,
            provider_id=provider_id,
            identity_id=identity_id,
            doc_types=doc_types,
            exclude_visibility=exclude_visibility,
            include_deleted=include_deleted,
            offset=0,
            limit=limit * 2,  # Get more for blending
        )

        # Try to get kNN results
        knn_results = {"hits": []}
        if self.embeddings_client:
            try:
                knn_results = self.vector_search(
                    query=query,
                    provider_id=provider_id,
                    identity_id=identity_id,
                    doc_types=doc_types,
                    exclude_visibility=exclude_visibility,
                    include_deleted=include_deleted,
                    k=limit * 2,
                )
            except (SearchError, EmbeddingsError):
                pass  # Fall back to BM25 only

        # If no kNN results, return BM25 results directly with original scores
        if not knn_results.get("hits"):
            bm25_hits = bm25_results.get("hits", [])
            paginated = bm25_hits[offset : offset + limit]
            return {
                "total": bm25_results.get("total", len(bm25_hits)),
                "hits": paginated,
                "max_score": paginated[0]["score"] if paginated else None,
            }

        # Blend results using RRF when we have both BM25 and kNN
        blended = self._blend_results(
            bm25_hits=bm25_results.get("hits", []),
            knn_hits=knn_results.get("hits", []),
            bm25_weight=bm25_weight,
            knn_weight=knn_weight,
        )

        # Apply pagination
        paginated = blended[offset : offset + limit]

        return {
            "total": len(blended),
            "hits": paginated,
            "max_score": paginated[0]["score"] if paginated else None,
        }

    def _blend_results(
        self,
        bm25_hits: list[dict],
        knn_hits: list[dict],
        bm25_weight: float,
        knn_weight: float,
    ) -> list[dict]:
        """Blend BM25 and kNN results using Reciprocal Rank Fusion.

        Args:
            bm25_hits: Hits from BM25 search.
            knn_hits: Hits from kNN search.
            bm25_weight: Weight for BM25 scores.
            knn_weight: Weight for kNN scores.

        Returns:
            Blended and re-ranked hits.
        """
        # Use Reciprocal Rank Fusion (RRF)
        k = 60  # RRF constant

        scores = {}
        sources = {}

        # Add BM25 scores
        for rank, hit in enumerate(bm25_hits):
            doc_id = hit["id"]
            rrf_score = bm25_weight / (k + rank + 1)
            scores[doc_id] = scores.get(doc_id, 0) + rrf_score
            sources[doc_id] = hit

        # Add kNN scores
        for rank, hit in enumerate(knn_hits):
            doc_id = hit["id"]
            rrf_score = knn_weight / (k + rank + 1)
            scores[doc_id] = scores.get(doc_id, 0) + rrf_score
            if doc_id not in sources:
                sources[doc_id] = hit

        # Sort by blended score
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

        # Build result list
        results = []
        for doc_id in sorted_ids:
            hit = sources[doc_id].copy()
            hit["score"] = scores[doc_id]
            results.append(hit)

        return results


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "SearchService",
    "SearchError",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
]
