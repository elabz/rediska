"""Shared utilities for creating/upserting profile items from external post data.

Used by LeadsService (save_lead) and ScoutWatchService (record_post)
to persist browse/scout post content as profile_items, ensuring
analysis always has at least the post that surfaced the user.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from rediska_core.domain.models import ProfileItem

logger = logging.getLogger(__name__)


def upsert_profile_item_from_post(
    db: Session,
    account_id: int,
    external_post_id: str,
    title: Optional[str] = None,
    body_text: Optional[str] = None,
    source_location: Optional[str] = None,
    post_created_at: Optional[datetime] = None,
) -> Optional[int]:
    """Upsert a profile_item of type 'post' from browse/scout/lead post data.

    Combines title + body into text_content. Deduplicates by the
    (account_id, item_type='post', external_item_id) unique constraint.

    Args:
        db: SQLAlchemy session.
        account_id: The ExternalAccount ID for the post author.
        external_post_id: Provider's post ID (e.g., Reddit post ID).
        title: Post title (optional).
        body_text: Post body text (optional).
        source_location: Subreddit / channel name (optional).
        post_created_at: When the post was created on the provider (optional).

    Returns:
        The profile_item ID, or None if there was no content to save.
    """
    if not body_text and not title:
        return None

    # Combine title + body for text_content
    text_parts = []
    if title:
        text_parts.append(title)
    if body_text:
        text_parts.append(body_text)
    text_content = "\n\n".join(text_parts)

    # Clean source_location (strip r/ prefix if present)
    clean_location = source_location
    if clean_location and clean_location.startswith("r/"):
        clean_location = clean_location[2:]

    # Upsert by unique key (account_id, item_type='post', external_item_id)
    existing = (
        db.query(ProfileItem)
        .filter(
            ProfileItem.account_id == account_id,
            ProfileItem.item_type == "post",
            ProfileItem.external_item_id == external_post_id,
        )
        .first()
    )

    if existing:
        # Update with newer/richer data
        existing.text_content = text_content
        if post_created_at:
            existing.item_created_at = post_created_at
        if clean_location:
            existing.subreddit = clean_location
        if title:
            existing.link_title = title[:512]
        # Mark visible since we just saw it in search results
        existing.remote_visibility = "visible"
        db.flush()
        logger.debug(
            "Updated profile_item %d for account %d, post %s",
            existing.id, account_id, external_post_id,
        )
        return existing.id

    item = ProfileItem(
        account_id=account_id,
        item_type="post",
        external_item_id=external_post_id,
        text_content=text_content,
        item_created_at=post_created_at,
        subreddit=clean_location,
        link_title=title[:512] if title else None,
        remote_visibility="visible",
    )
    db.add(item)
    db.flush()
    logger.debug(
        "Created profile_item %d for account %d, post %s",
        item.id, account_id, external_post_id,
    )
    return item.id
