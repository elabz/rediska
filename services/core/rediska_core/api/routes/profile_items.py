"""Profile items API routes.

Provides endpoints for:
- POST /profile-items/ingest-browse-posts - Batch ingest browse/scout posts for known authors
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from rediska_core.api.deps import CurrentUser, get_db
from rediska_core.api.schemas.profile_items import (
    IngestBrowsePostsRequest,
    IngestBrowsePostsResponse,
)
from rediska_core.domain.models import ExternalAccount, ProfileItem
from rediska_core.domain.services.profile_item_utils import upsert_profile_item_from_post

router = APIRouter(prefix="/profile-items", tags=["profile-items"])
logger = logging.getLogger(__name__)


@router.post(
    "/ingest-browse-posts",
    response_model=IngestBrowsePostsResponse,
    summary="Ingest browse/scout posts for known authors",
    description="For each post, checks if the author already has an ExternalAccount. "
    "If so, upserts a profile_item for the post. Posts from unknown authors are skipped.",
)
async def ingest_browse_posts(
    request: IngestBrowsePostsRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> IngestBrowsePostsResponse:
    """Batch ingest posts from browse/scout results.

    Only creates profile_items for authors who already exist in
    external_accounts (known users). Unknown authors are skipped.
    """
    if not request.posts:
        return IngestBrowsePostsResponse(
            ingested_count=0,
            new_items_count=0,
            known_authors=[],
        )

    # Collect unique (provider_id, author_username) pairs
    author_keys: set[tuple[str, str]] = set()
    for post in request.posts:
        author_keys.add((post.provider_id, post.author_username))

    # Batch-lookup existing ExternalAccounts
    # Build a map of (provider_id, username) → account_id
    account_map: dict[tuple[str, str], int] = {}
    if author_keys:
        accounts = (
            db.query(ExternalAccount.provider_id, ExternalAccount.external_username, ExternalAccount.id)
            .filter(
                tuple_(ExternalAccount.provider_id, ExternalAccount.external_username).in_(
                    list(author_keys)
                )
            )
            .all()
        )
        for provider_id, username, account_id in accounts:
            account_map[(provider_id, username)] = account_id

    known_authors: set[str] = set()
    ingested_count = 0
    new_items_count = 0

    for post in request.posts:
        key = (post.provider_id, post.author_username)
        account_id = account_map.get(key)
        if not account_id:
            continue

        known_authors.add(post.author_username)

        # Check if this item already exists (to track new vs updated)
        existing = (
            db.query(ProfileItem.id)
            .filter(
                ProfileItem.account_id == account_id,
                ProfileItem.item_type == "post",
                ProfileItem.external_item_id == post.external_post_id,
            )
            .first()
        )
        is_new = existing is None

        item_id = upsert_profile_item_from_post(
            db=db,
            account_id=account_id,
            external_post_id=post.external_post_id,
            title=post.title,
            body_text=post.body_text,
            source_location=post.source_location,
            post_created_at=post.post_created_at,
        )

        if item_id:
            ingested_count += 1
            if is_new:
                new_items_count += 1

    logger.info(
        "Ingested %d posts (%d new) for %d known authors",
        ingested_count, new_items_count, len(known_authors),
    )

    return IngestBrowsePostsResponse(
        ingested_count=ingested_count,
        new_items_count=new_items_count,
        known_authors=sorted(known_authors),
    )
