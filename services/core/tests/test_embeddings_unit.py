"""Unit tests for Epic 6.2 - Embeddings client wrapper.

Tests cover:
1. Client initialization with URL/model/API key
2. Generating embeddings for single text
3. Generating embeddings for batch text
4. Handling API errors
5. Handling connection failures
6. Dimension validation
"""

from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# CLIENT INITIALIZATION TESTS
# =============================================================================


class TestEmbeddingsClientInitialization:
    """Tests for embeddings client initialization."""

    def test_client_initializes_with_url(self, test_settings):
        """Client should initialize with embeddings URL."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient

        client = EmbeddingsClient(
            url="http://localhost:8080",
            model="nomic-embed-text",
        )

        assert client.url == "http://localhost:8080"
        assert client.model == "nomic-embed-text"

    def test_client_initializes_with_api_key(self, test_settings):
        """Client should accept optional API key."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient

        client = EmbeddingsClient(
            url="http://localhost:8080",
            model="nomic-embed-text",
            api_key="test-api-key",
        )

        assert client.api_key == "test-api-key"

    def test_client_uses_default_timeout(self, test_settings):
        """Client should have a default timeout."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient

        client = EmbeddingsClient(
            url="http://localhost:8080",
            model="nomic-embed-text",
        )

        assert client.timeout > 0


# =============================================================================
# SINGLE EMBEDDING TESTS
# =============================================================================


class TestSingleEmbedding:
    """Tests for generating single embeddings."""

    def test_embed_returns_vector(self, test_settings):
        """embed() should return a list of floats."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient

        with patch("httpx.Client") as mock_http:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [{"embedding": [0.1, 0.2, 0.3]}],
                "model": "nomic-embed-text",
                "usage": {"prompt_tokens": 5, "total_tokens": 5},
            }
            mock_client.post.return_value = mock_response
            mock_http.return_value.__enter__.return_value = mock_client

            client = EmbeddingsClient(
                url="http://localhost:8080",
                model="nomic-embed-text",
            )

            result = client.embed("Hello world")

            assert result is not None
            assert isinstance(result, list)
            assert len(result) == 3
            assert all(isinstance(v, float) for v in result)

    def test_embed_sends_correct_request(self, test_settings):
        """embed() should send correct request to API."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient

        with patch("httpx.Client") as mock_http:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [{"embedding": [0.1, 0.2, 0.3]}],
            }
            mock_client.post.return_value = mock_response
            mock_http.return_value.__enter__.return_value = mock_client

            client = EmbeddingsClient(
                url="http://localhost:8080",
                model="nomic-embed-text",
            )

            client.embed("Test text")

            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert "/v1/embeddings" in call_args[0][0]
            assert call_args[1]["json"]["input"] == "Test text"
            assert call_args[1]["json"]["model"] == "nomic-embed-text"

    def test_embed_includes_api_key_header(self, test_settings):
        """embed() should include API key in Authorization header."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient

        with patch("httpx.Client") as mock_http:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [{"embedding": [0.1, 0.2, 0.3]}],
            }
            mock_client.post.return_value = mock_response
            mock_http.return_value.__enter__.return_value = mock_client

            client = EmbeddingsClient(
                url="http://localhost:8080",
                model="nomic-embed-text",
                api_key="secret-key",
            )

            client.embed("Test text")

            call_args = mock_client.post.call_args
            headers = call_args[1].get("headers", {})
            assert "Authorization" in headers
            assert headers["Authorization"] == "Bearer secret-key"

    def test_embed_empty_text_returns_none(self, test_settings):
        """embed() with empty text should return None."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient

        client = EmbeddingsClient(
            url="http://localhost:8080",
            model="nomic-embed-text",
        )

        result = client.embed("")

        assert result is None

    def test_embed_whitespace_only_returns_none(self, test_settings):
        """embed() with whitespace-only text should return None."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient

        client = EmbeddingsClient(
            url="http://localhost:8080",
            model="nomic-embed-text",
        )

        result = client.embed("   \n\t  ")

        assert result is None


# =============================================================================
# BATCH EMBEDDING TESTS
# =============================================================================


class TestBatchEmbedding:
    """Tests for generating batch embeddings."""

    def test_embed_batch_returns_vectors(self, test_settings):
        """embed_batch() should return list of vectors."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient

        with patch("httpx.Client") as mock_http:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [
                    {"embedding": [0.1, 0.2, 0.3]},
                    {"embedding": [0.4, 0.5, 0.6]},
                ],
            }
            mock_client.post.return_value = mock_response
            mock_http.return_value.__enter__.return_value = mock_client

            client = EmbeddingsClient(
                url="http://localhost:8080",
                model="nomic-embed-text",
            )

            result = client.embed_batch(["Hello", "World"])

            assert result is not None
            assert len(result) == 2
            assert result[0] == [0.1, 0.2, 0.3]
            assert result[1] == [0.4, 0.5, 0.6]

    def test_embed_batch_empty_list_returns_empty(self, test_settings):
        """embed_batch() with empty list should return empty list."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient

        client = EmbeddingsClient(
            url="http://localhost:8080",
            model="nomic-embed-text",
        )

        result = client.embed_batch([])

        assert result == []

    def test_embed_batch_filters_empty_texts(self, test_settings):
        """embed_batch() should filter out empty texts."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient

        with patch("httpx.Client") as mock_http:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [
                    {"embedding": [0.1, 0.2, 0.3]},
                ],
            }
            mock_client.post.return_value = mock_response
            mock_http.return_value.__enter__.return_value = mock_client

            client = EmbeddingsClient(
                url="http://localhost:8080",
                model="nomic-embed-text",
            )

            result = client.embed_batch(["Hello", "", "  "])

            # Should only have made request for non-empty text
            call_args = mock_client.post.call_args
            assert call_args[1]["json"]["input"] == ["Hello"]


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    def test_embed_handles_api_error(self, test_settings):
        """embed() should handle API error responses gracefully."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient, EmbeddingsError

        with patch("httpx.Client") as mock_http:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_response.raise_for_status.side_effect = Exception("500 Error")
            mock_client.post.return_value = mock_response
            mock_http.return_value.__enter__.return_value = mock_client

            client = EmbeddingsClient(
                url="http://localhost:8080",
                model="nomic-embed-text",
            )

            with pytest.raises(EmbeddingsError) as exc_info:
                client.embed("Test text")

            assert "500" in str(exc_info.value) or "Error" in str(exc_info.value)

    def test_embed_handles_connection_failure(self, test_settings):
        """embed() should handle connection failures gracefully."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient, EmbeddingsError

        with patch("httpx.Client") as mock_http:
            mock_client = MagicMock()
            mock_client.post.side_effect = ConnectionError("Connection refused")
            mock_http.return_value.__enter__.return_value = mock_client

            client = EmbeddingsClient(
                url="http://localhost:8080",
                model="nomic-embed-text",
            )

            with pytest.raises(EmbeddingsError) as exc_info:
                client.embed("Test text")

            assert "Connection" in str(exc_info.value) or "connection" in str(exc_info.value)

    def test_embed_handles_timeout(self, test_settings):
        """embed() should handle timeout errors."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient, EmbeddingsError
        import httpx

        with patch("httpx.Client") as mock_http:
            mock_client = MagicMock()
            mock_client.post.side_effect = httpx.TimeoutException("Request timed out")
            mock_http.return_value.__enter__.return_value = mock_client

            client = EmbeddingsClient(
                url="http://localhost:8080",
                model="nomic-embed-text",
            )

            with pytest.raises(EmbeddingsError) as exc_info:
                client.embed("Test text")

            assert "timeout" in str(exc_info.value).lower() or "Timeout" in str(exc_info.value)

    def test_embed_handles_invalid_response(self, test_settings):
        """embed() should handle invalid response format."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient, EmbeddingsError

        with patch("httpx.Client") as mock_http:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"invalid": "response"}
            mock_client.post.return_value = mock_response
            mock_http.return_value.__enter__.return_value = mock_client

            client = EmbeddingsClient(
                url="http://localhost:8080",
                model="nomic-embed-text",
            )

            with pytest.raises(EmbeddingsError) as exc_info:
                client.embed("Test text")

            assert "response" in str(exc_info.value).lower() or "format" in str(exc_info.value).lower()


# =============================================================================
# DIMENSION TESTS
# =============================================================================


class TestEmbeddingDimensions:
    """Tests for embedding dimension handling."""

    def test_embed_returns_correct_dimensions(self, test_settings):
        """embed() should return vector with correct dimensions."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient

        # Simulate 768-dimension embedding (nomic-embed-text)
        embedding_768 = [0.1] * 768

        with patch("httpx.Client") as mock_http:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [{"embedding": embedding_768}],
            }
            mock_client.post.return_value = mock_response
            mock_http.return_value.__enter__.return_value = mock_client

            client = EmbeddingsClient(
                url="http://localhost:8080",
                model="nomic-embed-text",
            )

            result = client.embed("Test text")

            assert len(result) == 768

    def test_get_dimensions_returns_model_dimension(self, test_settings):
        """get_dimensions() should return the model's embedding dimension."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient

        # Test with sample embedding
        with patch("httpx.Client") as mock_http:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [{"embedding": [0.1] * 768}],
            }
            mock_client.post.return_value = mock_response
            mock_http.return_value.__enter__.return_value = mock_client

            client = EmbeddingsClient(
                url="http://localhost:8080",
                model="test-model",
            )

            dims = client.get_dimensions()

            assert dims == 768


# =============================================================================
# UTILITY TESTS
# =============================================================================


class TestClientUtilities:
    """Tests for client utility methods."""

    def test_health_check_returns_true_on_success(self, test_settings):
        """health_check() should return True when API is reachable."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient

        with patch("httpx.Client") as mock_http:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [{"embedding": [0.1, 0.2, 0.3]}],
            }
            mock_client.post.return_value = mock_response
            mock_http.return_value.__enter__.return_value = mock_client

            client = EmbeddingsClient(
                url="http://localhost:8080",
                model="nomic-embed-text",
            )

            result = client.health_check()

            assert result is True

    def test_health_check_returns_false_on_failure(self, test_settings):
        """health_check() should return False when API is unreachable."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient

        with patch("httpx.Client") as mock_http:
            mock_client = MagicMock()
            mock_client.post.side_effect = ConnectionError("Connection refused")
            mock_http.return_value.__enter__.return_value = mock_client

            client = EmbeddingsClient(
                url="http://localhost:8080",
                model="nomic-embed-text",
            )

            result = client.health_check()

            assert result is False

    def test_truncate_text_respects_max_tokens(self, test_settings):
        """truncate_text() should truncate long text."""
        from rediska_core.infrastructure.embeddings import EmbeddingsClient

        client = EmbeddingsClient(
            url="http://localhost:8080",
            model="nomic-embed-text",
        )

        long_text = "word " * 10000  # Very long text
        truncated = client.truncate_text(long_text, max_chars=1000)

        assert len(truncated) <= 1000
