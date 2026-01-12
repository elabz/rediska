"""Unit tests for incremental sync service.

Tests the incremental sync functionality:
1. sync_delta fetches only new/updated content since a timestamp
2. Updates visibility status for deleted/removed content
3. Tracks last sync timestamp for scheduling
4. Configurable sync intervals
"""

from datetime import datetime, timedelta, timezone
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
    SyncDeltaResult,
    SyncState,
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


@pytest.fixture
def setup_existing_data(db_session, setup_provider):
    """Create existing conversations and messages for sync tests."""
    # Create external account
    account = ExternalAccount(
        provider_id="reddit",
        external_username="existing_user",
        external_user_id="t2_existing",
        remote_status="active",
    )
    db_session.add(account)
    db_session.flush()

    # Create conversation
    conversation = Conversation(
        provider_id="reddit",
        external_conversation_id="conv_existing",
        counterpart_account_id=account.id,
        identity_id=setup_provider["identity"].id,
        last_activity_at=datetime(2025, 1, 1, 12, 0, 0),
    )
    db_session.add(conversation)
    db_session.flush()

    # Create existing message
    message = Message(
        provider_id="reddit",
        external_message_id="msg_existing",
        conversation_id=conversation.id,
        direction="in",
        sent_at=datetime(2025, 1, 1, 12, 0, 0),
        body_text="Existing message content",
        remote_visibility="visible",
    )
    db_session.add(message)
    db_session.flush()

    return {
        "account": account,
        "conversation": conversation,
        "message": message,
    }


# =============================================================================
# SYNC DELTA TESTS
# =============================================================================


class TestSyncDelta:
    """Tests for sync_delta method."""

    @pytest.mark.asyncio
    async def test_sync_delta_returns_result(
        self, db_session, ingest_service, mock_adapter, setup_existing_data
    ):
        """sync_delta should return SyncDeltaResult."""
        since = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[], next_cursor=None, has_more=False
        )

        result = await ingest_service.sync_delta(since_ts=since)

        assert isinstance(result, SyncDeltaResult)
        assert result.conversations_checked >= 0
        assert result.messages_created >= 0
        assert result.messages_updated >= 0

    @pytest.mark.asyncio
    async def test_sync_delta_fetches_new_messages(
        self, db_session, ingest_service, mock_adapter, setup_existing_data
    ):
        """sync_delta should fetch and create new messages."""
        since = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        new_msg_time = datetime(2025, 1, 2, 10, 0, 0, tzinfo=timezone.utc)

        # Return existing conversation
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_existing",
                    counterpart_id="t2_existing",
                    counterpart_username="existing_user",
                    last_message_at=new_msg_time,
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        # Return new message
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_new",
                    conversation_id="conv_existing",
                    direction=MessageDirection.IN,
                    body_text="New message after sync",
                    sent_at=new_msg_time,
                    remote_visibility=RemoteVisibility.VISIBLE,
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        result = await ingest_service.sync_delta(since_ts=since)

        assert result.messages_created == 1

        # Verify new message exists
        new_msg = db_session.query(Message).filter_by(
            external_message_id="msg_new"
        ).first()
        assert new_msg is not None
        assert new_msg.body_text == "New message after sync"

    @pytest.mark.asyncio
    async def test_sync_delta_updates_deleted_messages(
        self, db_session, ingest_service, mock_adapter, setup_existing_data
    ):
        """sync_delta should update visibility when messages are deleted."""
        since = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        # Return existing conversation
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

        # Return deleted message
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_existing",
                    conversation_id="conv_existing",
                    direction=MessageDirection.IN,
                    body_text="[deleted]",
                    sent_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                    sender_username="[deleted]",
                    remote_visibility=RemoteVisibility.DELETED_BY_AUTHOR,
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        result = await ingest_service.sync_delta(since_ts=since)

        assert result.messages_updated >= 1

        # Verify message content preserved, visibility updated
        msg = db_session.query(Message).filter_by(
            external_message_id="msg_existing"
        ).first()
        assert msg.body_text == "Existing message content"  # Preserved
        assert msg.remote_visibility == "deleted_by_author"

    @pytest.mark.asyncio
    async def test_sync_delta_creates_new_conversations(
        self, db_session, ingest_service, mock_adapter, setup_provider
    ):
        """sync_delta should create new conversations discovered during sync."""
        since = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        new_time = datetime(2025, 1, 2, 10, 0, 0, tzinfo=timezone.utc)

        # Return new conversation
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_new",
                    counterpart_id="t2_newuser",
                    counterpart_username="newuser",
                    last_message_at=new_time,
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        # Return messages for new conversation
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_in_new_conv",
                    conversation_id="conv_new",
                    direction=MessageDirection.IN,
                    body_text="Hello from new conv",
                    sent_at=new_time,
                    remote_visibility=RemoteVisibility.VISIBLE,
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        result = await ingest_service.sync_delta(since_ts=since)

        assert result.conversations_created == 1

        # Verify new conversation exists
        conv = db_session.query(Conversation).filter_by(
            external_conversation_id="conv_new"
        ).first()
        assert conv is not None

    @pytest.mark.asyncio
    async def test_sync_delta_skips_unchanged_conversations(
        self, db_session, ingest_service, mock_adapter, setup_existing_data
    ):
        """sync_delta should skip conversations with no new activity."""
        # Since after the last message
        since = datetime(2025, 1, 2, 0, 0, 0, tzinfo=timezone.utc)

        # Return conversation with old activity
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_existing",
                    counterpart_id="t2_existing",
                    counterpart_username="existing_user",
                    last_message_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        result = await ingest_service.sync_delta(since_ts=since)

        # Should not fetch messages for unchanged conversation
        mock_adapter.list_messages.assert_not_called()
        assert result.conversations_skipped == 1

    @pytest.mark.asyncio
    async def test_sync_delta_records_sync_time(
        self, db_session, ingest_service, mock_adapter, setup_existing_data
    ):
        """sync_delta should record when sync completed."""
        since = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        before_sync = datetime.now(timezone.utc)

        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[], next_cursor=None, has_more=False
        )

        result = await ingest_service.sync_delta(since_ts=since)

        after_sync = datetime.now(timezone.utc)
        assert result.completed_at is not None
        assert before_sync <= result.completed_at <= after_sync


# =============================================================================
# SYNC STATE MANAGEMENT TESTS
# =============================================================================


class TestSyncStateManagement:
    """Tests for sync state tracking."""

    @pytest.mark.asyncio
    async def test_get_last_sync_returns_none_initially(
        self, db_session, ingest_service
    ):
        """get_last_sync should return None if never synced."""
        state = ingest_service.get_sync_state()

        assert state is None or state.last_sync_at is None

    @pytest.mark.asyncio
    async def test_sync_delta_updates_sync_state(
        self, db_session, ingest_service, mock_adapter, setup_provider
    ):
        """sync_delta should update the sync state."""
        since = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[], next_cursor=None, has_more=False
        )

        await ingest_service.sync_delta(since_ts=since)

        state = ingest_service.get_sync_state()
        assert state is not None
        assert state.last_sync_at is not None

    @pytest.mark.asyncio
    async def test_sync_state_persists_across_instances(
        self, db_session, mock_adapter, setup_provider
    ):
        """Sync state should persist across service instances."""
        since = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[], next_cursor=None, has_more=False
        )

        # First instance syncs
        service1 = IngestService(
            db=db_session,
            adapter=mock_adapter,
            identity_id=setup_provider["identity"].id,
        )
        await service1.sync_delta(since_ts=since)
        db_session.flush()

        # Second instance should see the state
        service2 = IngestService(
            db=db_session,
            adapter=mock_adapter,
            identity_id=setup_provider["identity"].id,
        )
        state = service2.get_sync_state()

        assert state is not None
        assert state.last_sync_at is not None


# =============================================================================
# SYNC SCHEDULING TESTS
# =============================================================================


class TestSyncScheduling:
    """Tests for sync scheduling configuration."""

    def test_default_sync_interval(self, db_session, mock_adapter, setup_provider):
        """IngestService should have a default sync interval."""
        service = IngestService(
            db=db_session,
            adapter=mock_adapter,
            identity_id=setup_provider["identity"].id,
        )

        # Default should be between 5-15 minutes
        assert service.sync_interval_minutes >= 5
        assert service.sync_interval_minutes <= 15

    def test_configurable_sync_interval(self, db_session, mock_adapter, setup_provider):
        """Sync interval should be configurable."""
        service = IngestService(
            db=db_session,
            adapter=mock_adapter,
            identity_id=setup_provider["identity"].id,
            sync_interval_minutes=10,
        )

        assert service.sync_interval_minutes == 10

    @pytest.mark.asyncio
    async def test_should_sync_returns_true_when_due(
        self, db_session, ingest_service, mock_adapter, setup_provider
    ):
        """should_sync should return True when sync is due."""
        from rediska_core.domain.models import Job

        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[], next_cursor=None, has_more=False
        )

        # First sync
        await ingest_service.sync_delta(
            since_ts=datetime(2025, 1, 1, tzinfo=timezone.utc)
        )

        # Manually set the Job's updated_at to an old time (older than interval)
        job = db_session.query(Job).filter(
            Job.job_type == IngestService.JOB_TYPE_SYNC_DELTA,
            Job.status == "done",
        ).first()
        assert job is not None
        job.updated_at = datetime.now(timezone.utc) - timedelta(minutes=20)
        db_session.flush()

        assert ingest_service.should_sync() is True

    @pytest.mark.asyncio
    async def test_should_sync_returns_false_when_recent(
        self, db_session, ingest_service, mock_adapter
    ):
        """should_sync should return False when recently synced."""
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[], next_cursor=None, has_more=False
        )

        # Sync just now
        await ingest_service.sync_delta(
            since_ts=datetime(2025, 1, 1, tzinfo=timezone.utc)
        )

        # Should not need to sync again immediately
        assert ingest_service.should_sync() is False

    def test_should_sync_returns_true_when_never_synced(
        self, db_session, ingest_service
    ):
        """should_sync should return True if never synced."""
        assert ingest_service.should_sync() is True


# =============================================================================
# SYNC JOB CREATION TESTS
# =============================================================================


class TestSyncJobCreation:
    """Tests for creating scheduled sync jobs."""

    def test_enqueue_sync_creates_job(self, db_session, ingest_service):
        """enqueue_sync should create a sync job."""
        from rediska_core.domain.models import Job

        job = ingest_service.enqueue_sync()
        db_session.flush()

        assert job is not None
        assert job.job_type == "ingest.sync_delta"
        assert job.status == "queued"

    def test_enqueue_sync_is_idempotent(self, db_session, ingest_service):
        """Enqueueing sync twice should not create duplicates."""
        from rediska_core.domain.models import Job

        job1 = ingest_service.enqueue_sync()
        job2 = ingest_service.enqueue_sync()
        db_session.flush()

        # Should return same job
        assert job1.id == job2.id

        # Only one job should exist
        jobs = db_session.query(Job).filter_by(
            job_type="ingest.sync_delta"
        ).all()
        assert len(jobs) == 1

    def test_enqueue_sync_with_scheduled_time(self, db_session, ingest_service):
        """enqueue_sync should support scheduled execution time."""
        from rediska_core.domain.models import Job

        run_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        job = ingest_service.enqueue_sync(run_at=run_at)
        db_session.flush()

        assert job.next_run_at is not None
        # Compare without microseconds
        assert job.next_run_at.replace(microsecond=0, tzinfo=None) == run_at.replace(microsecond=0, tzinfo=None)


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


class TestSyncErrorHandling:
    """Tests for error handling during sync."""

    @pytest.mark.asyncio
    async def test_sync_handles_api_error(
        self, db_session, ingest_service, mock_adapter
    ):
        """sync_delta should handle API errors gracefully."""
        mock_adapter.list_conversations.side_effect = Exception("API Error")

        with pytest.raises(Exception, match="API Error"):
            await ingest_service.sync_delta(
                since_ts=datetime(2025, 1, 1, tzinfo=timezone.utc)
            )

    @pytest.mark.asyncio
    async def test_sync_continues_on_conversation_error(
        self, db_session, ingest_service, mock_adapter, setup_provider
    ):
        """sync_delta should continue if one conversation fails."""
        since = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        new_time = datetime(2025, 1, 2, 10, 0, 0, tzinfo=timezone.utc)

        # Return two conversations
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_fail",
                    counterpart_id="t2_user1",
                    counterpart_username="user1",
                    last_message_at=new_time,
                ),
                ProviderConversation(
                    external_id="conv_success",
                    counterpart_id="t2_user2",
                    counterpart_username="user2",
                    last_message_at=new_time,
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        # First conversation fails, second succeeds
        mock_adapter.list_messages.side_effect = [
            Exception("Conversation error"),
            PaginatedResult(
                items=[
                    ProviderMessage(
                        external_id="msg_success",
                        conversation_id="conv_success",
                        direction=MessageDirection.IN,
                        body_text="Success message",
                        sent_at=new_time,
                        remote_visibility=RemoteVisibility.VISIBLE,
                    ),
                ],
                next_cursor=None,
                has_more=False,
            ),
        ]

        result = await ingest_service.sync_delta(since_ts=since)

        # Should have processed second conversation despite first failing
        assert result.errors == 1
        assert result.messages_created == 1
