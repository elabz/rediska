"""Unit tests for remote status mapper.

Tests the mapping of provider-specific deletion states to normalized
RemoteStatus and RemoteVisibility values. This ensures that:
1. Provider data is correctly classified
2. Local data is never deleted (only status updated)
3. Deletion timestamps are properly recorded
"""

from datetime import datetime, timezone

import pytest

from rediska_core.providers.base import RemoteVisibility as ProviderVisibility
from rediska_core.domain.services.remote_status import (
    RemoteStatusMapper,
    AccountStatus,
    ContentVisibility,
)


# =============================================================================
# ACCOUNT STATUS MAPPING TESTS
# =============================================================================


class TestAccountStatusMapping:
    """Tests for mapping provider profile data to AccountStatus."""

    def test_active_user_returns_active(self):
        """Active user profile should return ACTIVE status."""
        mapper = RemoteStatusMapper()

        profile_data = {
            "name": "test_user",
            "is_suspended": False,
        }

        result = mapper.map_account_status(profile_data, provider_id="reddit")

        assert result.status == AccountStatus.ACTIVE
        assert result.detected_at is not None

    def test_suspended_user_returns_suspended(self):
        """Suspended user should return SUSPENDED status."""
        mapper = RemoteStatusMapper()

        profile_data = {
            "name": "suspended_user",
            "is_suspended": True,
        }

        result = mapper.map_account_status(profile_data, provider_id="reddit")

        assert result.status == AccountStatus.SUSPENDED

    def test_deleted_username_returns_deleted(self):
        """User with [deleted] username should return DELETED status."""
        mapper = RemoteStatusMapper()

        profile_data = {
            "name": "[deleted]",
        }

        result = mapper.map_account_status(profile_data, provider_id="reddit")

        assert result.status == AccountStatus.DELETED

    def test_none_profile_returns_unknown(self):
        """None profile data should return UNKNOWN status."""
        mapper = RemoteStatusMapper()

        result = mapper.map_account_status(None, provider_id="reddit")

        assert result.status == AccountStatus.UNKNOWN

    def test_empty_profile_returns_unknown(self):
        """Empty profile dict should return UNKNOWN status."""
        mapper = RemoteStatusMapper()

        result = mapper.map_account_status({}, provider_id="reddit")

        assert result.status == AccountStatus.UNKNOWN

    def test_profile_404_error_returns_deleted(self):
        """Profile fetch 404 error indicator should return DELETED."""
        mapper = RemoteStatusMapper()

        profile_data = {
            "_error": "not_found",
            "_status_code": 404,
        }

        result = mapper.map_account_status(profile_data, provider_id="reddit")

        assert result.status == AccountStatus.DELETED

    def test_profile_403_error_returns_suspended(self):
        """Profile fetch 403 error indicator should return SUSPENDED."""
        mapper = RemoteStatusMapper()

        profile_data = {
            "_error": "forbidden",
            "_status_code": 403,
        }

        result = mapper.map_account_status(profile_data, provider_id="reddit")

        assert result.status == AccountStatus.SUSPENDED

    def test_shadowbanned_user_returns_deleted(self):
        """Shadowbanned user (empty submissions but exists) should return DELETED."""
        mapper = RemoteStatusMapper()

        profile_data = {
            "name": "shadow_user",
            "_shadowbanned": True,
        }

        result = mapper.map_account_status(profile_data, provider_id="reddit")

        assert result.status == AccountStatus.DELETED


# =============================================================================
# CONTENT VISIBILITY MAPPING TESTS
# =============================================================================


class TestContentVisibilityMapping:
    """Tests for mapping provider content data to ContentVisibility."""

    def test_visible_content_returns_visible(self):
        """Normal visible content should return VISIBLE."""
        mapper = RemoteStatusMapper()

        content_data = {
            "author": "real_user",
            "body": "This is a message",
        }

        result = mapper.map_content_visibility(content_data, provider_id="reddit")

        assert result.visibility == ContentVisibility.VISIBLE

    def test_deleted_author_returns_deleted_by_author(self):
        """Content with [deleted] author should return DELETED_BY_AUTHOR."""
        mapper = RemoteStatusMapper()

        content_data = {
            "author": "[deleted]",
            "body": "[deleted]",
        }

        result = mapper.map_content_visibility(content_data, provider_id="reddit")

        assert result.visibility == ContentVisibility.DELETED_BY_AUTHOR

    def test_removed_content_returns_removed(self):
        """Content removed by moderator should return REMOVED."""
        mapper = RemoteStatusMapper()

        content_data = {
            "author": "some_user",
            "removed_by_category": "moderator",
        }

        result = mapper.map_content_visibility(content_data, provider_id="reddit")

        assert result.visibility == ContentVisibility.REMOVED

    def test_spam_removed_returns_removed(self):
        """Content removed as spam should return REMOVED."""
        mapper = RemoteStatusMapper()

        content_data = {
            "author": "spammer",
            "removed_by_category": "spam",
        }

        result = mapper.map_content_visibility(content_data, provider_id="reddit")

        assert result.visibility == ContentVisibility.REMOVED

    def test_none_content_returns_unknown(self):
        """None content data should return UNKNOWN."""
        mapper = RemoteStatusMapper()

        result = mapper.map_content_visibility(None, provider_id="reddit")

        assert result.visibility == ContentVisibility.UNKNOWN

    def test_content_404_returns_deleted_by_author(self):
        """Content fetch 404 should return DELETED_BY_AUTHOR."""
        mapper = RemoteStatusMapper()

        content_data = {
            "_error": "not_found",
            "_status_code": 404,
        }

        result = mapper.map_content_visibility(content_data, provider_id="reddit")

        assert result.visibility == ContentVisibility.DELETED_BY_AUTHOR

    def test_selftext_removed_returns_removed(self):
        """Post with [removed] selftext but visible author should return REMOVED."""
        mapper = RemoteStatusMapper()

        content_data = {
            "author": "real_user",
            "selftext": "[removed]",
        }

        result = mapper.map_content_visibility(content_data, provider_id="reddit")

        assert result.visibility == ContentVisibility.REMOVED


# =============================================================================
# PROVIDER VISIBILITY DTO MAPPING TESTS
# =============================================================================


class TestProviderVisibilityMapping:
    """Tests for mapping ProviderPost/ProviderMessage visibility to ContentVisibility."""

    def test_provider_visible_maps_to_visible(self):
        """ProviderVisibility.VISIBLE should map to ContentVisibility.VISIBLE."""
        mapper = RemoteStatusMapper()

        result = mapper.from_provider_visibility(ProviderVisibility.VISIBLE)

        assert result == ContentVisibility.VISIBLE

    def test_provider_deleted_maps_to_deleted(self):
        """ProviderVisibility.DELETED_BY_AUTHOR should map correctly."""
        mapper = RemoteStatusMapper()

        result = mapper.from_provider_visibility(ProviderVisibility.DELETED_BY_AUTHOR)

        assert result == ContentVisibility.DELETED_BY_AUTHOR

    def test_provider_removed_maps_to_removed(self):
        """ProviderVisibility.REMOVED should map correctly."""
        mapper = RemoteStatusMapper()

        result = mapper.from_provider_visibility(ProviderVisibility.REMOVED)

        assert result == ContentVisibility.REMOVED

    def test_provider_unknown_maps_to_unknown(self):
        """ProviderVisibility.UNKNOWN should map correctly."""
        mapper = RemoteStatusMapper()

        result = mapper.from_provider_visibility(ProviderVisibility.UNKNOWN)

        assert result == ContentVisibility.UNKNOWN


# =============================================================================
# DETECTION TIMESTAMP TESTS
# =============================================================================


class TestDetectionTimestamps:
    """Tests for proper recording of detection timestamps."""

    def test_account_status_includes_detection_time(self):
        """Account status result should include detection timestamp."""
        mapper = RemoteStatusMapper()
        before = datetime.now(timezone.utc)

        result = mapper.map_account_status({"is_suspended": True}, provider_id="reddit")

        after = datetime.now(timezone.utc)
        assert result.detected_at is not None
        assert before <= result.detected_at <= after

    def test_content_visibility_includes_detection_time(self):
        """Content visibility result should include detection timestamp."""
        mapper = RemoteStatusMapper()
        before = datetime.now(timezone.utc)

        result = mapper.map_content_visibility({"author": "[deleted]"}, provider_id="reddit")

        after = datetime.now(timezone.utc)
        assert result.detected_at is not None
        assert before <= result.detected_at <= after

    def test_custom_detection_time_is_used(self):
        """Custom detection time should be used when provided."""
        mapper = RemoteStatusMapper()
        custom_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        result = mapper.map_account_status(
            {"is_suspended": True},
            provider_id="reddit",
            detected_at=custom_time
        )

        assert result.detected_at == custom_time


# =============================================================================
# STATUS TRANSITION TESTS
# =============================================================================


class TestStatusTransitions:
    """Tests for status transition logic."""

    def test_should_update_when_status_changes(self):
        """should_update_status returns True when status changes."""
        mapper = RemoteStatusMapper()

        assert mapper.should_update_status(
            current=AccountStatus.ACTIVE,
            new=AccountStatus.DELETED
        ) is True

    def test_should_not_update_when_status_same(self):
        """should_update_status returns False when status unchanged."""
        mapper = RemoteStatusMapper()

        assert mapper.should_update_status(
            current=AccountStatus.ACTIVE,
            new=AccountStatus.ACTIVE
        ) is False

    def test_should_update_unknown_to_known(self):
        """Unknown status should be updated to any known status."""
        mapper = RemoteStatusMapper()

        assert mapper.should_update_status(
            current=AccountStatus.UNKNOWN,
            new=AccountStatus.ACTIVE
        ) is True

    def test_should_not_downgrade_known_to_unknown(self):
        """Known status should not be downgraded to unknown."""
        mapper = RemoteStatusMapper()

        assert mapper.should_update_status(
            current=AccountStatus.DELETED,
            new=AccountStatus.UNKNOWN
        ) is False

    def test_visibility_should_update_when_changed(self):
        """should_update_visibility returns True when visibility changes."""
        mapper = RemoteStatusMapper()

        assert mapper.should_update_visibility(
            current=ContentVisibility.VISIBLE,
            new=ContentVisibility.DELETED_BY_AUTHOR
        ) is True

    def test_visibility_should_not_downgrade_to_unknown(self):
        """Known visibility should not be downgraded to unknown."""
        mapper = RemoteStatusMapper()

        assert mapper.should_update_visibility(
            current=ContentVisibility.VISIBLE,
            new=ContentVisibility.UNKNOWN
        ) is False


# =============================================================================
# REDDIT-SPECIFIC MAPPING TESTS
# =============================================================================


class TestRedditSpecificMapping:
    """Tests for Reddit-specific mapping patterns."""

    def test_reddit_post_with_over_18_stays_visible(self):
        """NSFW posts should still be marked visible."""
        mapper = RemoteStatusMapper()

        content_data = {
            "author": "nsfw_poster",
            "over_18": True,
            "title": "NSFW content",
        }

        result = mapper.map_content_visibility(content_data, provider_id="reddit")

        assert result.visibility == ContentVisibility.VISIBLE

    def test_reddit_locked_post_stays_visible(self):
        """Locked posts should still be marked visible."""
        mapper = RemoteStatusMapper()

        content_data = {
            "author": "poster",
            "locked": True,
            "title": "Locked post",
        }

        result = mapper.map_content_visibility(content_data, provider_id="reddit")

        assert result.visibility == ContentVisibility.VISIBLE

    def test_reddit_archived_post_stays_visible(self):
        """Archived posts should still be marked visible."""
        mapper = RemoteStatusMapper()

        content_data = {
            "author": "poster",
            "archived": True,
            "title": "Old post",
        }

        result = mapper.map_content_visibility(content_data, provider_id="reddit")

        assert result.visibility == ContentVisibility.VISIBLE

    def test_reddit_comment_body_deleted_returns_deleted(self):
        """Comment with [deleted] body should return DELETED_BY_AUTHOR."""
        mapper = RemoteStatusMapper()

        content_data = {
            "author": "[deleted]",
            "body": "[deleted]",
        }

        result = mapper.map_content_visibility(content_data, provider_id="reddit")

        assert result.visibility == ContentVisibility.DELETED_BY_AUTHOR

    def test_reddit_awarder_karma_ignored(self):
        """Profile with awarder_karma should not affect status."""
        mapper = RemoteStatusMapper()

        profile_data = {
            "name": "karma_user",
            "awarder_karma": 100,
            "is_suspended": False,
        }

        result = mapper.map_account_status(profile_data, provider_id="reddit")

        assert result.status == AccountStatus.ACTIVE


# =============================================================================
# GENERIC PROVIDER MAPPING TESTS
# =============================================================================


class TestGenericProviderMapping:
    """Tests for generic (non-Reddit) provider mapping."""

    def test_generic_provider_uses_default_rules(self):
        """Unknown provider should use generic mapping rules."""
        mapper = RemoteStatusMapper()

        profile_data = {
            "username": "user",
            "active": True,
        }

        # Should not raise, just use defaults
        result = mapper.map_account_status(profile_data, provider_id="unknown_provider")

        # Without specific rules, defaults to UNKNOWN
        assert result.status in (AccountStatus.ACTIVE, AccountStatus.UNKNOWN)

    def test_generic_deleted_indicator(self):
        """Generic deleted indicator should be detected."""
        mapper = RemoteStatusMapper()

        profile_data = {
            "deleted": True,
        }

        result = mapper.map_account_status(profile_data, provider_id="generic")

        assert result.status == AccountStatus.DELETED
