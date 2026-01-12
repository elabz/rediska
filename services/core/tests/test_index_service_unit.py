"""Unit tests for Epic 6.1 - Content indexing service.

Tests cover:
1. Document conversion from DB entities to ES documents
2. Upsert operations for different document types
3. Identity and provider filtering
4. Index on startup / admin operation
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
    """Set up test data for indexing tests."""
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
        body_text="Hello world!",
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
# DOCUMENT CONVERSION TESTS
# =============================================================================


class TestDocumentConversion:
    """Tests for converting DB entities to ES documents."""

    def test_message_to_document_includes_required_fields(
        self, db_session, setup_test_data
    ):
        """Message document should include all required fields."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        message = setup_test_data["message"]

        doc = service.message_to_document(message)

        assert doc["doc_type"] == "message"
        assert doc["entity_id"] == message.id
        assert doc["provider_id"] == "reddit"
        assert doc["identity_id"] == setup_test_data["identity"].id
        assert doc["content"] == "Hello world!"

    def test_message_to_document_includes_conversation_id(
        self, db_session, setup_test_data
    ):
        """Message document should include conversation_id."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        message = setup_test_data["message"]

        doc = service.message_to_document(message)

        assert doc["conversation_id"] == setup_test_data["conversation"].id

    def test_message_to_document_includes_direction(
        self, db_session, setup_test_data
    ):
        """Message document should include direction."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        message = setup_test_data["message"]

        doc = service.message_to_document(message)

        assert doc["direction"] == "out"

    def test_message_to_document_includes_visibility(
        self, db_session, setup_test_data
    ):
        """Message document should include visibility for filtering."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        message = setup_test_data["message"]

        doc = service.message_to_document(message)

        assert doc["remote_visibility"] == "visible"

    def test_message_to_document_includes_timestamp(
        self, db_session, setup_test_data
    ):
        """Message document should include created_at timestamp."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        message = setup_test_data["message"]

        doc = service.message_to_document(message)

        assert "created_at" in doc
        assert doc["indexed_at"] is not None


# =============================================================================
# UPSERT OPERATIONS TESTS
# =============================================================================


class TestUpsertOperations:
    """Tests for upsert_content operations."""

    def test_upsert_message_indexes_document(
        self, db_session, setup_test_data
    ):
        """Upsert message should index the document in ES."""
        from rediska_core.domain.services.indexing import IndexingService

        with patch("rediska_core.domain.services.indexing.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.index_document.return_value = True
            mock_es.return_value = mock_client

            service = IndexingService(
                db=db_session,
                es_url="http://localhost:9200",
            )
            message = setup_test_data["message"]

            result = service.upsert_content("message", message.id)

            assert result is True
            mock_client.index_document.assert_called_once()

    def test_upsert_message_uses_correct_doc_id(
        self, db_session, setup_test_data
    ):
        """Upsert should use correct document ID format."""
        from rediska_core.domain.services.indexing import IndexingService

        with patch("rediska_core.domain.services.indexing.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.index_document.return_value = True
            mock_es.return_value = mock_client

            service = IndexingService(
                db=db_session,
                es_url="http://localhost:9200",
            )
            message = setup_test_data["message"]

            service.upsert_content("message", message.id)

            call_args = mock_client.index_document.call_args
            assert call_args[1]["doc_id"] == f"message:{message.id}"

    def test_upsert_missing_entity_returns_false(
        self, db_session, setup_test_data
    ):
        """Upsert of non-existent entity should return False."""
        from rediska_core.domain.services.indexing import IndexingService

        with patch("rediska_core.domain.services.indexing.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_es.return_value = mock_client

            service = IndexingService(
                db=db_session,
                es_url="http://localhost:9200",
            )

            result = service.upsert_content("message", 99999)

            assert result is False
            mock_client.index_document.assert_not_called()

    def test_upsert_invalid_doc_type_raises_error(
        self, db_session, setup_test_data
    ):
        """Upsert with invalid doc_type should raise ValueError."""
        from rediska_core.domain.services.indexing import IndexingService

        with patch("rediska_core.domain.services.indexing.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_es.return_value = mock_client

            service = IndexingService(
                db=db_session,
                es_url="http://localhost:9200",
            )

            with pytest.raises(ValueError) as exc_info:
                service.upsert_content("invalid_type", 1)

            assert "Unknown doc_type" in str(exc_info.value)


# =============================================================================
# DELETE OPERATIONS TESTS
# =============================================================================


class TestDeleteOperations:
    """Tests for delete_content operations."""

    def test_delete_content_removes_document(
        self, db_session, setup_test_data
    ):
        """Delete content should remove document from ES."""
        from rediska_core.domain.services.indexing import IndexingService

        with patch("rediska_core.domain.services.indexing.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.delete_document.return_value = True
            mock_es.return_value = mock_client

            service = IndexingService(
                db=db_session,
                es_url="http://localhost:9200",
            )
            message = setup_test_data["message"]

            result = service.delete_content("message", message.id)

            assert result is True
            mock_client.delete_document.assert_called_once()


# =============================================================================
# ENSURE INDEX TESTS
# =============================================================================


class TestEnsureIndex:
    """Tests for index creation on startup."""

    def test_ensure_index_creates_index_if_missing(self, db_session):
        """Ensure index should create the index if it doesn't exist."""
        from rediska_core.domain.services.indexing import IndexingService

        with patch("rediska_core.domain.services.indexing.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.ensure_index.return_value = True
            mock_es.return_value = mock_client

            service = IndexingService(
                db=db_session,
                es_url="http://localhost:9200",
            )

            result = service.ensure_index()

            assert result is True
            mock_client.ensure_index.assert_called_once()

    def test_ensure_index_skips_if_exists(self, db_session):
        """Ensure index should skip creation if index exists."""
        from rediska_core.domain.services.indexing import IndexingService

        with patch("rediska_core.domain.services.indexing.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.ensure_index.return_value = True
            mock_es.return_value = mock_client

            service = IndexingService(
                db=db_session,
                es_url="http://localhost:9200",
            )

            result = service.ensure_index()

            assert result is True
            mock_client.ensure_index.assert_called_once()


# =============================================================================
# BULK INDEXING TESTS
# =============================================================================


class TestBulkIndexing:
    """Tests for bulk indexing operations."""

    def test_bulk_index_messages_for_conversation(
        self, db_session, setup_test_data
    ):
        """Bulk index should index all messages in a conversation."""
        from rediska_core.domain.services.indexing import IndexingService

        # Add more messages
        conv = setup_test_data["conversation"]
        for i in range(5):
            msg = Message(
                provider_id="reddit",
                conversation_id=conv.id,
                identity_id=setup_test_data["identity"].id,
                direction="in" if i % 2 == 0 else "out",
                body_text=f"Message {i}",
                sent_at=datetime.now(timezone.utc),
                remote_visibility="visible",
            )
            db_session.add(msg)
        db_session.flush()

        with patch("rediska_core.domain.services.indexing.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.bulk_index.return_value = {"success": True, "indexed": 6}
            mock_es.return_value = mock_client

            service = IndexingService(
                db=db_session,
                es_url="http://localhost:9200",
            )

            result = service.bulk_index_conversation(conv.id)

            assert result["success"] is True
            mock_client.bulk_index.assert_called_once()


# =============================================================================
# LEAD POST INDEXING TESTS (Epic 6.4)
# =============================================================================


@pytest.fixture
def setup_lead_post_data(db_session):
    """Set up lead post test data."""
    from rediska_core.domain.models import LeadPost

    # Create provider
    provider = Provider(
        provider_id="reddit",
        display_name="Reddit",
        enabled=True,
    )
    db_session.add(provider)
    db_session.flush()

    # Create counterpart account for author
    author = ExternalAccount(
        provider_id="reddit",
        external_username="lead_author",
        external_user_id="t2_author",
        remote_status="active",
    )
    db_session.add(author)
    db_session.flush()

    # Create lead post
    lead_post = LeadPost(
        provider_id="reddit",
        source_location="r/programming",
        external_post_id="abc123",
        post_url="https://reddit.com/r/programming/comments/abc123",
        author_account_id=author.id,
        title="Looking for Python developers",
        body_text="We need experienced Python developers for a project.",
        status="saved",
        remote_visibility="visible",
    )
    db_session.add(lead_post)
    db_session.flush()

    return {
        "provider": provider,
        "author": author,
        "lead_post": lead_post,
    }


class TestLeadPostDocumentConversion:
    """Tests for converting LeadPost entities to ES documents."""

    def test_lead_post_to_document_includes_required_fields(
        self, db_session, setup_lead_post_data
    ):
        """LeadPost document should include all required fields."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        lead_post = setup_lead_post_data["lead_post"]

        doc = service.lead_post_to_document(lead_post)

        assert doc["doc_type"] == "lead_post"
        assert doc["entity_id"] == lead_post.id
        assert doc["provider_id"] == "reddit"
        assert doc["source_location"] == "r/programming"

    def test_lead_post_to_document_includes_title(
        self, db_session, setup_lead_post_data
    ):
        """LeadPost document should include title field."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        lead_post = setup_lead_post_data["lead_post"]

        doc = service.lead_post_to_document(lead_post)

        assert doc["title"] == "Looking for Python developers"

    def test_lead_post_to_document_includes_content(
        self, db_session, setup_lead_post_data
    ):
        """LeadPost document should include body_text as content."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        lead_post = setup_lead_post_data["lead_post"]

        doc = service.lead_post_to_document(lead_post)

        assert "Python developers" in doc["content"]

    def test_lead_post_to_document_includes_author_account(
        self, db_session, setup_lead_post_data
    ):
        """LeadPost document should include author account_id."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        lead_post = setup_lead_post_data["lead_post"]

        doc = service.lead_post_to_document(lead_post)

        assert doc["account_id"] == setup_lead_post_data["author"].id

    def test_lead_post_to_document_includes_post_url(
        self, db_session, setup_lead_post_data
    ):
        """LeadPost document should include post_url."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        lead_post = setup_lead_post_data["lead_post"]

        doc = service.lead_post_to_document(lead_post)

        assert doc["post_url"] == "https://reddit.com/r/programming/comments/abc123"

    def test_lead_post_to_document_includes_visibility(
        self, db_session, setup_lead_post_data
    ):
        """LeadPost document should include visibility for filtering."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        lead_post = setup_lead_post_data["lead_post"]

        doc = service.lead_post_to_document(lead_post)

        assert doc["remote_visibility"] == "visible"


class TestLeadPostUpsert:
    """Tests for lead_post upsert operations."""

    def test_upsert_lead_post_indexes_document(
        self, db_session, setup_lead_post_data
    ):
        """Upsert lead_post should index the document in ES."""
        from rediska_core.domain.services.indexing import IndexingService

        with patch("rediska_core.domain.services.indexing.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.index_document.return_value = True
            mock_es.return_value = mock_client

            service = IndexingService(
                db=db_session,
                es_url="http://localhost:9200",
            )
            lead_post = setup_lead_post_data["lead_post"]

            result = service.upsert_content("lead_post", lead_post.id)

            assert result is True
            mock_client.index_document.assert_called_once()

    def test_upsert_lead_post_uses_correct_doc_id(
        self, db_session, setup_lead_post_data
    ):
        """Upsert lead_post should use correct document ID format."""
        from rediska_core.domain.services.indexing import IndexingService

        with patch("rediska_core.domain.services.indexing.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.index_document.return_value = True
            mock_es.return_value = mock_client

            service = IndexingService(
                db=db_session,
                es_url="http://localhost:9200",
            )
            lead_post = setup_lead_post_data["lead_post"]

            service.upsert_content("lead_post", lead_post.id)

            call_args = mock_client.index_document.call_args
            assert call_args[1]["doc_id"] == f"lead_post:{lead_post.id}"


# =============================================================================
# PROFILE ITEM INDEXING TESTS (Epic 6.4)
# =============================================================================


@pytest.fixture
def setup_profile_item_data(db_session):
    """Set up profile item test data."""
    from rediska_core.domain.models import ProfileItem

    # Create provider
    provider = Provider(
        provider_id="reddit",
        display_name="Reddit",
        enabled=True,
    )
    db_session.add(provider)
    db_session.flush()

    # Create account
    account = ExternalAccount(
        provider_id="reddit",
        external_username="profile_user",
        external_user_id="t2_profile",
        remote_status="active",
    )
    db_session.add(account)
    db_session.flush()

    # Create profile item (post)
    profile_item = ProfileItem(
        account_id=account.id,
        item_type="post",
        external_item_id="post_xyz",
        text_content="This is my public post about coding.",
        remote_visibility="visible",
    )
    db_session.add(profile_item)
    db_session.flush()

    return {
        "provider": provider,
        "account": account,
        "profile_item": profile_item,
    }


class TestProfileItemDocumentConversion:
    """Tests for converting ProfileItem entities to ES documents."""

    def test_profile_item_to_document_includes_required_fields(
        self, db_session, setup_profile_item_data
    ):
        """ProfileItem document should include all required fields."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        profile_item = setup_profile_item_data["profile_item"]

        doc = service.profile_item_to_document(profile_item)

        assert doc["doc_type"] == "profile_item"
        assert doc["entity_id"] == profile_item.id
        assert doc["account_id"] == setup_profile_item_data["account"].id

    def test_profile_item_to_document_includes_item_type(
        self, db_session, setup_profile_item_data
    ):
        """ProfileItem document should include item_type."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        profile_item = setup_profile_item_data["profile_item"]

        doc = service.profile_item_to_document(profile_item)

        assert doc["item_type"] == "post"

    def test_profile_item_to_document_includes_content(
        self, db_session, setup_profile_item_data
    ):
        """ProfileItem document should include text_content as content."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        profile_item = setup_profile_item_data["profile_item"]

        doc = service.profile_item_to_document(profile_item)

        assert "public post about coding" in doc["content"]

    def test_profile_item_to_document_includes_visibility(
        self, db_session, setup_profile_item_data
    ):
        """ProfileItem document should include visibility for filtering."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        profile_item = setup_profile_item_data["profile_item"]

        doc = service.profile_item_to_document(profile_item)

        assert doc["remote_visibility"] == "visible"

    def test_profile_item_to_document_derives_provider_id(
        self, db_session, setup_profile_item_data
    ):
        """ProfileItem document should derive provider_id from account."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        profile_item = setup_profile_item_data["profile_item"]

        doc = service.profile_item_to_document(profile_item)

        assert doc["provider_id"] == "reddit"


class TestProfileItemUpsert:
    """Tests for profile_item upsert operations."""

    def test_upsert_profile_item_indexes_document(
        self, db_session, setup_profile_item_data
    ):
        """Upsert profile_item should index the document in ES."""
        from rediska_core.domain.services.indexing import IndexingService

        with patch("rediska_core.domain.services.indexing.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.index_document.return_value = True
            mock_es.return_value = mock_client

            service = IndexingService(
                db=db_session,
                es_url="http://localhost:9200",
            )
            profile_item = setup_profile_item_data["profile_item"]

            result = service.upsert_content("profile_item", profile_item.id)

            assert result is True
            mock_client.index_document.assert_called_once()

    def test_upsert_profile_item_uses_correct_doc_id(
        self, db_session, setup_profile_item_data
    ):
        """Upsert profile_item should use correct document ID format."""
        from rediska_core.domain.services.indexing import IndexingService

        with patch("rediska_core.domain.services.indexing.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.index_document.return_value = True
            mock_es.return_value = mock_client

            service = IndexingService(
                db=db_session,
                es_url="http://localhost:9200",
            )
            profile_item = setup_profile_item_data["profile_item"]

            service.upsert_content("profile_item", profile_item.id)

            call_args = mock_client.index_document.call_args
            assert call_args[1]["doc_id"] == f"profile_item:{profile_item.id}"


# =============================================================================
# PROFILE SNAPSHOT INDEXING TESTS (Epic 6.4)
# =============================================================================


@pytest.fixture
def setup_profile_snapshot_data(db_session):
    """Set up profile snapshot test data."""
    from rediska_core.domain.models import ProfileSnapshot

    # Create provider
    provider = Provider(
        provider_id="reddit",
        display_name="Reddit",
        enabled=True,
    )
    db_session.add(provider)
    db_session.flush()

    # Create account
    account = ExternalAccount(
        provider_id="reddit",
        external_username="snapshot_user",
        external_user_id="t2_snapshot",
        remote_status="active",
    )
    db_session.add(account)
    db_session.flush()

    # Create profile snapshot
    profile_snapshot = ProfileSnapshot(
        account_id=account.id,
        fetched_at=datetime.now(timezone.utc),
        summary_text="This user is interested in Python and machine learning. They have 5 years of experience.",
        signals_json={"interests": ["python", "ml"], "experience_years": 5},
        risk_flags_json={"spam_score": 0.1},
        model_info_json={"model": "llama-3", "version": "8b"},
    )
    db_session.add(profile_snapshot)
    db_session.flush()

    return {
        "provider": provider,
        "account": account,
        "profile_snapshot": profile_snapshot,
    }


class TestProfileSnapshotDocumentConversion:
    """Tests for converting ProfileSnapshot entities to ES documents."""

    def test_profile_snapshot_to_document_includes_required_fields(
        self, db_session, setup_profile_snapshot_data
    ):
        """ProfileSnapshot document should include all required fields."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        snapshot = setup_profile_snapshot_data["profile_snapshot"]

        doc = service.profile_snapshot_to_document(snapshot)

        assert doc["doc_type"] == "profile_snapshot"
        assert doc["entity_id"] == snapshot.id
        assert doc["account_id"] == setup_profile_snapshot_data["account"].id

    def test_profile_snapshot_to_document_includes_summary(
        self, db_session, setup_profile_snapshot_data
    ):
        """ProfileSnapshot document should include summary_text as content."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        snapshot = setup_profile_snapshot_data["profile_snapshot"]

        doc = service.profile_snapshot_to_document(snapshot)

        assert "Python and machine learning" in doc["content"]

    def test_profile_snapshot_to_document_derives_provider_id(
        self, db_session, setup_profile_snapshot_data
    ):
        """ProfileSnapshot document should derive provider_id from account."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        snapshot = setup_profile_snapshot_data["profile_snapshot"]

        doc = service.profile_snapshot_to_document(snapshot)

        assert doc["provider_id"] == "reddit"

    def test_profile_snapshot_to_document_includes_metadata(
        self, db_session, setup_profile_snapshot_data
    ):
        """ProfileSnapshot document should include signals and flags as metadata."""
        from rediska_core.domain.services.indexing import IndexingService

        service = IndexingService(db=db_session)
        snapshot = setup_profile_snapshot_data["profile_snapshot"]

        doc = service.profile_snapshot_to_document(snapshot)

        assert "metadata" in doc
        assert doc["metadata"]["signals_json"] == {"interests": ["python", "ml"], "experience_years": 5}


class TestProfileSnapshotUpsert:
    """Tests for profile_snapshot upsert operations."""

    def test_upsert_profile_snapshot_indexes_document(
        self, db_session, setup_profile_snapshot_data
    ):
        """Upsert profile_snapshot should index the document in ES."""
        from rediska_core.domain.services.indexing import IndexingService

        with patch("rediska_core.domain.services.indexing.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.index_document.return_value = True
            mock_es.return_value = mock_client

            service = IndexingService(
                db=db_session,
                es_url="http://localhost:9200",
            )
            snapshot = setup_profile_snapshot_data["profile_snapshot"]

            result = service.upsert_content("profile_snapshot", snapshot.id)

            assert result is True
            mock_client.index_document.assert_called_once()

    def test_upsert_profile_snapshot_uses_correct_doc_id(
        self, db_session, setup_profile_snapshot_data
    ):
        """Upsert profile_snapshot should use correct document ID format."""
        from rediska_core.domain.services.indexing import IndexingService

        with patch("rediska_core.domain.services.indexing.ElasticsearchClient") as mock_es:
            mock_client = MagicMock()
            mock_client.index_document.return_value = True
            mock_es.return_value = mock_client

            service = IndexingService(
                db=db_session,
                es_url="http://localhost:9200",
            )
            snapshot = setup_profile_snapshot_data["profile_snapshot"]

            service.upsert_content("profile_snapshot", snapshot.id)

            call_args = mock_client.index_document.call_args
            assert call_args[1]["doc_id"] == f"profile_snapshot:{snapshot.id}"
