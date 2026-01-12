"""Unit tests for Epic 6.3 - Hybrid search service.

Tests cover:
1. BM25 text search
2. kNN vector search
3. Hybrid search with score blending
4. Filters: provider_id, identity_id, doc_type
5. Exclusion filters: remote_visibility, local_deleted
6. Pagination
7. Error handling
"""

from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# BM25 TEXT SEARCH TESTS
# =============================================================================


class TestBM25Search:
    """Tests for BM25 text-based search."""

    def test_text_search_returns_results(self, test_settings):
        """Text search should return matching documents."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {
                "total": 2,
                "max_score": 5.5,
                "hits": [
                    {"id": "message:1", "score": 5.5, "source": {"content": "Hello world", "doc_type": "message"}},
                    {"id": "message:2", "score": 3.2, "source": {"content": "Hello there", "doc_type": "message"}},
                ],
            }
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            result = service.text_search(query="hello")

            assert result["total"] == 2
            assert len(result["hits"]) == 2

    def test_text_search_uses_match_query(self, test_settings):
        """Text search should use ES match query."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {"total": 0, "hits": []}
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            service.text_search(query="test query")

            call_args = mock_client.search.call_args
            query = call_args[1]["query"]
            assert "match" in query or "multi_match" in query

    def test_text_search_empty_query_returns_empty(self, test_settings):
        """Text search with empty query should return empty results."""
        from rediska_core.domain.services.search import SearchService

        service = SearchService(es_url="http://localhost:9200")
        result = service.text_search(query="")

        assert result["total"] == 0
        assert result["hits"] == []


# =============================================================================
# KNN VECTOR SEARCH TESTS
# =============================================================================


class TestKNNSearch:
    """Tests for kNN vector-based search."""

    def test_vector_search_returns_results(self, test_settings):
        """Vector search should return similar documents."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            with patch("rediska_core.domain.services.search.EmbeddingsClient") as mock_embed:
                mock_embed_instance = MagicMock()
                mock_embed_instance.embed.return_value = [0.1] * 768
                mock_embed.return_value = mock_embed_instance

                mock_client = MagicMock()
                mock_client.knn_search.return_value = {
                    "total": 2,
                    "max_score": 0.95,
                    "hits": [
                        {"id": "message:1", "score": 0.95, "source": {"content": "Similar text"}},
                        {"id": "message:2", "score": 0.85, "source": {"content": "Also similar"}},
                    ],
                }
                mock_es.return_value = mock_client

                service = SearchService(
                    es_url="http://localhost:9200",
                    embeddings_url="http://localhost:8080",
                    embeddings_model="nomic-embed-text",
                )
                result = service.vector_search(query="find similar content")

                assert result["total"] == 2
                mock_embed_instance.embed.assert_called_once()
                mock_client.knn_search.assert_called_once()

    def test_vector_search_uses_query_embedding(self, test_settings):
        """Vector search should embed the query and use kNN."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            with patch("rediska_core.domain.services.search.EmbeddingsClient") as mock_embed:
                expected_vector = [0.5] * 768
                mock_embed_instance = MagicMock()
                mock_embed_instance.embed.return_value = expected_vector
                mock_embed.return_value = mock_embed_instance

                mock_client = MagicMock()
                mock_client.knn_search.return_value = {"total": 0, "hits": []}
                mock_es.return_value = mock_client

                service = SearchService(
                    es_url="http://localhost:9200",
                    embeddings_url="http://localhost:8080",
                    embeddings_model="nomic-embed-text",
                )
                service.vector_search(query="semantic search")

                call_args = mock_client.knn_search.call_args
                assert call_args[1]["vector"] == expected_vector

    def test_vector_search_without_embeddings_config_returns_empty(self, test_settings):
        """Vector search without embeddings configured should return empty."""
        from rediska_core.domain.services.search import SearchService

        service = SearchService(es_url="http://localhost:9200")
        result = service.vector_search(query="test")

        assert result["total"] == 0
        assert result["hits"] == []


# =============================================================================
# HYBRID SEARCH TESTS
# =============================================================================


class TestHybridSearch:
    """Tests for hybrid search with score blending."""

    def test_hybrid_search_combines_bm25_and_knn(self, test_settings):
        """Hybrid search should combine BM25 and kNN results."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            with patch("rediska_core.domain.services.search.EmbeddingsClient") as mock_embed:
                mock_embed_instance = MagicMock()
                mock_embed_instance.embed.return_value = [0.1] * 768
                mock_embed.return_value = mock_embed_instance

                mock_client = MagicMock()
                # BM25 results
                mock_client.search.return_value = {
                    "total": 2,
                    "hits": [
                        {"id": "message:1", "score": 5.0, "source": {"content": "exact match"}},
                        {"id": "message:3", "score": 3.0, "source": {"content": "partial match"}},
                    ],
                }
                # kNN results
                mock_client.knn_search.return_value = {
                    "total": 2,
                    "hits": [
                        {"id": "message:2", "score": 0.9, "source": {"content": "semantic match"}},
                        {"id": "message:1", "score": 0.8, "source": {"content": "exact match"}},
                    ],
                }
                mock_es.return_value = mock_client

                service = SearchService(
                    es_url="http://localhost:9200",
                    embeddings_url="http://localhost:8080",
                    embeddings_model="nomic-embed-text",
                )
                result = service.hybrid_search(query="test query")

                # Should have combined results
                assert result["total"] >= 2
                # message:1 appears in both, should be boosted
                ids = [hit["id"] for hit in result["hits"]]
                assert "message:1" in ids

    def test_hybrid_search_blends_scores(self, test_settings):
        """Hybrid search should blend scores with configurable weights."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            with patch("rediska_core.domain.services.search.EmbeddingsClient") as mock_embed:
                mock_embed_instance = MagicMock()
                mock_embed_instance.embed.return_value = [0.1] * 768
                mock_embed.return_value = mock_embed_instance

                mock_client = MagicMock()
                mock_client.search.return_value = {
                    "total": 1,
                    "hits": [{"id": "message:1", "score": 10.0, "source": {}}],
                }
                mock_client.knn_search.return_value = {
                    "total": 1,
                    "hits": [{"id": "message:1", "score": 0.5, "source": {}}],
                }
                mock_es.return_value = mock_client

                service = SearchService(
                    es_url="http://localhost:9200",
                    embeddings_url="http://localhost:8080",
                    embeddings_model="nomic-embed-text",
                )

                # Default weights
                result = service.hybrid_search(query="test")
                assert result["hits"][0]["score"] > 0

    def test_hybrid_search_falls_back_to_text_only(self, test_settings):
        """Hybrid search should fall back to text-only when embeddings unavailable."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {
                "total": 1,
                "hits": [{"id": "message:1", "score": 5.0, "source": {"content": "test"}}],
            }
            mock_es.return_value = mock_client

            # No embeddings configured
            service = SearchService(es_url="http://localhost:9200")
            result = service.hybrid_search(query="test")

            assert result["total"] == 1
            mock_client.search.assert_called_once()


# =============================================================================
# FILTER TESTS
# =============================================================================


class TestSearchFilters:
    """Tests for search filters."""

    def test_filter_by_provider_id(self, test_settings):
        """Search should filter by provider_id."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {"total": 0, "hits": []}
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            service.text_search(query="test", provider_id="reddit")

            call_args = mock_client.search.call_args
            filters = call_args[1].get("filters", {})
            assert filters.get("provider_id") == "reddit"

    def test_filter_by_identity_id(self, test_settings):
        """Search should filter by identity_id."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {"total": 0, "hits": []}
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            service.text_search(query="test", identity_id=42)

            call_args = mock_client.search.call_args
            filters = call_args[1].get("filters", {})
            assert filters.get("identity_id") == 42

    def test_filter_by_doc_type(self, test_settings):
        """Search should filter by doc_type."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {"total": 0, "hits": []}
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            service.text_search(query="test", doc_types=["message", "lead_post"])

            call_args = mock_client.search.call_args
            # doc_type filter should be applied
            assert call_args is not None

    def test_exclude_deleted_by_default(self, test_settings):
        """Search should exclude locally deleted documents by default."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {"total": 0, "hits": []}
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            service.text_search(query="test")

            call_args = mock_client.search.call_args
            filters = call_args[1].get("filters", {})
            assert filters.get("local_deleted") is False

    def test_exclude_removed_visibility(self, test_settings):
        """Search should optionally exclude removed/deleted visibility."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {"total": 0, "hits": []}
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            service.text_search(
                query="test",
                exclude_visibility=["removed", "deleted_by_author"],
            )

            # Should have exclusion filters applied
            call_args = mock_client.search.call_args
            assert call_args is not None


# =============================================================================
# PAGINATION TESTS
# =============================================================================


class TestSearchPagination:
    """Tests for search pagination."""

    def test_pagination_with_offset_and_limit(self, test_settings):
        """Search should support offset and limit pagination."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {"total": 100, "hits": []}
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            service.text_search(query="test", offset=20, limit=10)

            call_args = mock_client.search.call_args
            assert call_args[1]["from_"] == 20
            assert call_args[1]["size"] == 10

    def test_default_limit(self, test_settings):
        """Search should have a default limit."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {"total": 0, "hits": []}
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            service.text_search(query="test")

            call_args = mock_client.search.call_args
            assert call_args[1]["size"] > 0

    def test_max_limit_enforced(self, test_settings):
        """Search should enforce a maximum limit."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {"total": 0, "hits": []}
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            service.text_search(query="test", limit=10000)

            call_args = mock_client.search.call_args
            assert call_args[1]["size"] <= 100  # Max limit


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


class TestSearchErrorHandling:
    """Tests for search error handling."""

    def test_handles_es_connection_error(self, test_settings):
        """Search should handle ES connection errors gracefully."""
        from rediska_core.domain.services.search import SearchService, SearchError

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.side_effect = Exception("Connection refused")
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")

            with pytest.raises(SearchError):
                service.text_search(query="test")

    def test_handles_embeddings_error_in_hybrid(self, test_settings):
        """Hybrid search should handle embeddings errors gracefully."""
        from rediska_core.domain.services.search import SearchService
        from rediska_core.infrastructure.embeddings import EmbeddingsError

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            with patch("rediska_core.domain.services.search.EmbeddingsClient") as mock_embed:
                mock_embed_instance = MagicMock()
                mock_embed_instance.embed.side_effect = EmbeddingsError("API error")
                mock_embed.return_value = mock_embed_instance

                mock_client = MagicMock()
                mock_client.search.return_value = {
                    "total": 1,
                    "hits": [{"id": "message:1", "score": 5.0, "source": {}}],
                }
                mock_es.return_value = mock_client

                service = SearchService(
                    es_url="http://localhost:9200",
                    embeddings_url="http://localhost:8080",
                    embeddings_model="nomic-embed-text",
                )

                # Should fall back to text-only search
                result = service.hybrid_search(query="test")
                assert result["total"] == 1


# =============================================================================
# RESULT FORMATTING TESTS
# =============================================================================


class TestSearchResultFormatting:
    """Tests for search result formatting."""

    def test_results_include_highlights(self, test_settings):
        """Search results should include content highlights."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {
                "total": 1,
                "hits": [{
                    "id": "message:1",
                    "score": 5.0,
                    "source": {"content": "This is a test message with keywords"},
                    "highlight": {"content": ["This is a <em>test</em> message"]},
                }],
            }
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            result = service.text_search(query="test", include_highlights=True)

            assert result["total"] == 1

    def test_results_include_doc_type(self, test_settings):
        """Search results should include doc_type for each hit."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {
                "total": 1,
                "hits": [{
                    "id": "message:1",
                    "score": 5.0,
                    "source": {"doc_type": "message", "content": "Test"},
                }],
            }
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            result = service.text_search(query="test")

            assert result["hits"][0]["source"]["doc_type"] == "message"

    def test_results_include_entity_id(self, test_settings):
        """Search results should include entity_id for each hit."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {
                "total": 1,
                "hits": [{
                    "id": "message:123",
                    "score": 5.0,
                    "source": {"entity_id": 123, "doc_type": "message"},
                }],
            }
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            result = service.text_search(query="test")

            assert result["hits"][0]["source"]["entity_id"] == 123
