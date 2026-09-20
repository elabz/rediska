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
                mock_embed_instance.embed_query.return_value = [0.1] * 768
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
                mock_embed_instance.embed_query.assert_called_once()
                mock_client.knn_search.assert_called_once()

    def test_vector_search_uses_query_embedding(self, test_settings):
        """Vector search should embed the query and use kNN."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            with patch("rediska_core.domain.services.search.EmbeddingsClient") as mock_embed:
                expected_vector = [0.5] * 768
                mock_embed_instance = MagicMock()
                mock_embed_instance.embed_query.return_value = expected_vector
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

    def test_vector_search_without_embeddings_config_raises(self, test_settings):
        """Vector mode says it cannot run rather than returning nothing.

        An empty result set is indistinguishable from "nothing is similar",
        which is the lie this change exists to stop telling.
        """
        import pytest

        from rediska_core.domain.services.search import (
            REASON_NOT_CONFIGURED,
            SearchService,
            SemanticUnavailableError,
        )

        service = SearchService(es_url="http://localhost:9200")
        with pytest.raises(SemanticUnavailableError) as exc:
            service.vector_search(query="test")

        assert exc.value.reason == REASON_NOT_CONFIGURED

    def test_vector_search_filters_on_the_configured_model(self, test_settings):
        """Vectors written by another model are a different space."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            with patch("rediska_core.domain.services.search.EmbeddingsClient") as mock_embed:
                mock_embed.return_value.embed_query.return_value = [0.1] * 8
                mock_client = MagicMock()
                mock_client.knn_search.return_value = {"total": 0, "hits": []}
                mock_es.return_value = mock_client

                service = SearchService(
                    es_url="http://localhost:9200",
                    embeddings_url="http://localhost:8080",
                    embeddings_model="nomic-embed-text",
                )
                service.vector_search(query="test")

                filters = mock_client.knn_search.call_args[1]["filters"]
                assert filters["embedding_model"] == "nomic-embed-text"


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
                mock_embed_instance.embed_query.return_value = [0.1] * 768
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
                mock_embed_instance.embed_query.return_value = [0.1] * 768
                mock_embed.return_value = mock_embed_instance

                mock_client = MagicMock()
                # Opposite rankings so the two weights land on different RRF
                # denominators; identical ranks would make every weight split
                # produce the same blended score.
                mock_client.search.return_value = {
                    "total": 2,
                    "hits": [
                        {"id": "message:1", "score": 10.0, "source": {}},
                        {"id": "message:2", "score": 8.0, "source": {}},
                    ],
                }
                mock_client.knn_search.return_value = {
                    "total": 2,
                    "hits": [
                        {"id": "message:2", "score": 0.9, "source": {}},
                        {"id": "message:1", "score": 0.5, "source": {}},
                    ],
                }
                mock_es.return_value = mock_client

                service = SearchService(
                    es_url="http://localhost:9200",
                    embeddings_url="http://localhost:8080",
                    embeddings_model="nomic-embed-text",
                )

                # RRF with k=60: score = weight / (60 + rank + 1), summed
                # across both result lists. message:1 is BM25 rank 0 and kNN
                # rank 1; message:2 is the reverse.
                result = service.hybrid_search(query="test")
                scores = {hit["id"]: hit["score"] for hit in result["hits"]}
                assert scores["message:1"] == pytest.approx(0.3 / 61 + 0.7 / 62)
                assert scores["message:2"] == pytest.approx(0.3 / 62 + 0.7 / 61)
                # kNN-weighted by default, so message:2 wins.
                assert result["hits"][0]["id"] == "message:2"

                # Flipping the weights must change the scores and the order.
                bm25_heavy = service.hybrid_search(
                    query="test", bm25_weight=0.9, knn_weight=0.1
                )
                heavy_scores = {h["id"]: h["score"] for h in bm25_heavy["hits"]}
                assert heavy_scores["message:1"] == pytest.approx(0.9 / 61 + 0.1 / 62)
                assert heavy_scores["message:1"] != scores["message:1"]
                assert bm25_heavy["hits"][0]["id"] == "message:1"

    def test_hybrid_search_falls_back_to_text_only(self, test_settings):
        """Hybrid search should fall back to text-only when embeddings unavailable."""
        from rediska_core.domain.services.search import (
            REASON_NOT_CONFIGURED,
            SearchService,
        )

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
            assert result["semantic_used"] is False
            assert result["semantic_unavailable_reason"] == REASON_NOT_CONFIGURED
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
            filters = call_args[1].get("filters", {})
            # doc_types is passed through under the singular ES field name.
            assert filters.get("doc_type") == ["message", "lead_post"]

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
        """Search should exclude the requested remote_visibility values.

        This used to be an xfail pinning a live bug: _build_filters accepted
        exclude_visibility and silently dropped it, so removed/deleted content
        came back to callers who explicitly asked to exclude it.
        """
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

            # Exclusions are negative constraints, so they travel as must_not
            # rather than as positive filters.
            must_not = mock_client.search.call_args[1]["must_not"]
            assert set(must_not["remote_visibility"]) == {
                "removed",
                "deleted_by_author",
            }

    def test_exclude_visibility_is_a_negative_clause_not_a_filter(self, test_settings):
        """The exclusion must not leak into the positive filter dict."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {"total": 0, "hits": []}
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            service.text_search(query="test", exclude_visibility=["removed"])

            filters = mock_client.search.call_args[1]["filters"]
            assert "remote_visibility" not in filters

    def test_remote_deleted_excluded_by_default(self, test_settings):
        """Without include_deleted, remote-deleted content is excluded."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {"total": 0, "hits": []}
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            service.text_search(query="test")

            kwargs = mock_client.search.call_args[1]
            assert set(kwargs["must_not"]["remote_visibility"]) == {
                "removed",
                "deleted_by_author",
            }
            # Locally deleted content is excluded by the positive filter.
            assert kwargs["filters"]["local_deleted"] is False

    def test_include_deleted_drops_the_default_exclusion(self, test_settings):
        """include_deleted opts the caller in to hidden content."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {"total": 0, "hits": []}
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            service.text_search(query="test", include_deleted=True)

            kwargs = mock_client.search.call_args[1]
            assert kwargs["must_not"] == {}
            assert "local_deleted" not in kwargs["filters"]

    def test_caller_exclusions_merge_with_the_default(self, test_settings):
        """A caller-supplied value adds to the default exclusion set."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {"total": 0, "hits": []}
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            service.text_search(query="test", exclude_visibility=["send_failed"])

            must_not = mock_client.search.call_args[1]["must_not"]
            assert set(must_not["remote_visibility"]) == {
                "removed",
                "deleted_by_author",
                "send_failed",
            }

    def test_vector_search_applies_exclusions(self, test_settings):
        """Exclusions reach kNN search too, not just BM25."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            with patch(
                "rediska_core.domain.services.search.EmbeddingsClient"
            ) as mock_emb:
                mock_client = MagicMock()
                mock_client.knn_search.return_value = {"total": 0, "hits": []}
                mock_es.return_value = mock_client
                mock_emb.return_value.embed_query.return_value = [0.1] * 8

                service = SearchService(
                    es_url="http://localhost:9200",
                    embeddings_url="http://localhost:8080",
                    embeddings_model="nomic-embed-text",
                )
                service.vector_search(query="test", exclude_visibility=["removed"])

                must_not = mock_client.knn_search.call_args[1]["must_not"]
                assert "removed" in must_not["remote_visibility"]

    def test_unapplicable_filter_fails_the_request(self, test_settings):
        """A filter the search layer cannot apply raises instead of widening.

        Returning results when a supplied filter was dropped is the same
        failure mode as the bug above, one layer up.
        """
        from rediska_core.domain.services.search import (
            SearchService,
            UnsupportedFilterError,
        )

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.side_effect = UnsupportedFilterError(
                "Cannot build a query clause for filter 'doc_type'"
            )
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")

            # Must surface as UnsupportedFilterError, not be wrapped into a
            # generic SearchError or swallowed into an empty result set.
            with pytest.raises(UnsupportedFilterError):
                service.text_search(query="test")


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

            from rediska_core.domain.services.search import MAX_LIMIT

            call_args = mock_client.search.call_args
            assert call_args[1]["size"] == MAX_LIMIT


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
        from rediska_core.domain.services.search import (
            REASON_ENDPOINT_FAILED,
            SearchService,
        )
        from rediska_core.infrastructure.embeddings import EmbeddingsError

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            with patch("rediska_core.domain.services.search.EmbeddingsClient") as mock_embed:
                mock_embed_instance = MagicMock()
                mock_embed_instance.embed_query.side_effect = EmbeddingsError("API error")
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

                # Should fall back to text-only search, and say why
                result = service.hybrid_search(query="test")
                assert result["total"] == 1
                assert result["semantic_used"] is False
                assert result["semantic_unavailable_reason"] == REASON_ENDPOINT_FAILED


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
            # text_search returns the ES result unchanged, so a highlight
            # payload from ES must survive to the caller untouched.
            assert result["hits"][0]["highlight"] == {
                "content": ["This is a <em>test</em> message"]
            }

    def test_include_highlights_requests_highlighting_from_es(self, test_settings):
        """include_highlights=True should ask ES for a highlight section.

        Formerly an xfail: the parameter was accepted and never added to the
        request, so ES was never asked to highlight anything.
        """
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {"total": 0, "hits": []}
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            service.text_search(query="test", include_highlights=True)

            highlight = mock_client.search.call_args[1]["highlight"]
            assert "content" in highlight["fields"]

    def test_highlights_omitted_when_not_requested(self, test_settings):
        """Without include_highlights, no highlight section is requested."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {"total": 0, "hits": []}
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            service.text_search(query="test")

            assert mock_client.search.call_args[1]["highlight"] is None

    def test_text_search_builds_multi_match_request(self, test_settings):
        """text_search should build a boosted, fuzzy multi_match over the index.

        Hits are returned from ES unchanged, so the request is the only part
        of text_search worth asserting on.
        """
        from rediska_core.domain.services.search import SearchService
        from rediska_core.infrastructure.elasticsearch import CONTENT_DOCS_INDEX

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {"total": 0, "hits": []}
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            service.text_search(query="test")

            kwargs = mock_client.search.call_args[1]
            assert kwargs["index"] == CONTENT_DOCS_INDEX
            assert kwargs["query"] == {
                "multi_match": {
                    "query": "test",
                    "fields": ["content^2", "title^3"],
                    "type": "best_fields",
                    "fuzziness": "AUTO",
                }
            }

    def test_phrase_mode_disables_fuzziness(self, test_settings):
        """phrase=True should switch to a phrase match with no fuzziness."""
        from rediska_core.domain.services.search import SearchService

        with patch("rediska_core.domain.services.search.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.search.return_value = {"total": 0, "hits": []}
            mock_es.return_value = mock_client

            service = SearchService(es_url="http://localhost:9200")
            service.text_search(query="exact words", phrase=True)

            multi_match = mock_client.search.call_args[1]["query"]["multi_match"]
            assert multi_match["type"] == "phrase"
            assert "fuzziness" not in multi_match
