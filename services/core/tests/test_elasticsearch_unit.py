"""Unit tests for Epic 6.1 - Elasticsearch client wrapper.

Tests cover:
1. ES client initialization
2. Index creation with correct mapping
3. Document indexing (upsert)
4. Document retrieval and deletion
5. Index existence checking
"""

from unittest.mock import MagicMock, patch

import pytest

# Patch path for all tests
ES_PATCH_PATH = "rediska_core.infrastructure.elasticsearch.Elasticsearch"


# =============================================================================
# CLIENT INITIALIZATION TESTS
# =============================================================================


class TestESClientInitialization:
    """Tests for ES client initialization."""

    def test_client_connects_with_url(self, test_settings):
        """ES client should connect using configured URL."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.ping.return_value = True
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)

            mock_es.assert_called_once()
            # The driver is constructed with the configured URL as its only host.
            assert mock_es.call_args[0][0] == [test_settings.elastic_url]
            assert client.url == test_settings.elastic_url

    def test_client_ping_returns_health(self, test_settings):
        """Client ping should return ES cluster health."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.ping.return_value = True
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            result = client.ping()

            assert result is True

    def test_client_handles_connection_failure(self, test_settings):
        """Client should handle connection failures gracefully."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.ping.side_effect = Exception("Connection refused")
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            result = client.ping()

            assert result is False


# =============================================================================
# INDEX MANAGEMENT TESTS
# =============================================================================


class TestIndexManagement:
    """Tests for index creation and management."""

    def test_create_index_with_mapping(self, test_settings):
        """Creating index should use correct mapping."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.indices.exists.return_value = False
            mock_instance.indices.create.return_value = {"acknowledged": True}
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            result = client.create_index("rediska_content_docs_v1")

            assert result is True
            mock_instance.indices.create.assert_called_once()

    def test_create_index_includes_identity_id(self, test_settings):
        """Index mapping should include identity_id field."""
        from rediska_core.infrastructure.elasticsearch import CONTENT_DOCS_MAPPING

        # Verify mapping includes identity_id
        properties = CONTENT_DOCS_MAPPING["mappings"]["properties"]
        assert "identity_id" in properties
        assert properties["identity_id"]["type"] == "long"

    def test_create_index_includes_provider_id(self, test_settings):
        """Index mapping should include provider_id field."""
        from rediska_core.infrastructure.elasticsearch import CONTENT_DOCS_MAPPING

        properties = CONTENT_DOCS_MAPPING["mappings"]["properties"]
        assert "provider_id" in properties
        assert properties["provider_id"]["type"] == "keyword"

    def test_create_index_includes_doc_type(self, test_settings):
        """Index mapping should include doc_type field."""
        from rediska_core.infrastructure.elasticsearch import CONTENT_DOCS_MAPPING

        properties = CONTENT_DOCS_MAPPING["mappings"]["properties"]
        assert "doc_type" in properties
        assert properties["doc_type"]["type"] == "keyword"

    def test_create_index_includes_text_content(self, test_settings):
        """Index mapping should include text content field for search."""
        from rediska_core.infrastructure.elasticsearch import CONTENT_DOCS_MAPPING

        properties = CONTENT_DOCS_MAPPING["mappings"]["properties"]
        assert "content" in properties
        assert properties["content"]["type"] == "text"

    def test_create_index_includes_embedding_vector(self, test_settings):
        """Index mapping should include embedding vector field."""
        from rediska_core.infrastructure.elasticsearch import CONTENT_DOCS_MAPPING

        properties = CONTENT_DOCS_MAPPING["mappings"]["properties"]
        assert "embedding" in properties
        assert properties["embedding"]["type"] == "dense_vector"

    def test_create_index_skips_if_exists(self, test_settings):
        """Create index should skip if index already exists."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.indices.exists.return_value = True
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            result = client.create_index("rediska_content_docs_v1")

            assert result is True
            mock_instance.indices.create.assert_not_called()

    def test_index_exists_returns_true(self, test_settings):
        """Index exists should return True when index exists."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.indices.exists.return_value = True
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            result = client.index_exists("rediska_content_docs_v1")

            assert result is True

    def test_index_exists_returns_false(self, test_settings):
        """Index exists should return False when index doesn't exist."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.indices.exists.return_value = False
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            result = client.index_exists("rediska_content_docs_v1")

            assert result is False


# =============================================================================
# DOCUMENT OPERATIONS TESTS
# =============================================================================


class TestDocumentOperations:
    """Tests for document indexing and retrieval."""

    def test_index_document_creates_doc(self, test_settings):
        """Index document should create a new document."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.index.return_value = {"result": "created", "_id": "msg_123"}
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            result = client.index_document(
                index="rediska_content_docs_v1",
                doc_id="message:123",
                document={
                    "doc_type": "message",
                    "entity_id": 123,
                    "provider_id": "reddit",
                    "identity_id": 1,
                    "content": "Hello world",
                },
            )

            assert result is True
            mock_instance.index.assert_called_once()

    def test_index_document_passes_id_body_and_refresh(self, test_settings):
        """Index document should forward doc_id, body and refresh to the driver."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.index.return_value = {"result": "updated", "_id": "msg_123"}
            mock_es.return_value = mock_instance

            document = {
                "doc_type": "message",
                "entity_id": 123,
                "content": "Updated content",
            }

            client = ElasticsearchClient(url=test_settings.elastic_url)
            result = client.index_document(
                index="rediska_content_docs_v1",
                doc_id="message:123",
                document=document,
                refresh=True,
            )

            assert result is True
            # index_document returns True on any non-exception, so the only
            # behaviour worth checking is the request it built.
            kwargs = mock_instance.index.call_args[1]
            assert kwargs["index"] == "rediska_content_docs_v1"
            assert kwargs["id"] == "message:123"
            assert kwargs["body"] == document
            assert kwargs["refresh"] is True

    def test_get_document_returns_doc(self, test_settings):
        """Get document should return the document if exists."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.get.return_value = {
                "_id": "message:123",
                "_source": {
                    "doc_type": "message",
                    "entity_id": 123,
                    "content": "Hello world",
                },
            }
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            result = client.get_document(
                index="rediska_content_docs_v1",
                doc_id="message:123",
            )

            assert result is not None
            assert result["entity_id"] == 123

    def test_get_document_returns_none_if_missing(self, test_settings):
        """Get document should return None if not found."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient, NotFoundError

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.get.side_effect = NotFoundError(404, "not_found", {})
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            result = client.get_document(
                index="rediska_content_docs_v1",
                doc_id="message:999",
            )

            assert result is None

    def test_delete_document_removes_doc(self, test_settings):
        """Delete document should remove the document."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.delete.return_value = {"result": "deleted"}
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            result = client.delete_document(
                index="rediska_content_docs_v1",
                doc_id="message:123",
            )

            assert result is True

    def test_delete_document_handles_missing(self, test_settings):
        """Delete document should handle missing documents gracefully."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient, NotFoundError

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.delete.side_effect = NotFoundError(404, "not_found", {})
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            result = client.delete_document(
                index="rediska_content_docs_v1",
                doc_id="message:999",
            )

            assert result is False


# =============================================================================
# BULK OPERATIONS TESTS
# =============================================================================


class TestBulkOperations:
    """Tests for bulk indexing operations."""

    def test_bulk_index_documents(self, test_settings):
        """Bulk index should index multiple documents."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.bulk.return_value = {"errors": False, "items": []}
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            documents = [
                {"_id": "message:1", "doc_type": "message", "content": "Hello"},
                {"_id": "message:2", "doc_type": "message", "content": "World"},
            ]

            result = client.bulk_index(
                index="rediska_content_docs_v1",
                documents=documents,
            )

            assert result["success"] is True
            mock_instance.bulk.assert_called_once()

    def test_bulk_index_handles_partial_failure(self, test_settings):
        """Bulk index should handle partial failures."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.bulk.return_value = {
                "errors": True,
                "items": [
                    {"index": {"_id": "message:1", "status": 201}},
                    {"index": {"_id": "message:2", "status": 400, "error": "bad request"}},
                ],
            }
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            documents = [
                {"_id": "message:1", "doc_type": "message", "content": "Hello"},
                {"_id": "message:2", "doc_type": "message", "content": ""},
            ]

            result = client.bulk_index(
                index="rediska_content_docs_v1",
                documents=documents,
            )

            assert result["success"] is False
            assert result["error_count"] > 0


# =============================================================================
# SEARCH TESTS
# =============================================================================


class TestSearch:
    """Tests for search operations."""

    def test_search_returns_results(self, test_settings):
        """Search should return matching documents."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.search.return_value = {
                "hits": {
                    "total": {"value": 2},
                    "hits": [
                        {"_id": "message:1", "_score": 1.5, "_source": {"content": "Hello"}},
                        {"_id": "message:2", "_score": 1.0, "_source": {"content": "World"}},
                    ],
                }
            }
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            result = client.search(
                index="rediska_content_docs_v1",
                query={"match": {"content": "hello"}},
            )

            assert result["total"] == 2
            assert len(result["hits"]) == 2

    def test_search_filters_by_provider_id(self, test_settings):
        """Search should support filtering by provider_id."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.search.return_value = {
                "hits": {"total": {"value": 0}, "hits": []}
            }
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            client.search(
                index="rediska_content_docs_v1",
                query={"match": {"content": "hello"}},
                filters={"provider_id": "reddit"},
            )

            # Filters become term clauses inside body.query.bool.filter.
            body = mock_instance.search.call_args[1]["body"]
            assert body["query"]["bool"]["filter"] == [
                {"term": {"provider_id": "reddit"}}
            ]
            assert body["query"]["bool"]["must"] == [{"match": {"content": "hello"}}]

    def test_search_filters_by_identity_id(self, test_settings):
        """Search should support filtering by identity_id."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.search.return_value = {
                "hits": {"total": {"value": 0}, "hits": []}
            }
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            client.search(
                index="rediska_content_docs_v1",
                query={"match": {"content": "hello"}},
                filters={"identity_id": 1},
            )

            body = mock_instance.search.call_args[1]["body"]
            assert body["query"]["bool"]["filter"] == [{"term": {"identity_id": 1}}]

    def test_search_list_filter_becomes_terms_clause(self, test_settings):
        """A list-valued filter should become a `terms` clause, not `term`."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.search.return_value = {
                "hits": {"total": {"value": 0}, "hits": []}
            }
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            client.search(
                index="rediska_content_docs_v1",
                query={"match": {"content": "hello"}},
                # None-valued filters are dropped entirely.
                filters={"doc_type": ["message", "lead_post"], "identity_id": None},
            )

            body = mock_instance.search.call_args[1]["body"]
            assert body["query"]["bool"]["filter"] == [
                {"terms": {"doc_type": ["message", "lead_post"]}}
            ]

    def test_search_multi_value_exclusion_becomes_must_not_terms(self, test_settings):
        """A multi-value exclusion becomes a `terms` clause under `must_not`."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.search.return_value = {
                "hits": {"total": {"value": 0}, "hits": []}
            }
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            client.search(
                index="rediska_content_docs_v1",
                query={"match": {"content": "hello"}},
                must_not={"remote_visibility": ["removed", "deleted_by_author"]},
            )

            bool_query = mock_instance.search.call_args[1]["body"]["query"]["bool"]
            assert bool_query["must_not"] == [
                {"terms": {"remote_visibility": ["removed", "deleted_by_author"]}}
            ]
            # must_not sits beside must/filter, so a document missing the
            # remote_visibility field does not match the clause and survives.
            # That is why exclusion is expressed negatively rather than as a
            # whitelist of the surviving values.
            assert "must" in bool_query and "filter" in bool_query

    def test_search_omits_must_not_when_nothing_is_excluded(self, test_settings):
        """No exclusions means no `must_not` key at all, not an empty list."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.search.return_value = {
                "hits": {"total": {"value": 0}, "hits": []}
            }
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            client.search(
                index="rediska_content_docs_v1",
                query={"match": {"content": "hello"}},
                must_not={"remote_visibility": []},
            )

            bool_query = mock_instance.search.call_args[1]["body"]["query"]["bool"]
            assert "must_not" not in bool_query

    def test_knn_search_applies_must_not(self, test_settings):
        """kNN exclusions land in the knn filter's bool must_not."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.search.return_value = {"hits": {"hits": []}}
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            client.knn_search(
                index="rediska_content_docs_v1",
                vector=[0.1, 0.2],
                filters={"provider_id": "reddit"},
                must_not={"remote_visibility": ["removed"]},
            )

            knn = mock_instance.search.call_args[1]["body"]["knn"]
            assert knn["filter"]["bool"]["must_not"] == [
                {"terms": {"remote_visibility": ["removed"]}}
            ]
            assert knn["filter"]["bool"]["filter"] == [
                {"term": {"provider_id": "reddit"}}
            ]

    def test_search_raises_on_an_inapplicable_filter(self, test_settings):
        """A filter the client cannot express fails rather than being dropped."""
        from rediska_core.infrastructure.elasticsearch import (
            ElasticsearchClient,
            UnsupportedFilterError,
        )

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)

            with pytest.raises(UnsupportedFilterError):
                client.search(
                    index="rediska_content_docs_v1",
                    query={"match_all": {}},
                    filters={"doc_type": {"nested": "object"}},
                )

            # And the request never went out with a widened filter set.
            mock_instance.search.assert_not_called()

    def test_search_carries_highlights_through(self, test_settings):
        """A highlight payload from ES survives to the caller."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.search.return_value = {
                "hits": {
                    "total": {"value": 1},
                    "hits": [
                        {
                            "_id": "message:1",
                            "_score": 1.0,
                            "_source": {"content": "a test message"},
                            "highlight": {"content": ["a <em>test</em> message"]},
                        }
                    ],
                }
            }
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            result = client.search(
                index="rediska_content_docs_v1",
                query={"match": {"content": "test"}},
                highlight={"fields": {"content": {}}},
            )

            assert mock_instance.search.call_args[1]["body"]["highlight"] == {
                "fields": {"content": {}}
            }
            assert result["hits"][0]["highlight"] == {
                "content": ["a <em>test</em> message"]
            }

    def test_search_with_pagination(self, test_settings):
        """Search should support pagination."""
        from rediska_core.infrastructure.elasticsearch import ElasticsearchClient

        with patch(ES_PATCH_PATH) as mock_es:
            mock_instance = MagicMock()
            mock_instance.search.return_value = {
                "hits": {"total": {"value": 100}, "hits": []}
            }
            mock_es.return_value = mock_instance

            client = ElasticsearchClient(url=test_settings.elastic_url)
            client.search(
                index="rediska_content_docs_v1",
                query={"match_all": {}},
                from_=10,
                size=20,
            )

            # Pagination goes into the query body, not as driver kwargs.
            body = mock_instance.search.call_args[1]["body"]
            assert body["from"] == 10
            assert body["size"] == 20
