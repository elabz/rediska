"""
Unit tests for Epic 4.3 - Ingest persistence rules.

Tests cover:
1. Conversation upsert rules (external_conversation_id uniqueness)
2. Message upsert rules (external_message_id uniqueness, content preservation)
3. last_activity_at derivation rules (monotonic increase)
4. Multiple sync runs don't create duplicates
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from rediska_core.domain.models import (
    Conversation,
    ExternalAccount,
    Identity,
    Message,
    Provider,
)
from rediska_core.domain.services.ingest import IngestService
from rediska_core.providers.base import (
    MessageDirection,
    PaginatedResult,
    ProviderConversation,
    ProviderMessage,
    RemoteVisibility,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_adapter():
    """Create a mock provider adapter."""
    adapter = MagicMock()
    adapter.provider_id = "reddit"
    adapter.list_conversations = AsyncMock()
    adapter.list_messages = AsyncMock()
    return adapter


@pytest.fixture
def setup_provider(db_session):
    """Create provider and identity in database."""
    provider = Provider(
        provider_id="reddit",
        display_name="Reddit",
        enabled=True,
    )
    db_session.add(provider)
    db_session.flush()

    # Create identity with id=1 (required by IngestService)
    identity = Identity(
        provider_id="reddit",
        external_username="test_identity",
        display_name="Test Identity",
        is_default=True,
        is_active=True,
    )
    db_session.add(identity)
    db_session.flush()

    return provider


@pytest.fixture
def ingest_service(db_session, mock_adapter, setup_provider):
    """Create IngestService with mocked adapter. Depends on setup_provider."""
    return IngestService(
        db=db_session,
        adapter=mock_adapter,
        identity_id=1,
    )


# =============================================================================
# CONVERSATION UPSERT RULES TESTS
# =============================================================================


class TestConversationUpsertRules:
    """Tests for conversation upsert rules.

    Rules:
    - provider_id + external_conversation_id must be unique
    - Re-syncing same conversation does not create duplicates
    - last_activity_at is updated when new activity arrives
    - Counterpart account is linked correctly
    """

    @pytest.mark.asyncio
    async def test_same_external_id_does_not_create_duplicate(
        self, db_session, ingest_service, mock_adapter, setup_provider
    ):
        """Syncing same conversation twice should not create duplicates."""
        conv_data = ProviderConversation(
            external_id="conv_123",
            counterpart_id="t2_user1",
            counterpart_username="testuser",
            last_message_at=datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
        )

        # First sync
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[conv_data], next_cursor=None, has_more=False
        )
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[], next_cursor=None, has_more=False
        )

        await ingest_service.backfill_conversations()
        db_session.flush()

        first_count = db_session.query(Conversation).filter_by(
            provider_id="reddit",
            external_conversation_id="conv_123",
        ).count()
        assert first_count == 1

        # Second sync with same data
        await ingest_service.backfill_conversations()
        db_session.flush()

        second_count = db_session.query(Conversation).filter_by(
            provider_id="reddit",
            external_conversation_id="conv_123",
        ).count()
        assert second_count == 1  # Still 1, no duplicate

    @pytest.mark.asyncio
    async def test_different_providers_can_have_same_external_id(
        self, db_session, mock_adapter, setup_provider
    ):
        """Different providers can use the same external_id."""
        # Create second provider
        provider2 = Provider(
            provider_id="twitter",
            display_name="Twitter",
            enabled=True,
        )
        db_session.add(provider2)
        db_session.flush()

        # Create conversation for reddit
        account1 = ExternalAccount(
            provider_id="reddit",
            external_username="user1",
            remote_status="unknown",
        )
        db_session.add(account1)
        db_session.flush()

        conv1 = Conversation(
            provider_id="reddit",
            external_conversation_id="conv_123",
            counterpart_account_id=account1.id,
            identity_id=1,
        )
        db_session.add(conv1)

        # Create conversation with same external_id for twitter
        account2 = ExternalAccount(
            provider_id="twitter",
            external_username="user2",
            remote_status="unknown",
        )
        db_session.add(account2)
        db_session.flush()

        conv2 = Conversation(
            provider_id="twitter",
            external_conversation_id="conv_123",  # Same external_id, different provider
            counterpart_account_id=account2.id,
            identity_id=1,
        )
        db_session.add(conv2)
        db_session.flush()

        # Both should exist
        count = db_session.query(Conversation).filter_by(
            external_conversation_id="conv_123"
        ).count()
        assert count == 2

    @pytest.mark.asyncio
    async def test_upsert_updates_last_activity_when_newer(
        self, db_session, ingest_service, mock_adapter, setup_provider
    ):
        """Upsert should update last_activity_at when provider has newer timestamp."""
        old_time = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        new_time = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)

        # First sync with old time
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_123",
                    counterpart_id="t2_user1",
                    counterpart_username="testuser",
                    last_message_at=old_time,
                )
            ],
            next_cursor=None,
            has_more=False,
        )
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[], next_cursor=None, has_more=False
        )

        await ingest_service.backfill_conversations()
        db_session.flush()

        conv = db_session.query(Conversation).filter_by(
            external_conversation_id="conv_123"
        ).first()
        assert conv.last_activity_at == old_time.replace(tzinfo=None)

        # Second sync with newer time
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_123",
                    counterpart_id="t2_user1",
                    counterpart_username="testuser",
                    last_message_at=new_time,
                )
            ],
            next_cursor=None,
            has_more=False,
        )

        await ingest_service.backfill_conversations()
        db_session.flush()
        db_session.refresh(conv)

        assert conv.last_activity_at == new_time.replace(tzinfo=None)

    @pytest.mark.asyncio
    async def test_upsert_does_not_decrease_last_activity(
        self, db_session, ingest_service, mock_adapter, setup_provider
    ):
        """last_activity_at should never decrease (monotonic)."""
        new_time = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)
        old_time = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

        # First sync with newer time
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_123",
                    counterpart_id="t2_user1",
                    counterpart_username="testuser",
                    last_message_at=new_time,
                )
            ],
            next_cursor=None,
            has_more=False,
        )
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[], next_cursor=None, has_more=False
        )

        await ingest_service.backfill_conversations()
        db_session.flush()

        conv = db_session.query(Conversation).filter_by(
            external_conversation_id="conv_123"
        ).first()
        assert conv.last_activity_at == new_time.replace(tzinfo=None)

        # Second sync with OLDER time (should not decrease)
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_123",
                    counterpart_id="t2_user1",
                    counterpart_username="testuser",
                    last_message_at=old_time,
                )
            ],
            next_cursor=None,
            has_more=False,
        )

        await ingest_service.backfill_conversations()
        db_session.flush()
        db_session.refresh(conv)

        # Should still be the newer time
        assert conv.last_activity_at == new_time.replace(tzinfo=None)

    @pytest.mark.asyncio
    async def test_upsert_handles_missing_last_message_at(
        self, db_session, ingest_service, mock_adapter, setup_provider
    ):
        """Upsert should handle conversations without last_message_at."""
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_123",
                    counterpart_id="t2_user1",
                    counterpart_username="testuser",
                    last_message_at=None,  # No timestamp
                )
            ],
            next_cursor=None,
            has_more=False,
        )
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[], next_cursor=None, has_more=False
        )

        await ingest_service.backfill_conversations()
        db_session.flush()

        conv = db_session.query(Conversation).filter_by(
            external_conversation_id="conv_123"
        ).first()
        assert conv is not None
        assert conv.last_activity_at is None

    @pytest.mark.asyncio
    async def test_counterpart_account_linked_correctly(
        self, db_session, ingest_service, mock_adapter, setup_provider
    ):
        """Conversation should be linked to correct counterpart account."""
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_123",
                    counterpart_id="t2_user123",
                    counterpart_username="specific_user",
                    last_message_at=datetime.now(timezone.utc),
                )
            ],
            next_cursor=None,
            has_more=False,
        )
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[], next_cursor=None, has_more=False
        )

        await ingest_service.backfill_conversations()
        db_session.flush()

        conv = db_session.query(Conversation).filter_by(
            external_conversation_id="conv_123"
        ).first()
        account = db_session.query(ExternalAccount).get(conv.counterpart_account_id)

        assert account is not None
        assert account.external_username == "specific_user"
        assert account.external_user_id == "t2_user123"


# =============================================================================
# MESSAGE UPSERT RULES TESTS
# =============================================================================


class TestMessageUpsertRules:
    """Tests for message upsert rules.

    Rules:
    - provider_id + external_message_id must be unique
    - Re-syncing same message does not create duplicates
    - Original content is preserved when message is deleted remotely
    - Visibility is updated but body_text is not modified
    """

    @pytest.fixture
    def setup_conversation(self, db_session, setup_provider):
        """Create a conversation for message tests."""
        account = ExternalAccount(
            provider_id="reddit",
            external_username="testuser",
            remote_status="unknown",
        )
        db_session.add(account)
        db_session.flush()

        conv = Conversation(
            provider_id="reddit",
            external_conversation_id="conv_123",
            counterpart_account_id=account.id,
            identity_id=1,
        )
        db_session.add(conv)
        db_session.flush()

        return conv

    @pytest.mark.asyncio
    async def test_same_external_message_id_does_not_create_duplicate(
        self, db_session, ingest_service, mock_adapter, setup_conversation
    ):
        """Syncing same message twice should not create duplicates."""
        msg_data = ProviderMessage(
            external_id="msg_123",
            conversation_id="conv_123",
            direction=MessageDirection.IN,
            body_text="Hello world",
            sent_at=datetime.now(timezone.utc),
            remote_visibility=RemoteVisibility.VISIBLE,
        )

        # First sync
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_123",
                    counterpart_id="t2_user1",
                    counterpart_username="testuser",
                    last_message_at=datetime.now(timezone.utc),
                )
            ],
            next_cursor=None,
            has_more=False,
        )
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[msg_data], next_cursor=None, has_more=False
        )

        result1 = await ingest_service.backfill_messages("conv_123")
        db_session.flush()

        first_count = db_session.query(Message).filter_by(
            provider_id="reddit",
            external_message_id="msg_123",
        ).count()
        assert first_count == 1
        assert result1.messages_created == 1

        # Second sync with same data
        result2 = await ingest_service.backfill_messages("conv_123")
        db_session.flush()

        second_count = db_session.query(Message).filter_by(
            provider_id="reddit",
            external_message_id="msg_123",
        ).count()
        assert second_count == 1  # Still 1, no duplicate
        assert result2.messages_created == 0  # No new messages
        assert result2.messages_updated == 1  # Updated existing

    @pytest.mark.asyncio
    async def test_different_providers_can_have_same_message_id(
        self, db_session, setup_conversation
    ):
        """Different providers can use the same external_message_id."""
        now = datetime.now()

        # Create second provider
        provider2 = Provider(
            provider_id="twitter",
            display_name="Twitter",
            enabled=True,
        )
        db_session.add(provider2)
        db_session.flush()

        # Create message for reddit
        msg1 = Message(
            provider_id="reddit",
            external_message_id="msg_123",
            conversation_id=setup_conversation.id,
            direction="in",
            body_text="Reddit message",
            remote_visibility="visible",
            sent_at=now,
        )
        db_session.add(msg1)

        # Create identity for twitter
        identity2 = Identity(
            provider_id="twitter",
            external_username="twitter_user",
            display_name="Twitter User",
            is_default=True,
            is_active=True,
        )
        db_session.add(identity2)
        db_session.flush()

        # Create second conversation for twitter
        account2 = ExternalAccount(
            provider_id="twitter",
            external_username="user2",
            remote_status="unknown",
        )
        db_session.add(account2)
        db_session.flush()

        conv2 = Conversation(
            provider_id="twitter",
            external_conversation_id="conv_456",
            counterpart_account_id=account2.id,
            identity_id=identity2.id,
        )
        db_session.add(conv2)
        db_session.flush()

        # Create message with same external_id for twitter
        msg2 = Message(
            provider_id="twitter",
            external_message_id="msg_123",  # Same external_id, different provider
            conversation_id=conv2.id,
            direction="in",
            body_text="Twitter message",
            remote_visibility="visible",
            sent_at=now,
        )
        db_session.add(msg2)
        db_session.flush()

        # Both should exist
        count = db_session.query(Message).filter_by(
            external_message_id="msg_123"
        ).count()
        assert count == 2

    @pytest.mark.asyncio
    async def test_content_preserved_when_deleted_remotely(
        self, db_session, ingest_service, mock_adapter, setup_conversation
    ):
        """Original body_text must be preserved when message is deleted remotely."""
        original_text = "Original message content that should be preserved"
        msg_time = datetime.now(timezone.utc)

        # First sync with visible message
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_123",
                    counterpart_id="t2_user1",
                    counterpart_username="testuser",
                    last_message_at=msg_time,
                )
            ],
            next_cursor=None,
            has_more=False,
        )
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_123",
                    conversation_id="conv_123",
                    direction=MessageDirection.IN,
                    body_text=original_text,
                    sent_at=msg_time,
                    remote_visibility=RemoteVisibility.VISIBLE,
                )
            ],
            next_cursor=None,
            has_more=False,
        )

        await ingest_service.backfill_messages("conv_123")
        db_session.flush()

        msg = db_session.query(Message).filter_by(external_message_id="msg_123").first()
        assert msg.body_text == original_text
        assert msg.remote_visibility == "visible"

        # Second sync with deleted message (body_text is "[deleted]" from provider)
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_123",
                    conversation_id="conv_123",
                    direction=MessageDirection.IN,
                    body_text="[deleted]",  # Provider returns deleted placeholder
                    sent_at=msg_time,
                    remote_visibility=RemoteVisibility.DELETED_BY_AUTHOR,
                )
            ],
            next_cursor=None,
            has_more=False,
        )

        await ingest_service.backfill_messages("conv_123")
        db_session.flush()
        db_session.refresh(msg)

        # Original content MUST be preserved
        assert msg.body_text == original_text  # NOT "[deleted]"
        assert msg.remote_visibility == "deleted_by_author"
        assert msg.remote_deleted_at is not None

    @pytest.mark.asyncio
    async def test_visibility_updated_on_sync(
        self, db_session, ingest_service, mock_adapter, setup_conversation
    ):
        """Visibility should be updated when provider reports deletion."""
        msg_time = datetime.now(timezone.utc)

        # First sync with visible
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_123",
                    counterpart_id="t2_user1",
                    counterpart_username="testuser",
                    last_message_at=msg_time,
                )
            ],
            next_cursor=None,
            has_more=False,
        )
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_123",
                    conversation_id="conv_123",
                    direction=MessageDirection.IN,
                    body_text="Test message",
                    sent_at=msg_time,
                    remote_visibility=RemoteVisibility.VISIBLE,
                )
            ],
            next_cursor=None,
            has_more=False,
        )

        await ingest_service.backfill_messages("conv_123")
        db_session.flush()

        msg = db_session.query(Message).filter_by(external_message_id="msg_123").first()
        assert msg.remote_visibility == "visible"

        # Second sync with removed (mod action)
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_123",
                    conversation_id="conv_123",
                    direction=MessageDirection.IN,
                    body_text="Test message",
                    sent_at=msg_time,
                    remote_visibility=RemoteVisibility.REMOVED,
                )
            ],
            next_cursor=None,
            has_more=False,
        )

        await ingest_service.backfill_messages("conv_123")
        db_session.flush()
        db_session.refresh(msg)

        assert msg.remote_visibility == "removed"

    @pytest.mark.asyncio
    async def test_visibility_does_not_downgrade_to_unknown(
        self, db_session, ingest_service, mock_adapter, setup_conversation
    ):
        """Known visibility should not be downgraded to unknown."""
        msg_time = datetime.now(timezone.utc)

        # First sync with known deletion state
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_123",
                    counterpart_id="t2_user1",
                    counterpart_username="testuser",
                    last_message_at=msg_time,
                )
            ],
            next_cursor=None,
            has_more=False,
        )
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_123",
                    conversation_id="conv_123",
                    direction=MessageDirection.IN,
                    body_text="Test message",
                    sent_at=msg_time,
                    remote_visibility=RemoteVisibility.DELETED_BY_AUTHOR,
                )
            ],
            next_cursor=None,
            has_more=False,
        )

        await ingest_service.backfill_messages("conv_123")
        db_session.flush()

        msg = db_session.query(Message).filter_by(external_message_id="msg_123").first()
        assert msg.remote_visibility == "deleted_by_author"

        # Second sync with unknown (should not downgrade)
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_123",
                    conversation_id="conv_123",
                    direction=MessageDirection.IN,
                    body_text="Test message",
                    sent_at=msg_time,
                    remote_visibility=RemoteVisibility.UNKNOWN,
                )
            ],
            next_cursor=None,
            has_more=False,
        )

        await ingest_service.backfill_messages("conv_123")
        db_session.flush()
        db_session.refresh(msg)

        # Should still be deleted_by_author, not unknown
        assert msg.remote_visibility == "deleted_by_author"

    @pytest.mark.asyncio
    async def test_message_handles_missing_sent_at(
        self, db_session, ingest_service, mock_adapter, setup_conversation
    ):
        """Messages without sent_at should use a default timestamp (DB requires NOT NULL)."""
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_123",
                    counterpart_id="t2_user1",
                    counterpart_username="testuser",
                    last_message_at=datetime.now(timezone.utc),
                )
            ],
            next_cursor=None,
            has_more=False,
        )
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_123",
                    conversation_id="conv_123",
                    direction=MessageDirection.IN,
                    body_text="Message without timestamp",
                    sent_at=None,  # No timestamp from provider
                    remote_visibility=RemoteVisibility.VISIBLE,
                )
            ],
            next_cursor=None,
            has_more=False,
        )

        await ingest_service.backfill_messages("conv_123")
        db_session.flush()

        msg = db_session.query(Message).filter_by(external_message_id="msg_123").first()
        assert msg is not None
        # Should have a default timestamp since DB requires NOT NULL
        assert msg.sent_at is not None
        assert msg.body_text == "Message without timestamp"


# =============================================================================
# LAST_ACTIVITY_AT DERIVATION TESTS
# =============================================================================


class TestLastActivityAtDerivation:
    """Tests for last_activity_at derivation rules.

    Rules:
    - last_activity_at is set from provider conversation data
    - last_activity_at is updated from message sync
    - last_activity_at only increases (monotonic)
    - Handles timezone normalization correctly
    """

    @pytest.fixture
    def setup_conversation(self, db_session, setup_provider):
        """Create a conversation for activity tests."""
        account = ExternalAccount(
            provider_id="reddit",
            external_username="testuser",
            remote_status="unknown",
        )
        db_session.add(account)
        db_session.flush()

        conv = Conversation(
            provider_id="reddit",
            external_conversation_id="conv_123",
            counterpart_account_id=account.id,
            identity_id=1,
            last_activity_at=datetime(2025, 1, 1, 12, 0),  # Naive datetime
        )
        db_session.add(conv)
        db_session.flush()

        return conv

    @pytest.mark.asyncio
    async def test_activity_updated_from_new_messages(
        self, db_session, ingest_service, mock_adapter, setup_conversation
    ):
        """last_activity_at should be updated when new messages arrive."""
        new_msg_time = datetime(2025, 1, 5, 12, 0, tzinfo=timezone.utc)

        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_new",
                    conversation_id="conv_123",
                    direction=MessageDirection.IN,
                    body_text="New message",
                    sent_at=new_msg_time,
                    remote_visibility=RemoteVisibility.VISIBLE,
                )
            ],
            next_cursor=None,
            has_more=False,
        )

        await ingest_service.backfill_messages("conv_123")
        db_session.flush()

        conv = db_session.query(Conversation).filter_by(
            external_conversation_id="conv_123"
        ).first()
        db_session.refresh(conv)

        # Should be updated to new message time
        assert conv.last_activity_at == new_msg_time.replace(tzinfo=None)

    @pytest.mark.asyncio
    async def test_activity_not_decreased_from_old_messages(
        self, db_session, ingest_service, mock_adapter, setup_conversation
    ):
        """last_activity_at should not decrease from older messages."""
        # Conversation already has activity at Jan 1 (from fixture)
        old_msg_time = datetime(2024, 12, 15, 12, 0, tzinfo=timezone.utc)

        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_old",
                    conversation_id="conv_123",
                    direction=MessageDirection.IN,
                    body_text="Old message",
                    sent_at=old_msg_time,
                    remote_visibility=RemoteVisibility.VISIBLE,
                )
            ],
            next_cursor=None,
            has_more=False,
        )

        await ingest_service.backfill_messages("conv_123")
        db_session.flush()

        conv = db_session.query(Conversation).filter_by(
            external_conversation_id="conv_123"
        ).first()
        db_session.refresh(conv)

        # Should still be Jan 1 (not decreased to Dec 15)
        assert conv.last_activity_at == datetime(2025, 1, 1, 12, 0)

    @pytest.mark.asyncio
    async def test_activity_tracks_latest_message_in_batch(
        self, db_session, ingest_service, mock_adapter, setup_conversation
    ):
        """last_activity_at should reflect the latest message in a batch."""
        msg_time_1 = datetime(2025, 1, 2, 10, 0, tzinfo=timezone.utc)
        msg_time_2 = datetime(2025, 1, 3, 14, 0, tzinfo=timezone.utc)  # Latest
        msg_time_3 = datetime(2025, 1, 2, 16, 0, tzinfo=timezone.utc)

        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_1",
                    conversation_id="conv_123",
                    direction=MessageDirection.IN,
                    body_text="Message 1",
                    sent_at=msg_time_1,
                    remote_visibility=RemoteVisibility.VISIBLE,
                ),
                ProviderMessage(
                    external_id="msg_2",
                    conversation_id="conv_123",
                    direction=MessageDirection.OUT,
                    body_text="Message 2",
                    sent_at=msg_time_2,
                    remote_visibility=RemoteVisibility.VISIBLE,
                ),
                ProviderMessage(
                    external_id="msg_3",
                    conversation_id="conv_123",
                    direction=MessageDirection.IN,
                    body_text="Message 3",
                    sent_at=msg_time_3,
                    remote_visibility=RemoteVisibility.VISIBLE,
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        await ingest_service.backfill_messages("conv_123")
        db_session.flush()

        conv = db_session.query(Conversation).filter_by(
            external_conversation_id="conv_123"
        ).first()
        db_session.refresh(conv)

        # Should be msg_time_2 (the latest)
        assert conv.last_activity_at == msg_time_2.replace(tzinfo=None)

    @pytest.mark.asyncio
    async def test_activity_handles_timezone_aware_datetimes(
        self, db_session, ingest_service, mock_adapter
    ):
        """Timezone-aware datetimes should be normalized to naive for storage."""
        # Use different timezones
        pst = timezone(timedelta(hours=-8))

        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_tz",
                    counterpart_id="t2_user1",
                    counterpart_username="testuser",
                    last_message_at=datetime(2025, 1, 1, 12, 0, tzinfo=pst),
                )
            ],
            next_cursor=None,
            has_more=False,
        )
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[], next_cursor=None, has_more=False
        )

        await ingest_service.backfill_conversations()
        db_session.flush()

        conv = db_session.query(Conversation).filter_by(
            external_conversation_id="conv_tz"
        ).first()

        # Stored as naive datetime (timezone stripped)
        assert conv.last_activity_at.tzinfo is None

    @pytest.mark.asyncio
    async def test_activity_from_conversation_sync_updates_existing(
        self, db_session, ingest_service, mock_adapter, setup_conversation
    ):
        """Conversation sync should update last_activity_at from provider data."""
        new_activity = datetime(2025, 1, 10, 12, 0, tzinfo=timezone.utc)

        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_123",
                    counterpart_id="t2_user1",
                    counterpart_username="testuser",
                    last_message_at=new_activity,
                )
            ],
            next_cursor=None,
            has_more=False,
        )
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[], next_cursor=None, has_more=False
        )

        await ingest_service.backfill_conversations()
        db_session.flush()

        conv = db_session.query(Conversation).filter_by(
            external_conversation_id="conv_123"
        ).first()
        db_session.refresh(conv)

        assert conv.last_activity_at == new_activity.replace(tzinfo=None)


# =============================================================================
# IDEMPOTENCY TESTS
# =============================================================================


class TestIdempotency:
    """Tests for idempotent sync operations.

    Multiple sync runs should:
    - Not create duplicate conversations
    - Not create duplicate messages
    - Not lose data
    - Produce consistent results
    """

    @pytest.mark.asyncio
    async def test_multiple_full_syncs_are_idempotent(
        self, db_session, ingest_service, mock_adapter
    ):
        """Running full sync multiple times produces same results."""
        conv_time = datetime.now(timezone.utc)

        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_1",
                    counterpart_id="t2_user1",
                    counterpart_username="user1",
                    last_message_at=conv_time,
                ),
                ProviderConversation(
                    external_id="conv_2",
                    counterpart_id="t2_user2",
                    counterpart_username="user2",
                    last_message_at=conv_time,
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        def create_messages(conv_id):
            return PaginatedResult(
                items=[
                    ProviderMessage(
                        external_id=f"{conv_id}_msg_1",
                        conversation_id=conv_id,
                        direction=MessageDirection.IN,
                        body_text=f"Message 1 in {conv_id}",
                        sent_at=conv_time,
                        remote_visibility=RemoteVisibility.VISIBLE,
                    ),
                    ProviderMessage(
                        external_id=f"{conv_id}_msg_2",
                        conversation_id=conv_id,
                        direction=MessageDirection.OUT,
                        body_text=f"Message 2 in {conv_id}",
                        sent_at=conv_time,
                        remote_visibility=RemoteVisibility.VISIBLE,
                    ),
                ],
                next_cursor=None,
                has_more=False,
            )

        mock_adapter.list_messages.side_effect = [
            create_messages("conv_1"),
            create_messages("conv_2"),
        ]

        # First sync: backfill conversations then messages
        await ingest_service.backfill_conversations()
        await ingest_service.backfill_messages("conv_1")
        await ingest_service.backfill_messages("conv_2")
        db_session.flush()

        conv_count_1 = db_session.query(Conversation).count()
        msg_count_1 = db_session.query(Message).count()

        # Reset mock for second sync
        mock_adapter.list_messages.side_effect = [
            create_messages("conv_1"),
            create_messages("conv_2"),
        ]

        # Second sync with same data
        await ingest_service.backfill_conversations()
        await ingest_service.backfill_messages("conv_1")
        await ingest_service.backfill_messages("conv_2")
        db_session.flush()

        conv_count_2 = db_session.query(Conversation).count()
        msg_count_2 = db_session.query(Message).count()

        # Counts should be identical
        assert conv_count_1 == conv_count_2 == 2
        assert msg_count_1 == msg_count_2 == 4

    @pytest.mark.asyncio
    async def test_interleaved_sync_and_backfill_consistent(
        self, db_session, ingest_service, mock_adapter
    ):
        """Interleaving sync_delta and backfill should produce consistent data."""
        base_time = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        new_time = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)

        # Initial backfill
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_1",
                    counterpart_id="t2_user1",
                    counterpart_username="user1",
                    last_message_at=base_time,
                )
            ],
            next_cursor=None,
            has_more=False,
        )
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_1",
                    conversation_id="conv_1",
                    direction=MessageDirection.IN,
                    body_text="Initial message",
                    sent_at=base_time,
                    remote_visibility=RemoteVisibility.VISIBLE,
                )
            ],
            next_cursor=None,
            has_more=False,
        )

        await ingest_service.backfill_all()
        db_session.flush()

        # Delta sync with new message
        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_1",
                    counterpart_id="t2_user1",
                    counterpart_username="user1",
                    last_message_at=new_time,
                )
            ],
            next_cursor=None,
            has_more=False,
        )
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[
                ProviderMessage(
                    external_id="msg_1",
                    conversation_id="conv_1",
                    direction=MessageDirection.IN,
                    body_text="Initial message",
                    sent_at=base_time,
                    remote_visibility=RemoteVisibility.VISIBLE,
                ),
                ProviderMessage(
                    external_id="msg_2",
                    conversation_id="conv_1",
                    direction=MessageDirection.OUT,
                    body_text="New message",
                    sent_at=new_time,
                    remote_visibility=RemoteVisibility.VISIBLE,
                ),
            ],
            next_cursor=None,
            has_more=False,
        )

        await ingest_service.sync_delta(since_ts=base_time)
        db_session.flush()

        # Verify state
        conv = db_session.query(Conversation).filter_by(
            external_conversation_id="conv_1"
        ).first()
        msgs = db_session.query(Message).filter_by(
            conversation_id=conv.id
        ).all()

        assert len(msgs) == 2
        assert conv.last_activity_at == new_time.replace(tzinfo=None)

    @pytest.mark.asyncio
    async def test_account_not_duplicated_across_conversations(
        self, db_session, ingest_service, mock_adapter
    ):
        """Same counterpart in multiple conversations should use one account."""
        conv_time = datetime.now(timezone.utc)

        mock_adapter.list_conversations.return_value = PaginatedResult(
            items=[
                ProviderConversation(
                    external_id="conv_1",
                    counterpart_id="t2_shared_user",
                    counterpart_username="shared_user",
                    last_message_at=conv_time,
                ),
                ProviderConversation(
                    external_id="conv_2",
                    counterpart_id="t2_shared_user",  # Same user
                    counterpart_username="shared_user",
                    last_message_at=conv_time,
                ),
            ],
            next_cursor=None,
            has_more=False,
        )
        mock_adapter.list_messages.return_value = PaginatedResult(
            items=[], next_cursor=None, has_more=False
        )

        await ingest_service.backfill_conversations()
        db_session.flush()

        # Should have only one account
        account_count = db_session.query(ExternalAccount).filter_by(
            external_username="shared_user"
        ).count()
        assert account_count == 1

        # Both conversations should reference the same account
        convs = db_session.query(Conversation).all()
        assert len(convs) == 2
        assert convs[0].counterpart_account_id == convs[1].counterpart_account_id
