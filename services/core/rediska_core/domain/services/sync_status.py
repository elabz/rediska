"""Sync status updater service.

Enforces the "no remote delete" policy by updating status/visibility fields
instead of deleting rows when content is removed remotely.

This service is used during sync operations to:
1. Update ExternalAccount.remote_status when users are deleted/suspended
2. Update Message/LeadPost/ProfileItem.remote_visibility when content is removed
3. Record timestamps of when deletions were detected
4. NEVER delete local rows - only update status fields

Usage:
    updater = SyncStatusUpdater(db_session)

    # Update account status from provider profile
    updater.update_account_status(account, provider_profile)

    # Update message visibility from provider message
    updater.update_message_visibility(message, provider_message)
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    ExternalAccount,
    LeadPost,
    Message,
    ProfileItem,
)
from rediska_core.domain.services.remote_status import (
    AccountStatus,
    ContentVisibility,
    RemoteStatusMapper,
)
from rediska_core.providers.base import (
    ProviderMessage,
    ProviderPost,
    ProviderProfile,
    ProviderProfileItem,
    RemoteVisibility as ProviderVisibility,
)


class SyncStatusUpdater:
    """Updates entity status/visibility without deleting rows.

    This service implements the "no remote delete" policy by:
    - Only updating status/visibility enum fields
    - Recording deletion detection timestamps
    - Preserving all original content locally
    - Never deleting database rows
    """

    def __init__(self, session: Session):
        """Initialize the updater.

        Args:
            session: SQLAlchemy session for database operations.
        """
        self.session = session
        self.mapper = RemoteStatusMapper()

    def update_account_status(
        self,
        account: ExternalAccount,
        profile: Optional[ProviderProfile],
    ) -> bool:
        """Update account status from provider profile data.

        IMPORTANT: This method NEVER deletes the account row.
        It only updates the remote_status and remote_status_last_seen_at fields.

        Args:
            account: The local ExternalAccount to update.
            profile: Provider profile data, or None if fetch failed.

        Returns:
            True if status was updated, False if unchanged.
        """
        now = datetime.now(timezone.utc)

        # Get raw data from profile if available
        raw_data = profile.raw_data if profile else None

        # If no raw_data, construct minimal data from profile fields
        if raw_data is None and profile is not None:
            raw_data = {
                "name": profile.username,
                "is_suspended": profile.is_suspended,
            }

        # Map to internal status
        result = self.mapper.map_account_status(
            profile_data=raw_data,
            provider_id=account.provider_id,
            detected_at=now,
        )

        # Get current status as enum
        try:
            current_status = AccountStatus(account.remote_status)
        except ValueError:
            current_status = AccountStatus.UNKNOWN

        # Check if we should update
        if not self.mapper.should_update_status(current_status, result.status):
            return False

        # Update status field (NEVER delete the row)
        account.remote_status = result.status.value
        account.remote_status_last_seen_at = result.detected_at

        return True

    def update_message_visibility(
        self,
        message: Message,
        provider_message: ProviderMessage,
    ) -> bool:
        """Update message visibility from provider message data.

        IMPORTANT: This method NEVER deletes the message row.
        It only updates remote_visibility and remote_deleted_at fields.
        Original body_text is preserved.

        Args:
            message: The local Message to update.
            provider_message: Provider message data with visibility info.

        Returns:
            True if visibility was updated, False if unchanged.
        """
        now = datetime.now(timezone.utc)

        # Map provider visibility to internal
        new_visibility = self.mapper.from_provider_visibility(
            provider_message.remote_visibility
        )

        # Get current visibility as enum
        try:
            current_visibility = ContentVisibility(message.remote_visibility)
        except ValueError:
            current_visibility = ContentVisibility.UNKNOWN

        # Check if we should update
        if not self.mapper.should_update_visibility(current_visibility, new_visibility):
            return False

        # Update visibility field (NEVER delete the row)
        # NOTE: We preserve the original body_text, do NOT overwrite it
        message.remote_visibility = new_visibility.value

        # Record when deletion was detected (only for non-visible states)
        if new_visibility != ContentVisibility.VISIBLE:
            message.remote_deleted_at = now

        return True

    def update_lead_post_visibility(
        self,
        lead_post: LeadPost,
        provider_post: ProviderPost,
    ) -> bool:
        """Update lead post visibility from provider post data.

        IMPORTANT: This method NEVER deletes the lead post row.
        It only updates remote_visibility and remote_deleted_at fields.
        Original title and body_text are preserved.

        Args:
            lead_post: The local LeadPost to update.
            provider_post: Provider post data with visibility info.

        Returns:
            True if visibility was updated, False if unchanged.
        """
        now = datetime.now(timezone.utc)

        # Map provider visibility to internal
        new_visibility = self.mapper.from_provider_visibility(
            provider_post.remote_visibility
        )

        # Get current visibility as enum
        try:
            current_visibility = ContentVisibility(lead_post.remote_visibility)
        except ValueError:
            current_visibility = ContentVisibility.UNKNOWN

        # Check if we should update
        if not self.mapper.should_update_visibility(current_visibility, new_visibility):
            return False

        # Update visibility field (NEVER delete the row)
        # NOTE: We preserve the original title and body_text, do NOT overwrite them
        lead_post.remote_visibility = new_visibility.value

        # Record when deletion was detected (only for non-visible states)
        if new_visibility != ContentVisibility.VISIBLE:
            lead_post.remote_deleted_at = now

        return True

    def update_profile_item_visibility(
        self,
        profile_item: ProfileItem,
        provider_item: ProviderProfileItem,
    ) -> bool:
        """Update profile item visibility from provider item data.

        IMPORTANT: This method NEVER deletes the profile item row.
        It only updates remote_visibility and remote_deleted_at fields.
        Original text_content is preserved.

        Args:
            profile_item: The local ProfileItem to update.
            provider_item: Provider profile item data with visibility info.

        Returns:
            True if visibility was updated, False if unchanged.
        """
        now = datetime.now(timezone.utc)

        # Map provider visibility to internal
        new_visibility = self.mapper.from_provider_visibility(
            provider_item.remote_visibility
        )

        # Get current visibility as enum
        try:
            current_visibility = ContentVisibility(profile_item.remote_visibility)
        except ValueError:
            current_visibility = ContentVisibility.UNKNOWN

        # Check if we should update
        if not self.mapper.should_update_visibility(current_visibility, new_visibility):
            return False

        # Update visibility field (NEVER delete the row)
        # NOTE: We preserve the original text_content, do NOT overwrite it
        profile_item.remote_visibility = new_visibility.value

        # Record when deletion was detected (only for non-visible states)
        if new_visibility != ContentVisibility.VISIBLE:
            profile_item.remote_deleted_at = now

        return True


# Export public interface
__all__ = ["SyncStatusUpdater"]
