"""Unit tests for sync status updater.

Tests the "no remote delete" policy enforcement:
1. Local rows are NEVER deleted when remote content is removed
2. Only status/visibility fields are updated
3. Deletion timestamps are recorded
4. Content is preserved locally even when remote is gone
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    ExternalAccount,
    Message,
    LeadPost,
    ProfileItem,
)
from rediska_core.domain.services.remote_status import (
    AccountStatus,
    ContentVisibility,
)
from rediska_core.domain.services.sync_status import SyncStatusUpdater
from rediska_core.providers.base import (
    ProviderPost,
    ProviderProfile,
    ProviderMessage,
    ProviderProfileItem,
    ProfileItemType as ProviderProfileItemType,
    RemoteVisibility as ProviderVisibility,
)


# =============================================================================
# ACCOUNT STATUS UPDATE TESTS
# =============================================================================


class TestAccountStatusUpdates:
    """Tests for account status updates (ExternalAccount.remote_status)."""

    @pytest.fixture(autouse=True)
    def setup_provider(self, db_session):
        """Create required provider for foreign key."""
        from rediska_core.domain.models import Provider

        provider = Provider(provider_id="reddit", display_name="Reddit")
        db_session.add(provider)
        db_session.flush()
        return provider

    def test_deleted_account_updates_status_not_row(self, db_session):
        """When account is deleted remotely, only status is updated, row remains."""
        updater = SyncStatusUpdater(db_session)

        # Create an active account
        account = ExternalAccount(
            provider_id="reddit",
            external_username="deleted_user",
            remote_status="active",
        )
        db_session.add(account)
        db_session.flush()
        account_id = account.id

        # Simulate deleted profile from provider
        profile = ProviderProfile(
            external_id="t2_deleted",
            username="[deleted]",
        )

        # Update status
        updater.update_account_status(account, profile)
        db_session.flush()

        # Verify row still exists and status is updated
        refreshed = db_session.get(ExternalAccount, account_id)
        assert refreshed is not None  # Row NOT deleted
        assert refreshed.remote_status == "deleted"
        assert refreshed.remote_status_last_seen_at is not None

    def test_suspended_account_updates_status(self, db_session):
        """Suspended account updates status field."""
        updater = SyncStatusUpdater(db_session)

        account = ExternalAccount(
            provider_id="reddit",
            external_username="suspended_user",
            remote_status="active",
        )
        db_session.add(account)
        db_session.flush()

        profile = ProviderProfile(
            external_id="t2_suspended",
            username="suspended_user",
            is_suspended=True,
            raw_data={"is_suspended": True},
        )

        updater.update_account_status(account, profile)
        db_session.flush()

        assert account.remote_status == "suspended"
        assert account.remote_status_last_seen_at is not None

    def test_active_account_stays_active(self, db_session):
        """Active account retains active status."""
        updater = SyncStatusUpdater(db_session)

        account = ExternalAccount(
            provider_id="reddit",
            external_username="active_user",
            remote_status="active",
        )
        db_session.add(account)
        db_session.flush()

        profile = ProviderProfile(
            external_id="t2_active",
            username="active_user",
            is_suspended=False,
            raw_data={"is_suspended": False},
        )

        updater.update_account_status(account, profile)
        db_session.flush()

        assert account.remote_status == "active"

    def test_unknown_not_downgraded_to_unknown(self, db_session):
        """Known status is not downgraded to unknown on fetch failure."""
        updater = SyncStatusUpdater(db_session)

        account = ExternalAccount(
            provider_id="reddit",
            external_username="known_user",
            remote_status="active",
        )
        db_session.add(account)
        db_session.flush()

        # Simulate failed fetch (None profile)
        updater.update_account_status(account, None)
        db_session.flush()

        # Status should remain active, not downgraded to unknown
        assert account.remote_status == "active"

    def test_preserves_original_username(self, db_session):
        """Account username is preserved even when remote shows [deleted]."""
        updater = SyncStatusUpdater(db_session)

        account = ExternalAccount(
            provider_id="reddit",
            external_username="original_username",
            remote_status="active",
        )
        db_session.add(account)
        db_session.flush()

        profile = ProviderProfile(
            external_id="t2_deleted",
            username="[deleted]",
        )

        updater.update_account_status(account, profile)
        db_session.flush()

        # Original username preserved
        assert account.external_username == "original_username"
        assert account.remote_status == "deleted"


# =============================================================================
# MESSAGE VISIBILITY UPDATE TESTS
# =============================================================================


class TestMessageVisibilityUpdates:
    """Tests for message visibility updates (Message.remote_visibility)."""

    @pytest.fixture
    def sample_message(self, db_session):
        """Create a sample message for testing."""
        from rediska_core.domain.models import Conversation, Identity, Provider

        # Create dependencies
        provider = Provider(provider_id="reddit", display_name="Reddit")
        db_session.add(provider)

        identity = Identity(
            provider_id="reddit",
            external_username="my_user",
            display_name="My User",
        )
        db_session.add(identity)

        account = ExternalAccount(
            provider_id="reddit",
            external_username="other_user",
            remote_status="active",
        )
        db_session.add(account)
        db_session.flush()

        conversation = Conversation(
            provider_id="reddit",
            external_conversation_id="conv_123",
            counterpart_account_id=account.id,
            identity_id=identity.id,
        )
        db_session.add(conversation)
        db_session.flush()

        message = Message(
            provider_id="reddit",
            external_message_id="msg_123",
            conversation_id=conversation.id,
            direction="in",
            sent_at=datetime.now(timezone.utc),
            body_text="Original message content",
            remote_visibility="visible",
        )
        db_session.add(message)
        db_session.flush()

        return message

    def test_deleted_message_updates_visibility_not_row(self, db_session, sample_message):
        """When message is deleted remotely, only visibility is updated, row remains."""
        updater = SyncStatusUpdater(db_session)
        message_id = sample_message.id

        provider_msg = ProviderMessage(
            external_id="msg_123",
            conversation_id="conv_123",
            direction="in",
            body_text="[deleted]",
            sent_at=datetime.now(timezone.utc),
            sender_username="[deleted]",
            remote_visibility=ProviderVisibility.DELETED_BY_AUTHOR,
        )

        updater.update_message_visibility(sample_message, provider_msg)
        db_session.flush()

        # Verify row still exists
        refreshed = db_session.get(Message, message_id)
        assert refreshed is not None  # Row NOT deleted
        assert refreshed.remote_visibility == "deleted_by_author"
        assert refreshed.remote_deleted_at is not None

    def test_preserves_original_message_content(self, db_session, sample_message):
        """Original message content is preserved when remote is deleted."""
        updater = SyncStatusUpdater(db_session)

        # Original content
        assert sample_message.body_text == "Original message content"

        provider_msg = ProviderMessage(
            external_id="msg_123",
            conversation_id="conv_123",
            direction="in",
            body_text="[deleted]",
            sent_at=datetime.now(timezone.utc),
            remote_visibility=ProviderVisibility.DELETED_BY_AUTHOR,
        )

        updater.update_message_visibility(sample_message, provider_msg)
        db_session.flush()

        # Original content preserved
        assert sample_message.body_text == "Original message content"
        assert sample_message.remote_visibility == "deleted_by_author"

    def test_removed_message_updates_visibility(self, db_session, sample_message):
        """Mod-removed message updates to REMOVED status."""
        updater = SyncStatusUpdater(db_session)

        provider_msg = ProviderMessage(
            external_id="msg_123",
            conversation_id="conv_123",
            direction="in",
            body_text="[removed]",
            sent_at=datetime.now(timezone.utc),
            remote_visibility=ProviderVisibility.REMOVED,
        )

        updater.update_message_visibility(sample_message, provider_msg)
        db_session.flush()

        assert sample_message.remote_visibility == "removed"


# =============================================================================
# LEAD POST VISIBILITY UPDATE TESTS
# =============================================================================


class TestLeadPostVisibilityUpdates:
    """Tests for lead post visibility updates (LeadPost.remote_visibility)."""

    @pytest.fixture
    def sample_lead_post(self, db_session):
        """Create a sample lead post for testing."""
        from rediska_core.domain.models import Provider

        provider = Provider(provider_id="reddit", display_name="Reddit")
        db_session.add(provider)
        db_session.flush()

        lead_post = LeadPost(
            provider_id="reddit",
            source_location="r/programming",
            external_post_id="post_123",
            post_url="https://reddit.com/r/programming/post_123",
            title="Original Post Title",
            body_text="Original post content here",
            remote_visibility="visible",
        )
        db_session.add(lead_post)
        db_session.flush()

        return lead_post

    def test_deleted_lead_post_updates_visibility_not_row(self, db_session, sample_lead_post):
        """When lead post is deleted remotely, only visibility is updated, row remains."""
        updater = SyncStatusUpdater(db_session)
        post_id = sample_lead_post.id

        provider_post = ProviderPost(
            external_id="post_123",
            author_id="",
            author_username="[deleted]",
            title="[deleted]",
            url="https://reddit.com/r/programming/post_123",
            location="r/programming",
            remote_visibility=ProviderVisibility.DELETED_BY_AUTHOR,
        )

        updater.update_lead_post_visibility(sample_lead_post, provider_post)
        db_session.flush()

        # Verify row still exists
        refreshed = db_session.get(LeadPost, post_id)
        assert refreshed is not None  # Row NOT deleted
        assert refreshed.remote_visibility == "deleted_by_author"
        assert refreshed.remote_deleted_at is not None

    def test_preserves_original_lead_post_content(self, db_session, sample_lead_post):
        """Original lead post content is preserved when remote is deleted."""
        updater = SyncStatusUpdater(db_session)

        # Original content
        assert sample_lead_post.title == "Original Post Title"
        assert sample_lead_post.body_text == "Original post content here"

        provider_post = ProviderPost(
            external_id="post_123",
            author_id="",
            author_username="[deleted]",
            title="[deleted]",
            url="https://reddit.com/r/programming/post_123",
            location="r/programming",
            remote_visibility=ProviderVisibility.DELETED_BY_AUTHOR,
        )

        updater.update_lead_post_visibility(sample_lead_post, provider_post)
        db_session.flush()

        # Original content preserved
        assert sample_lead_post.title == "Original Post Title"
        assert sample_lead_post.body_text == "Original post content here"
        assert sample_lead_post.remote_visibility == "deleted_by_author"

    def test_mod_removed_post_updates_visibility(self, db_session, sample_lead_post):
        """Mod-removed post updates to REMOVED status."""
        updater = SyncStatusUpdater(db_session)

        provider_post = ProviderPost(
            external_id="post_123",
            author_id="t2_author",
            author_username="some_user",
            title="Original Title",
            url="https://reddit.com/r/programming/post_123",
            location="r/programming",
            remote_visibility=ProviderVisibility.REMOVED,
        )

        updater.update_lead_post_visibility(sample_lead_post, provider_post)
        db_session.flush()

        assert sample_lead_post.remote_visibility == "removed"


# =============================================================================
# PROFILE ITEM VISIBILITY UPDATE TESTS
# =============================================================================


class TestProfileItemVisibilityUpdates:
    """Tests for profile item visibility updates (ProfileItem.remote_visibility)."""

    @pytest.fixture
    def sample_profile_item(self, db_session):
        """Create a sample profile item for testing."""
        from rediska_core.domain.models import Provider

        provider = Provider(provider_id="reddit", display_name="Reddit")
        db_session.add(provider)

        account = ExternalAccount(
            provider_id="reddit",
            external_username="content_creator",
            remote_status="active",
        )
        db_session.add(account)
        db_session.flush()

        profile_item = ProfileItem(
            account_id=account.id,
            item_type="post",
            external_item_id="item_123",
            text_content="Original comment content",
            remote_visibility="visible",
        )
        db_session.add(profile_item)
        db_session.flush()

        return profile_item

    def test_deleted_profile_item_updates_visibility_not_row(
        self, db_session, sample_profile_item
    ):
        """When profile item is deleted remotely, only visibility is updated, row remains."""
        updater = SyncStatusUpdater(db_session)
        item_id = sample_profile_item.id

        provider_item = ProviderProfileItem(
            external_id="item_123",
            item_type=ProviderProfileItemType.POST,
            author_id="",
            body_text="[deleted]",
            remote_visibility=ProviderVisibility.DELETED_BY_AUTHOR,
        )

        updater.update_profile_item_visibility(sample_profile_item, provider_item)
        db_session.flush()

        # Verify row still exists
        refreshed = db_session.get(ProfileItem, item_id)
        assert refreshed is not None  # Row NOT deleted
        assert refreshed.remote_visibility == "deleted_by_author"
        assert refreshed.remote_deleted_at is not None

    def test_preserves_original_profile_item_content(self, db_session, sample_profile_item):
        """Original profile item content is preserved when remote is deleted."""
        updater = SyncStatusUpdater(db_session)

        # Original content
        assert sample_profile_item.text_content == "Original comment content"

        provider_item = ProviderProfileItem(
            external_id="item_123",
            item_type=ProviderProfileItemType.POST,
            author_id="",
            body_text="[deleted]",
            remote_visibility=ProviderVisibility.DELETED_BY_AUTHOR,
        )

        updater.update_profile_item_visibility(sample_profile_item, provider_item)
        db_session.flush()

        # Original content preserved
        assert sample_profile_item.text_content == "Original comment content"
        assert sample_profile_item.remote_visibility == "deleted_by_author"


# =============================================================================
# BATCH UPDATE TESTS
# =============================================================================


class TestBatchUpdates:
    """Tests for batch update operations."""

    @pytest.fixture(autouse=True)
    def setup_provider(self, db_session):
        """Create required provider for foreign key."""
        from rediska_core.domain.models import Provider

        provider = Provider(provider_id="reddit", display_name="Reddit")
        db_session.add(provider)
        db_session.flush()
        return provider

    def test_batch_update_accounts_never_deletes(self, db_session):
        """Batch updating accounts never deletes rows."""
        updater = SyncStatusUpdater(db_session)

        # Create multiple accounts
        accounts = []
        for i in range(5):
            account = ExternalAccount(
                provider_id="reddit",
                external_username=f"user_{i}",
                remote_status="active",
            )
            db_session.add(account)
            accounts.append(account)
        db_session.flush()

        # Simulate some deleted, some suspended
        profiles = [
            ProviderProfile(external_id="0", username="[deleted]"),
            ProviderProfile(external_id="1", username="user_1", is_suspended=True, raw_data={"is_suspended": True}),
            None,  # Fetch failure
            ProviderProfile(external_id="3", username="user_3", raw_data={"is_suspended": False}),
            ProviderProfile(external_id="4", username="[deleted]"),
        ]

        for account, profile in zip(accounts, profiles):
            updater.update_account_status(account, profile)
        db_session.flush()

        # All accounts should still exist
        from sqlalchemy import select
        result = db_session.execute(
            select(ExternalAccount).where(ExternalAccount.provider_id == "reddit")
        ).scalars().all()

        assert len(result) == 5  # No deletions

        # Verify statuses
        status_map = {a.external_username: a.remote_status for a in result}
        assert status_map["user_0"] == "deleted"
        assert status_map["user_1"] == "suspended"
        assert status_map["user_2"] == "active"  # Preserved on failure
        assert status_map["user_3"] == "active"
        assert status_map["user_4"] == "deleted"


# =============================================================================
# AUDIT TRAIL TESTS
# =============================================================================


class TestAuditTrail:
    """Tests for audit trail of status changes."""

    @pytest.fixture(autouse=True)
    def setup_provider(self, db_session):
        """Create required provider for foreign key."""
        from rediska_core.domain.models import Provider

        provider = Provider(provider_id="reddit", display_name="Reddit")
        db_session.add(provider)
        db_session.flush()
        return provider

    def test_status_change_records_timestamp(self, db_session):
        """Status changes record when they were detected."""
        updater = SyncStatusUpdater(db_session)

        account = ExternalAccount(
            provider_id="reddit",
            external_username="test_user",
            remote_status="active",
            remote_status_last_seen_at=None,
        )
        db_session.add(account)
        db_session.flush()

        before = datetime.now(timezone.utc)

        profile = ProviderProfile(
            external_id="t2_test",
            username="[deleted]",
        )
        updater.update_account_status(account, profile)
        db_session.flush()

        after = datetime.now(timezone.utc)

        assert account.remote_status_last_seen_at is not None
        assert before <= account.remote_status_last_seen_at <= after

    def test_visibility_change_records_deleted_at(self, db_session):
        """Visibility changes record when deletion was detected."""
        from rediska_core.domain.models import Conversation, Identity

        identity = Identity(
            provider_id="reddit",
            external_username="my_user",
            display_name="My User",
        )
        db_session.add(identity)

        account = ExternalAccount(
            provider_id="reddit",
            external_username="other_user",
            remote_status="active",
        )
        db_session.add(account)
        db_session.flush()

        conversation = Conversation(
            provider_id="reddit",
            external_conversation_id="conv_123",
            counterpart_account_id=account.id,
            identity_id=identity.id,
        )
        db_session.add(conversation)
        db_session.flush()

        message = Message(
            provider_id="reddit",
            external_message_id="msg_audit_test",
            conversation_id=conversation.id,
            direction="in",
            sent_at=datetime.now(timezone.utc),
            body_text="Test message",
            remote_visibility="visible",
            remote_deleted_at=None,
        )
        db_session.add(message)
        db_session.flush()

        updater = SyncStatusUpdater(db_session)
        before = datetime.now(timezone.utc)

        provider_msg = ProviderMessage(
            external_id="msg_audit_test",
            conversation_id="conv_123",
            direction="in",
            body_text="[deleted]",
            sent_at=datetime.now(timezone.utc),
            remote_visibility=ProviderVisibility.DELETED_BY_AUTHOR,
        )
        updater.update_message_visibility(message, provider_msg)
        db_session.flush()

        after = datetime.now(timezone.utc)

        assert message.remote_deleted_at is not None
        assert before <= message.remote_deleted_at <= after
