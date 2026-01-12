"""Unit tests for ingestion backfill service.

Tests the backfill orchestration for conversations and messages:
1. Conversation backfill creates DB records without duplicates
2. Message backfill ingests full history with cursor-driven pagination
3. Fan-out strategy enqueues per-conversation message backfill tasks
4. Idempotency - re-running does not duplicate work
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rediska_core.domain.models import (
    Conversation,
    ExternalAccount,
    Identity,
    Message,
    Provider,
)
from rediska_core.domain.services.ingest import (
    IngestService,
    BackfillResult,
    BackfillConversationsResult,
    BackfillMessagesResult,
)
from rediska_core.providers.base import (
    PaginatedResult,
    ProviderConversation,
    ProviderMessage,
    MessageDirection,
    RemoteVisibility,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def setup_provider(db_session):
    """Create required provider and identity."""
    provider = Provider(provider_id="reddit", display_name="Reddit")
    db_session.add(provider)

    identity = Identity(
        provider_id="reddit",
        external_username="my_reddit_user",
        external_user_id="t2_myself",
        display_name="My Reddit Account",
        is_default=True,
    )
    db_session.add(identity)
    db_session.flush()

    return {"provider": provider, "identity": identity}


@pytest.fixture
def mock_adapter():
    """Create a mock provider adapter."""
    adapter = AsyncMock()
    adapter.provider_id = "reddit"
    return adapter


@pytest.fixture
def ingest_service(db_session, mock_adapter, setup_provider):
    """Create an ingest service for testing."""
    return IngestService(
        db=db_session,
        adapter=mock_adapter,
        identity_id=setup_provider["identity"].id,
    )


# =============================================================================
# BACKFILL CONVERSATIONS TESTS
# =============================================================================


class TestBackfillConversations:
    """Tests for backfill_conversations method."""

    @pytest.mark.asyncio
    async def test_backfill_creates_conversations(
        self, db_session, ingest_service, mock_adapter
    ):
        """backfill_conversations should create conversation records."""
        # Mock provider returning conversations
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_1",
                    counterpart_id="t2_user1",
                    counterpart_username="user1",
                    subject="Hello",
                    last_message_at=datetime.now(timezone.utc),
                    is_unread=False,
                ),
                ProviderConversation(
                    external_id="conv_2",
                    counterpart_id="t2_user2",
                    counterpart_username="user2",
                    subject="Question",
                    last_message_at=datetime.now(timezone.utc),
                    is_unread=True,
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        result = await ingest_service.backfill_conversations()

        assert isinstance(result, BackfillConversationsResult)
        assert result.conversations_created == 2
        assert result.conversations_updated == 0

        # Verify conversations exist in DB
        convs = db_session.query(Conversation).filter_by(provider_id="reddit").all()
        assert len(convs) == 2

    @pytest.mark.asyncio
    async def test_backfill_creates_external_accounts(
        self, db_session, ingest_service, mock_adapter
    ):
        """backfill_conversations should create ExternalAccount for counterparts."""
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_1",
                    counterpart_id="t2_newuser",
                    counterpart_username="newuser",
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        await ingest_service.backfill_conversations()

        # Verify external account was created
        account = db_session.query(ExternalAccount).filter_by(
            provider_id="reddit", external_username="newuser"
        ).first()
        assert account is not None
        assert account.external_user_id == "t2_newuser"

    @pytest.mark.asyncio
    async def test_backfill_handles_pagination(
        self, db_session, ingest_service, mock_adapter
    ):
        """backfill_conversations should handle paginated results."""
        # First page
        page1 = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_1",
                    counterpart_id="t2_user1",
                    counterpart_username="user1",
                ),
            ],
            next_cursor="cursor_page2",
            has_more=True,
        )
        # Second page
        page2 = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_2",
                    counterpart_id="t2_user2",
                    counterpart_username="user2",
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        mock_adapter.list_conversations.side_effect = [page1, page2]

        result = await ingest_service.backfill_conversations()

        assert result.conversations_created == 2
        assert mock_adapter.list_conversations.call_count == 2

    @pytest.mark.asyncio
    async def test_backfill_is_idempotent(
        self, db_session, ingest_service, mock_adapter, setup_provider
    ):
        """Running backfill twice should not create duplicates."""
        # Create existing conversation
        existing_account = ExternalAccount(
            provider_id="reddit",
            external_username="existing_user",
            external_user_id="t2_existing",
        )
        db_session.add(existing_account)
        db_session.flush()

        existing_conv = Conversation(
            provider_id="reddit",
            external_conversation_id="conv_existing",
            counterpart_account_id=existing_account.id,
            identity_id=setup_provider["identity"].id,
        )
        db_session.add(existing_conv)
        db_session.flush()

        # Mock returning the same conversation
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_existing",
                    counterpart_id="t2_existing",
                    counterpart_username="existing_user",
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        result = await ingest_service.backfill_conversations()

        # Should update, not create duplicate
        assert result.conversations_created == 0
        assert result.conversations_updated == 1

        # Only one conversation should exist
        convs = db_session.query(Conversation).filter_by(
            external_conversation_id="conv_existing"
        ).all()
        assert len(convs) == 1

    @pytest.mark.asyncio
    async def test_backfill_updates_last_activity(
        self, db_session, ingest_service, mock_adapter, setup_provider
    ):
        """backfill_conversations should update last_activity_at."""
        new_activity_time = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_1",
                    counterpart_id="t2_user1",
                    counterpart_username="user1",
                    last_message_at=new_activity_time,
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        await ingest_service.backfill_conversations()

        conv = db_session.query(Conversation).filter_by(
            external_conversation_id="conv_1"
        ).first()
        # Compare without timezone (DB stores naive datetimes)
        assert conv.last_activity_at.replace(tzinfo=None) == new_activity_time.replace(tzinfo=None)


# =============================================================================
# BACKFILL MESSAGES TESTS
# =============================================================================


class TestBackfillMessages:
    """Tests for backfill_messages method."""

    @pytest.fixture
    def setup_conversation(self, db_session, setup_provider):
        """Create a conversation for message tests."""
        account = ExternalAccount(
            provider_id="reddit",
            external_username="msg_user",
            external_user_id="t2_msguser",
        )
        db_session.add(account)
        db_session.flush()

        conversation = Conversation(
            provider_id="reddit",
            external_conversation_id="conv_for_msgs",
            counterpart_account_id=account.id,
            identity_id=setup_provider["identity"].id,
        )
        db_session.add(conversation)
        db_session.flush()

        return conversation

    @pytest.mark.asyncio
    async def test_backfill_creates_messages(
        self, db_session, ingest_service, mock_adapter, setup_conversation
    ):
        """backfill_messages should create message records."""
        sent_time = datetime.now(timezone.utc)

        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_1",
                    conversation_id="conv_for_msgs",
                    direction=MessageDirection.IN,
                    body_text="Hello there!",
                    sent_at=sent_time,
                    sender_username="msg_user",
                    remote_visibility=RemoteVisibility.VISIBLE,
                ),
                ProviderMessage(
                    external_id="msg_2",
                    conversation_id="conv_for_msgs",
                    direction=MessageDirection.OUT,
                    body_text="Hi back!",
                    sent_at=sent_time,
                    sender_username="my_reddit_user",
                    remote_visibility=RemoteVisibility.VISIBLE,
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        result = await ingest_service.backfill_messages("conv_for_msgs")

        assert isinstance(result, BackfillMessagesResult)
        assert result.messages_created == 2
        assert result.messages_updated == 0

        # Verify messages exist in DB
        msgs = db_session.query(Message).filter_by(
            conversation_id=setup_conversation.id
        ).all()
        assert len(msgs) == 2

    @pytest.mark.asyncio
    async def test_backfill_messages_pagination(
        self, db_session, ingest_service, mock_adapter, setup_conversation
    ):
        """backfill_messages should handle paginated results."""
        sent_time = datetime.now(timezone.utc)

        page1 = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_1",
                    conversation_id="conv_for_msgs",
                    direction=MessageDirection.IN,
                    body_text="Message 1",
                    sent_at=sent_time,
                    remote_visibility=RemoteVisibility.VISIBLE,
                ),
            ],
            next_cursor="cursor_page2",
            has_more=True,
        )
        page2 = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_2",
                    conversation_id="conv_for_msgs",
                    direction=MessageDirection.IN,
                    body_text="Message 2",
                    sent_at=sent_time,
                    remote_visibility=RemoteVisibility.VISIBLE,
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        mock_adapter.list_messages.side_effect = [page1, page2]

        result = await ingest_service.backfill_messages("conv_for_msgs")

        assert result.messages_created == 2
        assert mock_adapter.list_messages.call_count == 2

    @pytest.mark.asyncio
    async def test_backfill_messages_is_idempotent(
        self, db_session, ingest_service, mock_adapter, setup_conversation, setup_provider
    ):
        """Running backfill twice should not create duplicate messages."""
        sent_time = datetime.now(timezone.utc)

        # Create existing message
        existing_msg = Message(
            provider_id="reddit",
            external_message_id="msg_existing",
            conversation_id=setup_conversation.id,
            direction="in",
            body_text="Existing message",
            sent_at=sent_time,
            remote_visibility="visible",
        )
        db_session.add(existing_msg)
        db_session.flush()

        # Mock returning the same message
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_existing",
                    conversation_id="conv_for_msgs",
                    direction=MessageDirection.IN,
                    body_text="Existing message",
                    sent_at=sent_time,
                    remote_visibility=RemoteVisibility.VISIBLE,
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        result = await ingest_service.backfill_messages("conv_for_msgs")

        assert result.messages_created == 0
        assert result.messages_updated == 1

        # Only one message should exist
        msgs = db_session.query(Message).filter_by(
            external_message_id="msg_existing"
        ).all()
        assert len(msgs) == 1

    @pytest.mark.asyncio
    async def test_backfill_messages_preserves_content_on_deletion(
        self, db_session, ingest_service, mock_adapter, setup_conversation
    ):
        """backfill_messages should preserve content when remote is deleted."""
        sent_time = datetime.now(timezone.utc)

        # Create existing message with content
        existing_msg = Message(
            provider_id="reddit",
            external_message_id="msg_deleted",
            conversation_id=setup_conversation.id,
            direction="in",
            body_text="Original content before deletion",
            sent_at=sent_time,
            remote_visibility="visible",
        )
        db_session.add(existing_msg)
        db_session.flush()

        # Mock returning deleted version
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_deleted",
                    conversation_id="conv_for_msgs",
                    direction=MessageDirection.IN,
                    body_text="[deleted]",
                    sent_at=sent_time,
                    sender_username="[deleted]",
                    remote_visibility=RemoteVisibility.DELETED_BY_AUTHOR,
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        await ingest_service.backfill_messages("conv_for_msgs")

        # Original content should be preserved
        msg = db_session.query(Message).filter_by(
            external_message_id="msg_deleted"
        ).first()
        assert msg.body_text == "Original content before deletion"
        assert msg.remote_visibility == "deleted_by_author"

    @pytest.mark.asyncio
    async def test_backfill_messages_with_cursor(
        self, db_session, ingest_service, mock_adapter, setup_conversation
    ):
        """backfill_messages should support starting from a cursor."""
        sent_time = datetime.now(timezone.utc)

        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_after_cursor",
                    conversation_id="conv_for_msgs",
                    direction=MessageDirection.IN,
                    body_text="After cursor",
                    sent_at=sent_time,
                    remote_visibility=RemoteVisibility.VISIBLE,
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        result = await ingest_service.backfill_messages(
            "conv_for_msgs",
            cursor="some_cursor"
        )

        # Verify cursor was passed to adapter
        mock_adapter.list_messages.assert_called_once()
        call_args = mock_adapter.list_messages.call_args
        assert call_args[1].get("cursor") == "some_cursor" or call_args[0][1] == "some_cursor"

    @pytest.mark.asyncio
    async def test_backfill_messages_updates_conversation_activity(
        self, db_session, ingest_service, mock_adapter, setup_conversation
    ):
        """backfill_messages should update conversation last_activity_at."""
        latest_time = datetime(2025, 12, 25, 12, 0, 0, tzinfo=timezone.utc)

        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_latest",
                    conversation_id="conv_for_msgs",
                    direction=MessageDirection.IN,
                    body_text="Latest message",
                    sent_at=latest_time,
                    remote_visibility=RemoteVisibility.VISIBLE,
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        await ingest_service.backfill_messages("conv_for_msgs")

        # Conversation should have updated last_activity_at
        db_session.refresh(setup_conversation)
        # Compare without timezone (DB stores naive datetimes)
        assert setup_conversation.last_activity_at.replace(tzinfo=None) == latest_time.replace(tzinfo=None)


# =============================================================================
# FAN-OUT ORCHESTRATION TESTS
# =============================================================================


class TestFanOutOrchestration:
    """Tests for fan-out orchestration (enqueue message backfill per conversation)."""

    @pytest.mark.asyncio
    async def test_backfill_all_enqueues_message_jobs(
        self, db_session, ingest_service, mock_adapter, setup_provider
    ):
        """backfill_all should enqueue message backfill jobs for each conversation."""
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_1",
                    counterpart_id="t2_user1",
                    counterpart_username="user1",
                ),
                ProviderConversation(
                    external_id="conv_2",
                    counterpart_id="t2_user2",
                    counterpart_username="user2",
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        with patch.object(ingest_service, 'enqueue_message_backfill') as mock_enqueue:
            result = await ingest_service.backfill_all()

            # Should enqueue a job for each conversation
            assert mock_enqueue.call_count == 2
            mock_enqueue.assert_any_call("conv_1")
            mock_enqueue.assert_any_call("conv_2")

    @pytest.mark.asyncio
    async def test_backfill_all_returns_summary(
        self, db_session, ingest_service, mock_adapter
    ):
        """backfill_all should return a summary of work done."""
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_1",
                    counterpart_id="t2_user1",
                    counterpart_username="user1",
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        with patch.object(ingest_service, 'enqueue_message_backfill'):
            result = await ingest_service.backfill_all()

            assert isinstance(result, BackfillResult)
            assert result.conversations_processed == 1
            assert result.message_jobs_enqueued == 1

    @pytest.mark.asyncio
    async def test_enqueue_message_backfill_creates_job(
        self, db_session, ingest_service, mock_adapter, setup_provider
    ):
        """enqueue_message_backfill should create a job in the ledger."""
        from rediska_core.domain.models import Job

        # First create a conversation
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_to_backfill",
                    counterpart_id="t2_user1",
                    counterpart_username="user1",
                ),
            ],
            next_cursor=None,
            has_more=False,
        )
        await ingest_service.backfill_conversations()

        # Now enqueue message backfill
        ingest_service.enqueue_message_backfill("conv_to_backfill")
        db_session.flush()

        # Verify job was created
        job = db_session.query(Job).filter_by(
            job_type="ingest.backfill_messages"
        ).first()
        assert job is not None
        assert job.payload_json["conversation_id"] == "conv_to_backfill"
        assert job.status == "queued"

    @pytest.mark.asyncio
    async def test_enqueue_message_backfill_is_idempotent(
        self, db_session, ingest_service, mock_adapter, setup_provider
    ):
        """Enqueueing the same conversation twice should not create duplicates."""
        from rediska_core.domain.models import Job

        # Create conversation first
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_dedupe",
                    counterpart_id="t2_user1",
                    counterpart_username="user1",
                ),
            ],
            next_cursor=None,
            has_more=False,
        )
        await ingest_service.backfill_conversations()

        # Enqueue twice
        ingest_service.enqueue_message_backfill("conv_dedupe")
        ingest_service.enqueue_message_backfill("conv_dedupe")
        db_session.flush()

        # Should only have one job
        jobs = db_session.query(Job).filter(
            Job.job_type == "ingest.backfill_messages",
            Job.payload_json["conversation_id"].as_string() == "conv_dedupe",
        ).all()
        assert len(jobs) == 1


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


class TestErrorHandling:
    """Tests for error handling in backfill operations."""

    @pytest.mark.asyncio
    async def test_backfill_handles_api_error(
        self, db_session, ingest_service, mock_adapter
    ):
        """backfill_conversations should handle API errors gracefully."""
        mock_adapter.list_conversations.side_effect = Exception("API Error")

        with pytest.raises(Exception, match="API Error"):
            await ingest_service.backfill_conversations()

    @pytest.mark.asyncio
    async def test_backfill_messages_handles_missing_conversation(
        self, db_session, ingest_service, mock_adapter
    ):
        """backfill_messages should raise for unknown conversation."""
        with pytest.raises(ValueError, match="Conversation not found"):
            await ingest_service.backfill_messages("nonexistent_conv")

    @pytest.mark.asyncio
    async def test_backfill_continues_on_partial_failure(
        self, db_session, ingest_service, mock_adapter
    ):
        """backfill should continue processing after individual failures."""
        # First page succeeds
        page1 = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_success",
                    counterpart_id="t2_user1",
                    counterpart_username="user1",
                ),
            ],
            next_cursor="cursor_page2",
            has_more=True,
        )
        # Second page fails
        mock_adapter.list_conversations.side_effect = [
            page1,
            Exception("Partial failure"),
        ]

        # Should raise but first page should be processed
        with pytest.raises(Exception, match="Partial failure"):
            await ingest_service.backfill_conversations()

        # First conversation should still exist
        conv = db_session.query(Conversation).filter_by(
            external_conversation_id="conv_success"
        ).first()
        assert conv is not None
