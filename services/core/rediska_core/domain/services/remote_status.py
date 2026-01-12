"""Remote status mapper service.

Maps provider-specific deletion/visibility states to normalized internal values.
This service ensures that:
1. Provider data is correctly classified into our internal status enums
2. Local data is NEVER deleted - only status/visibility fields are updated
3. Deletion detection timestamps are properly recorded

The "no remote delete" policy is enforced at the sync layer, not here.
This service provides the mapping logic that sync uses to update fields.

Usage:
    mapper = RemoteStatusMapper()

    # Map account status from provider profile data
    result = mapper.map_account_status(profile_data, provider_id="reddit")
    if mapper.should_update_status(current_status, result.status):
        account.remote_status = result.status.value
        account.remote_status_last_seen_at = result.detected_at

    # Map content visibility from provider content data
    result = mapper.map_content_visibility(content_data, provider_id="reddit")
    if mapper.should_update_visibility(current_visibility, result.visibility):
        message.remote_visibility = result.visibility.value
        message.remote_deleted_at = result.detected_at
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from rediska_core.providers.base import RemoteVisibility as ProviderVisibility


class AccountStatus(str, Enum):
    """Normalized account status values.

    Maps to ExternalAccount.remote_status in the database.
    """

    ACTIVE = "active"
    DELETED = "deleted"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"


class ContentVisibility(str, Enum):
    """Normalized content visibility values.

    Maps to Message/LeadPost/ProfileItem.remote_visibility in the database.
    """

    VISIBLE = "visible"
    DELETED_BY_AUTHOR = "deleted_by_author"
    REMOVED = "removed"
    UNKNOWN = "unknown"


@dataclass
class AccountStatusResult:
    """Result of account status mapping."""

    status: AccountStatus
    detected_at: datetime


@dataclass
class ContentVisibilityResult:
    """Result of content visibility mapping."""

    visibility: ContentVisibility
    detected_at: datetime


class RemoteStatusMapper:
    """Maps provider-specific states to normalized internal values.

    This mapper handles the translation of provider-specific deletion,
    suspension, and removal indicators to our internal enum values.
    It also tracks when these states were detected.
    """

    # Reddit-specific indicators for deleted users
    REDDIT_DELETED_USERNAMES = {"[deleted]", "[removed]"}

    # Reddit-specific indicators for removed content
    REDDIT_REMOVED_INDICATORS = {"[removed]", "[deleted by user]"}

    def map_account_status(
        self,
        profile_data: Optional[dict[str, Any]],
        provider_id: str,
        detected_at: Optional[datetime] = None,
    ) -> AccountStatusResult:
        """Map provider profile data to normalized account status.

        Args:
            profile_data: Raw profile data from provider, or None if not found.
            provider_id: The provider identifier (e.g., "reddit").
            detected_at: Optional timestamp for when the status was detected.

        Returns:
            AccountStatusResult with status and detection timestamp.
        """
        if detected_at is None:
            detected_at = datetime.now(timezone.utc)

        # Handle None or empty profile
        if not profile_data:
            return AccountStatusResult(status=AccountStatus.UNKNOWN, detected_at=detected_at)

        # Check for error indicators first
        if "_error" in profile_data:
            status_code = profile_data.get("_status_code", 0)
            if status_code == 404:
                return AccountStatusResult(status=AccountStatus.DELETED, detected_at=detected_at)
            if status_code == 403:
                return AccountStatusResult(
                    status=AccountStatus.SUSPENDED, detected_at=detected_at
                )
            return AccountStatusResult(status=AccountStatus.UNKNOWN, detected_at=detected_at)

        # Provider-specific mapping
        if provider_id == "reddit":
            return self._map_reddit_account_status(profile_data, detected_at)

        # Generic mapping for unknown providers
        return self._map_generic_account_status(profile_data, detected_at)

    def _map_reddit_account_status(
        self, profile_data: dict[str, Any], detected_at: datetime
    ) -> AccountStatusResult:
        """Map Reddit-specific profile data to account status."""
        # Check for deleted username
        username = profile_data.get("name", "")
        if username in self.REDDIT_DELETED_USERNAMES:
            return AccountStatusResult(status=AccountStatus.DELETED, detected_at=detected_at)

        # Check for suspension
        if profile_data.get("is_suspended", False):
            return AccountStatusResult(status=AccountStatus.SUSPENDED, detected_at=detected_at)

        # Check for shadowban indicator
        if profile_data.get("_shadowbanned", False):
            return AccountStatusResult(status=AccountStatus.DELETED, detected_at=detected_at)

        # If we have a valid username and no suspension, they're active
        if username and username not in self.REDDIT_DELETED_USERNAMES:
            return AccountStatusResult(status=AccountStatus.ACTIVE, detected_at=detected_at)

        return AccountStatusResult(status=AccountStatus.UNKNOWN, detected_at=detected_at)

    def _map_generic_account_status(
        self, profile_data: dict[str, Any], detected_at: datetime
    ) -> AccountStatusResult:
        """Map generic profile data to account status."""
        # Check for common deleted indicators
        if profile_data.get("deleted", False):
            return AccountStatusResult(status=AccountStatus.DELETED, detected_at=detected_at)

        if profile_data.get("suspended", False):
            return AccountStatusResult(status=AccountStatus.SUSPENDED, detected_at=detected_at)

        # Check for active indicator
        if profile_data.get("active", False):
            return AccountStatusResult(status=AccountStatus.ACTIVE, detected_at=detected_at)

        # Check if username exists (basic indicator of active)
        if profile_data.get("username") or profile_data.get("name"):
            return AccountStatusResult(status=AccountStatus.ACTIVE, detected_at=detected_at)

        return AccountStatusResult(status=AccountStatus.UNKNOWN, detected_at=detected_at)

    def map_content_visibility(
        self,
        content_data: Optional[dict[str, Any]],
        provider_id: str,
        detected_at: Optional[datetime] = None,
    ) -> ContentVisibilityResult:
        """Map provider content data to normalized visibility.

        Args:
            content_data: Raw content data from provider, or None if not found.
            provider_id: The provider identifier (e.g., "reddit").
            detected_at: Optional timestamp for when the visibility was detected.

        Returns:
            ContentVisibilityResult with visibility and detection timestamp.
        """
        if detected_at is None:
            detected_at = datetime.now(timezone.utc)

        # Handle None content
        if content_data is None:
            return ContentVisibilityResult(
                visibility=ContentVisibility.UNKNOWN, detected_at=detected_at
            )

        # Check for error indicators first
        if "_error" in content_data:
            status_code = content_data.get("_status_code", 0)
            if status_code == 404:
                return ContentVisibilityResult(
                    visibility=ContentVisibility.DELETED_BY_AUTHOR, detected_at=detected_at
                )
            return ContentVisibilityResult(
                visibility=ContentVisibility.UNKNOWN, detected_at=detected_at
            )

        # Provider-specific mapping
        if provider_id == "reddit":
            return self._map_reddit_content_visibility(content_data, detected_at)

        # Generic mapping for unknown providers
        return self._map_generic_content_visibility(content_data, detected_at)

    def _map_reddit_content_visibility(
        self, content_data: dict[str, Any], detected_at: datetime
    ) -> ContentVisibilityResult:
        """Map Reddit-specific content data to visibility."""
        author = content_data.get("author", "")

        # Check for removed by moderator/admin
        removed_by = content_data.get("removed_by_category")
        if removed_by:
            return ContentVisibilityResult(
                visibility=ContentVisibility.REMOVED, detected_at=detected_at
            )

        # Check for [removed] selftext (mod removal of post body)
        selftext = content_data.get("selftext", "")
        if selftext in self.REDDIT_REMOVED_INDICATORS and author not in self.REDDIT_DELETED_USERNAMES:
            return ContentVisibilityResult(
                visibility=ContentVisibility.REMOVED, detected_at=detected_at
            )

        # Check for deleted author (user deleted their content)
        if author in self.REDDIT_DELETED_USERNAMES:
            return ContentVisibilityResult(
                visibility=ContentVisibility.DELETED_BY_AUTHOR, detected_at=detected_at
            )

        # Check for [deleted] body (comment deletion)
        body = content_data.get("body", "")
        if body in self.REDDIT_REMOVED_INDICATORS:
            return ContentVisibilityResult(
                visibility=ContentVisibility.DELETED_BY_AUTHOR, detected_at=detected_at
            )

        # Content is visible (locked/archived/NSFW doesn't affect visibility)
        return ContentVisibilityResult(
            visibility=ContentVisibility.VISIBLE, detected_at=detected_at
        )

    def _map_generic_content_visibility(
        self, content_data: dict[str, Any], detected_at: datetime
    ) -> ContentVisibilityResult:
        """Map generic content data to visibility."""
        # Check for common deleted indicators
        if content_data.get("deleted", False):
            return ContentVisibilityResult(
                visibility=ContentVisibility.DELETED_BY_AUTHOR, detected_at=detected_at
            )

        if content_data.get("removed", False):
            return ContentVisibilityResult(
                visibility=ContentVisibility.REMOVED, detected_at=detected_at
            )

        # Default to visible if we have content
        if content_data.get("body") or content_data.get("text") or content_data.get("content"):
            return ContentVisibilityResult(
                visibility=ContentVisibility.VISIBLE, detected_at=detected_at
            )

        return ContentVisibilityResult(
            visibility=ContentVisibility.UNKNOWN, detected_at=detected_at
        )

    def from_provider_visibility(self, visibility: ProviderVisibility) -> ContentVisibility:
        """Convert provider adapter visibility to internal visibility.

        Args:
            visibility: ProviderVisibility from the adapter DTOs.

        Returns:
            Corresponding ContentVisibility enum value.
        """
        mapping = {
            ProviderVisibility.VISIBLE: ContentVisibility.VISIBLE,
            ProviderVisibility.DELETED_BY_AUTHOR: ContentVisibility.DELETED_BY_AUTHOR,
            ProviderVisibility.REMOVED: ContentVisibility.REMOVED,
            ProviderVisibility.UNKNOWN: ContentVisibility.UNKNOWN,
        }
        return mapping.get(visibility, ContentVisibility.UNKNOWN)

    def should_update_status(
        self, current: AccountStatus, new: AccountStatus
    ) -> bool:
        """Determine if account status should be updated.

        Rules:
        - Always update if status actually changed (and not downgrading to unknown)
        - Never downgrade from a known status to unknown
        - Always update from unknown to any known status

        Args:
            current: Current account status.
            new: New detected status.

        Returns:
            True if status should be updated.
        """
        # No change
        if current == new:
            return False

        # Don't downgrade known status to unknown
        if current != AccountStatus.UNKNOWN and new == AccountStatus.UNKNOWN:
            return False

        # All other changes are valid
        return True

    def should_update_visibility(
        self, current: ContentVisibility, new: ContentVisibility
    ) -> bool:
        """Determine if content visibility should be updated.

        Rules:
        - Always update if visibility actually changed (and not downgrading to unknown)
        - Never downgrade from a known visibility to unknown
        - Always update from unknown to any known visibility

        Args:
            current: Current content visibility.
            new: New detected visibility.

        Returns:
            True if visibility should be updated.
        """
        # No change
        if current == new:
            return False

        # Don't downgrade known visibility to unknown
        if current != ContentVisibility.UNKNOWN and new == ContentVisibility.UNKNOWN:
            return False

        # All other changes are valid
        return True


# Export public interface
__all__ = [
    "RemoteStatusMapper",
    "AccountStatus",
    "ContentVisibility",
    "AccountStatusResult",
    "ContentVisibilityResult",
]
