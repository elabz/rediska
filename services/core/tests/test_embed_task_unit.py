"""Unit tests for Epic 6.2 - embed.generate task.

Tests cover:
1. Generating embeddings for content
2. Updating ES documents with embeddings
3. Handling missing entities
4. Handling empty text
5. Error handling
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from rediska_core.domain.models import (
    Conversation,
    ExternalAccount,
    Identity,
    Message,
    Provider,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def setup_test_data(db_session):
    """Set up test data for embedding tests."""
    # Create provider
    provider = Provider(
        provider_id="reddit",
        display_name="Reddit",
        enabled=True,
    )
    db_session.add(provider)
    db_session.flush()

    # Create identity
    identity = Identity(
        provider_id="reddit",
        external_username="my_account",
        external_user_id="t2_myid",
        display_name="My Account",
        is_default=True,
        is_active=True,
    )
    db_session.add(identity)
    db_session.flush()

    # Create counterpart account
    counterpart = ExternalAccount(
        provider_id="reddit",
        external_username="counterpart_user",
        external_user_id="t2_other",
        remote_status="active",
    )
    db_session.add(counterpart)
    db_session.flush()

    # Create conversation
    conversation = Conversation(
        provider_id="reddit",
        identity_id=identity.id,
        counterpart_account_id=counterpart.id,
        external_conversation_id="conv_123",
    )
    db_session.add(conversation)
    db_session.flush()

    # Create message
    message = Message(
        provider_id="reddit",
        conversation_id=conversation.id,
        identity_id=identity.id,
        direction="out",
        body_text="Hello world! This is a test message.",
        sent_at=datetime.now(timezone.utc),
        remote_visibility="visible",
    )
    db_session.add(message)
    db_session.flush()

    return {
        "provider": provider,
        "identity": identity,
        "counterpart": counterpart,
        "conversation": conversation,
        "message": message,
    }


# =============================================================================
# EMBEDDING SERVICE TESTS
# =============================================================================


class TestEmbeddingService:
    """Tests for EmbeddingService that wraps embedding generation + ES update."""

    def test_generate_embedding_for_message(self, db_session, setup_test_data):
        """generate_embedding should create embedding and update ES."""
        from rediska_core.domain.services.embedding import EmbeddingService

        with patch("rediska_core.domain.services.embedding.EmbeddingsClient") as mock_embed:
            with patch("rediska_core.domain.services.embedding.ElasticsearchClient") as mock_es:
                # Mock embeddings client
                mock_embed_instance = MagicMock()
                mock_embed_instance.embed.return_value = [0.1] * 768
                mock_embed.return_value = mock_embed_instance

                # Mock ES client
                mock_es_instance = MagicMock()
                mock_es_instance.update_document.return_value = True
                mock_es.return_value = mock_es_instance

                message = setup_test_data["message"]
                service = EmbeddingService(
                    db=db_session,
                    embeddings_url="http://localhost:8080",
                    embeddings_model="nomic-embed-text",
                    es_url="http://localhost:9200",
                )

                result = service.generate_embedding(
                    doc_type="message",
                    entity_id=message.id,
                    text=message.body_text,
                )

                assert result["success"] is True
                mock_embed_instance.embed.assert_called_once()
                mock_es_instance.update_document.assert_called_once()

    def test_generate_embedding_uses_correct_doc_id(self, db_session, setup_test_data):
        """generate_embedding should use correct ES doc_id format."""
        from rediska_core.domain.services.embedding import EmbeddingService

        with patch("rediska_core.domain.services.embedding.EmbeddingsClient") as mock_embed:
            with patch("rediska_core.domain.services.embedding.ElasticsearchClient") as mock_es:
                mock_embed_instance = MagicMock()
                mock_embed_instance.embed.return_value = [0.1] * 768
                mock_embed.return_value = mock_embed_instance

                mock_es_instance = MagicMock()
                mock_es_instance.update_document.return_value = True
                mock_es.return_value = mock_es_instance

                message = setup_test_data["message"]
                service = EmbeddingService(
                    db=db_session,
                    embeddings_url="http://localhost:8080",
                    embeddings_model="nomic-embed-text",
                    es_url="http://localhost:9200",
                )

                service.generate_embedding(
                    doc_type="message",
                    entity_id=message.id,
                    text=message.body_text,
                )

                call_args = mock_es_instance.update_document.call_args
                assert call_args[1]["doc_id"] == f"message:{message.id}"

    def test_generate_embedding_stores_vector(self, db_session, setup_test_data):
        """generate_embedding should store embedding vector in ES doc."""
        from rediska_core.domain.services.embedding import EmbeddingService

        expected_embedding = [0.1, 0.2, 0.3] * 256  # 768 dims

        with patch("rediska_core.domain.services.embedding.EmbeddingsClient") as mock_embed:
            with patch("rediska_core.domain.services.embedding.ElasticsearchClient") as mock_es:
                mock_embed_instance = MagicMock()
                mock_embed_instance.embed.return_value = expected_embedding
                mock_embed.return_value = mock_embed_instance

                mock_es_instance = MagicMock()
                mock_es_instance.update_document.return_value = True
                mock_es.return_value = mock_es_instance

                message = setup_test_data["message"]
                service = EmbeddingService(
                    db=db_session,
                    embeddings_url="http://localhost:8080",
                    embeddings_model="nomic-embed-text",
                    es_url="http://localhost:9200",
                )

                service.generate_embedding(
                    doc_type="message",
                    entity_id=message.id,
                    text=message.body_text,
                )

                call_args = mock_es_instance.update_document.call_args
                updates = call_args[1]["updates"]
                assert "embedding" in updates
                assert updates["embedding"] == expected_embedding

    def test_generate_embedding_empty_text_returns_skipped(self, db_session, setup_test_data):
        """generate_embedding with empty text should return skipped status."""
        from rediska_core.domain.services.embedding import EmbeddingService

        service = EmbeddingService(
            db=db_session,
            embeddings_url="http://localhost:8080",
            embeddings_model="nomic-embed-text",
            es_url="http://localhost:9200",
        )

        result = service.generate_embedding(
            doc_type="message",
            entity_id=1,
            text="",
        )

        assert result["success"] is True
        assert result["status"] == "skipped"
        assert "empty" in result.get("reason", "").lower()

    def test_generate_embedding_truncates_long_text(self, db_session, setup_test_data):
        """generate_embedding should truncate very long text."""
        from rediska_core.domain.services.embedding import EmbeddingService

        long_text = "word " * 50000  # Very long text

        with patch("rediska_core.domain.services.embedding.EmbeddingsClient") as mock_embed:
            with patch("rediska_core.domain.services.embedding.ElasticsearchClient") as mock_es:
                mock_embed_instance = MagicMock()
                mock_embed_instance.embed.return_value = [0.1] * 768
                mock_embed_instance.truncate_text.return_value = "word " * 1000
                mock_embed.return_value = mock_embed_instance

                mock_es_instance = MagicMock()
                mock_es_instance.update_document.return_value = True
                mock_es.return_value = mock_es_instance

                message = setup_test_data["message"]
                service = EmbeddingService(
                    db=db_session,
                    embeddings_url="http://localhost:8080",
                    embeddings_model="nomic-embed-text",
                    es_url="http://localhost:9200",
                )

                result = service.generate_embedding(
                    doc_type="message",
                    entity_id=message.id,
                    text=long_text,
                )

                assert result["success"] is True
                # Should have called truncate_text
                mock_embed_instance.truncate_text.assert_called_once()


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


class TestEmbeddingServiceErrors:
    """Tests for error handling in EmbeddingService."""

    def test_generate_embedding_handles_embeddings_api_error(self, db_session, setup_test_data):
        """generate_embedding should handle embeddings API errors."""
        from rediska_core.domain.services.embedding import EmbeddingService
        from rediska_core.infrastructure.embeddings import EmbeddingsError

        with patch("rediska_core.domain.services.embedding.EmbeddingsClient") as mock_embed:
            with patch("rediska_core.domain.services.embedding.ElasticsearchClient") as mock_es:
                mock_embed_instance = MagicMock()
                mock_embed_instance.embed.side_effect = EmbeddingsError("API error")
                mock_embed.return_value = mock_embed_instance

                mock_es_instance = MagicMock()
                mock_es.return_value = mock_es_instance

                message = setup_test_data["message"]
                service = EmbeddingService(
                    db=db_session,
                    embeddings_url="http://localhost:8080",
                    embeddings_model="nomic-embed-text",
                    es_url="http://localhost:9200",
                )

                result = service.generate_embedding(
                    doc_type="message",
                    entity_id=message.id,
                    text=message.body_text,
                )

                assert result["success"] is False
                assert "error" in result

    def test_generate_embedding_handles_es_update_error(self, db_session, setup_test_data):
        """generate_embedding should handle ES update errors."""
        from rediska_core.domain.services.embedding import EmbeddingService

        with patch("rediska_core.domain.services.embedding.EmbeddingsClient") as mock_embed:
            with patch("rediska_core.domain.services.embedding.ElasticsearchClient") as mock_es:
                mock_embed_instance = MagicMock()
                mock_embed_instance.embed.return_value = [0.1] * 768
                mock_embed.return_value = mock_embed_instance

                mock_es_instance = MagicMock()
                mock_es_instance.update_document.return_value = False
                mock_es.return_value = mock_es_instance

                message = setup_test_data["message"]
                service = EmbeddingService(
                    db=db_session,
                    embeddings_url="http://localhost:8080",
                    embeddings_model="nomic-embed-text",
                    es_url="http://localhost:9200",
                )

                result = service.generate_embedding(
                    doc_type="message",
                    entity_id=message.id,
                    text=message.body_text,
                )

                assert result["success"] is False
                assert "ES update failed" in result.get("error", "")


# =============================================================================
# BATCH EMBEDDING TESTS
# =============================================================================


class TestBatchEmbedding:
    """Tests for batch embedding generation."""

    def test_generate_embeddings_batch(self, db_session, setup_test_data):
        """generate_embeddings_batch should process multiple items."""
        from rediska_core.domain.services.embedding import EmbeddingService

        # Add more messages
        conv = setup_test_data["conversation"]
        identity = setup_test_data["identity"]
        messages = []
        for i in range(3):
            msg = Message(
                provider_id="reddit",
                conversation_id=conv.id,
                identity_id=identity.id,
                direction="in" if i % 2 == 0 else "out",
                body_text=f"Message {i}",
                sent_at=datetime.now(timezone.utc),
                remote_visibility="visible",
            )
            db_session.add(msg)
            messages.append(msg)
        db_session.flush()

        with patch("rediska_core.domain.services.embedding.EmbeddingsClient") as mock_embed:
            with patch("rediska_core.domain.services.embedding.ElasticsearchClient") as mock_es:
                mock_embed_instance = MagicMock()
                mock_embed_instance.embed_batch.return_value = [
                    [0.1] * 768,
                    [0.2] * 1024,
                    [0.3] * 1024,
                ]
                mock_embed.return_value = mock_embed_instance

                mock_es_instance = MagicMock()
                mock_es_instance.bulk_index.return_value = {"success": True, "indexed": 3}
                mock_es.return_value = mock_es_instance

                service = EmbeddingService(
                    db=db_session,
                    embeddings_url="http://localhost:8080",
                    embeddings_model="nomic-embed-text",
                    es_url="http://localhost:9200",
                )

                items = [
                    {"doc_type": "message", "entity_id": msg.id, "text": msg.body_text}
                    for msg in messages
                ]
                result = service.generate_embeddings_batch(items)

                assert result["success"] is True
                assert result["processed"] == 3


# =============================================================================
# INTEGRATION WITH INDEXING SERVICE TESTS
# =============================================================================


class TestEmbeddingWithIndexing:
    """Tests for embedding generation integrated with indexing."""

    def test_embed_after_index_updates_existing_doc(self, db_session, setup_test_data):
        """Embedding should update existing indexed document."""
        from rediska_core.domain.services.embedding import EmbeddingService

        with patch("rediska_core.domain.services.embedding.EmbeddingsClient") as mock_embed:
            with patch("rediska_core.domain.services.embedding.ElasticsearchClient") as mock_es:
                mock_embed_instance = MagicMock()
                mock_embed_instance.embed.return_value = [0.1] * 768
                mock_embed.return_value = mock_embed_instance

                mock_es_instance = MagicMock()
                mock_es_instance.update_document.return_value = True
                mock_es.return_value = mock_es_instance

                message = setup_test_data["message"]
                service = EmbeddingService(
                    db=db_session,
                    embeddings_url="http://localhost:8080",
                    embeddings_model="nomic-embed-text",
                    es_url="http://localhost:9200",
                )

                result = service.generate_embedding(
                    doc_type="message",
                    entity_id=message.id,
                    text=message.body_text,
                )

                assert result["success"] is True
                # Should use update_document, not index_document
                mock_es_instance.update_document.assert_called_once()
