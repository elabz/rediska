"""Leads service for managing saved posts/leads.

This service provides:
1. Saving posts as leads
2. Lead status management (new, saved, ignored, contacted, etc.)
3. Lead retrieval and listing
4. Author account handling

Usage:
    service = LeadsService(db=session)

    # Save a post as a lead
    lead = service.save_lead(
        provider_id="reddit",
        source_location="r/programming",
        external_post_id="abc123",
        post_url="https://reddit.com/...",
        title="Post title",
        body_text="Post content",
        author_username="username",
    )

    # Get a lead by ID
    lead = service.get_lead(lead_id)

    # List leads with filters
    leads = service.list_leads(status="saved", source_location="r/programming")
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from rediska_core.domain.models import ExternalAccount, LeadPost
from rediska_core.domain.services.external_listing import maybe_resolve_post_body
from rediska_core.domain.services.profile_item_utils import upsert_profile_item_from_post


# =============================================================================
# CONSTANTS
# =============================================================================


VALID_STATUSES = {"new", "saved", "ignored", "contact_queued", "contacted"}

# A lead is "active" for author-level dedupe unless the user ignored it or it
# was locally deleted. An ignored lead is a standing negative verdict: it is
# neither resurrected nor duplicated by new posts from the same author.
INACTIVE_STATUSES = {"ignored"}


# =============================================================================
# SERVICE
# =============================================================================


class LeadsService:
    """Service for managing leads (saved posts).

    Provides CRUD operations for lead posts and handles
    author account creation/linking.
    """

    def __init__(self, db: Session):
        """Initialize the leads service.

        Args:
            db: SQLAlchemy database session.
        """
        self.db = db

    # =========================================================================
    # SAVE LEAD
    # =========================================================================

    def save_lead(
        self,
        provider_id: str,
        source_location: str,
        external_post_id: str,
        post_url: str,
        title: Optional[str] = None,
        body_text: Optional[str] = None,
        author_username: Optional[str] = None,
        author_external_id: Optional[str] = None,
        post_created_at: Optional[datetime] = None,
    ) -> LeadPost:
        """Save a post as a lead.

        Creates a new lead_posts row, updates an existing one if the
        external_post_id already exists, or — when the author already has an
        active lead from a *different* post — attaches this post to that lead
        instead of creating a duplicate (at most one active lead per author).

        Args:
            provider_id: Provider ID (e.g., 'reddit').
            source_location: Source location (e.g., 'r/programming').
            external_post_id: Provider's post ID.
            post_url: URL to the post.
            title: Post title (optional).
            body_text: Post body text (optional).
            author_username: Author's username (optional).
            author_external_id: Author's external ID (optional).
            post_created_at: When the post was created (optional).

        Returns:
            The created or updated LeadPost.
        """
        # Link-only posts (e.g. weheartbdsm listings): substitute the listing's
        # About text as the body BEFORE persisting, so the profile_item and the
        # auto-analyze triggered right after saving always see real content.
        body_text = maybe_resolve_post_body(body_text, post_url)

        # Check if lead already exists
        existing = (
            self.db.query(LeadPost)
            .filter(
                LeadPost.provider_id == provider_id,
                LeadPost.external_post_id == external_post_id,
            )
            .first()
        )

        # Handle author account
        author_account_id = None
        if author_username:
            author_account_id = self._get_or_create_author_account(
                provider_id=provider_id,
                username=author_username,
                external_id=author_external_id,
            )

        attached = False

        if existing:
            # Update existing lead
            if title is not None:
                existing.title = title
            if body_text is not None:
                existing.body_text = body_text
            if author_account_id is not None:
                existing.author_account_id = author_account_id
            if post_created_at is not None:
                existing.post_created_at = post_created_at
            # Always set status to 'saved' when saving
            existing.status = "saved"
            self.db.flush()
            lead = existing
        elif author_account_id and (
            author_lead := self.get_active_lead_for_author(provider_id, author_account_id)
        ):
            # The author already has an active lead from a different post:
            # attach this post to it (as a profile_item, below) instead of
            # creating a sibling lead. The lead's own title/body/status stay
            # those of its primary post.
            author_lead.updated_at = datetime.utcnow()
            self.db.flush()
            lead = author_lead
            attached = True
        else:
            # Create new lead
            lead = LeadPost(
                provider_id=provider_id,
                source_location=source_location,
                external_post_id=external_post_id,
                post_url=post_url,
                title=title,
                body_text=body_text,
                author_account_id=author_account_id,
                post_created_at=post_created_at,
                status="saved",
                remote_visibility="unknown",
            )
            self.db.add(lead)
            self.db.flush()

        # Also save the post as a profile_item for the author so that
        # analysis always has at least this post even when the provider
        # API returns nothing (e.g., hidden NSFW profile).
        if author_account_id and (body_text or title):
            profile_item_id = upsert_profile_item_from_post(
                db=self.db,
                account_id=author_account_id,
                external_post_id=external_post_id,
                title=title,
                body_text=body_text,
                source_location=source_location,
                post_created_at=post_created_at,
            )
            # Attach as transient attribute for the response
            lead._profile_item_id = profile_item_id  # type: ignore[attr-defined]

        # Transient marker: the caller saved a post that joined an existing
        # lead rather than creating one (used by the API response + audit).
        lead._attached = attached  # type: ignore[attr-defined]

        return lead

    def get_active_lead_for_author(
        self,
        provider_id: str,
        account_id: int,
    ) -> Optional[LeadPost]:
        """Get the author's active lead, if any.

        Active means the lead is not `ignored` (a standing negative verdict)
        and not locally deleted. At most one active lead per author is the
        invariant this lookup supports; if several exist (historical
        duplicates, pending the merge task) the newest is returned.

        Args:
            provider_id: Provider ID.
            account_id: The author's external account ID.

        Returns:
            The active LeadPost or None if the author has none.
        """
        return (
            self.db.query(LeadPost)
            .filter(
                LeadPost.provider_id == provider_id,
                LeadPost.author_account_id == account_id,
                LeadPost.status.notin_(INACTIVE_STATUSES),
                LeadPost.deleted_at.is_(None),
            )
            .order_by(LeadPost.created_at.desc())
            .first()
        )

    def _get_or_create_author_account(
        self,
        provider_id: str,
        username: str,
        external_id: Optional[str] = None,
    ) -> int:
        """Get or create an external account for the author.

        Args:
            provider_id: Provider ID.
            username: Author's username.
            external_id: Author's external ID (optional).

        Returns:
            The account ID.
        """
        # Try to find existing account
        account = (
            self.db.query(ExternalAccount)
            .filter(
                ExternalAccount.provider_id == provider_id,
                ExternalAccount.external_username == username,
            )
            .first()
        )

        if account:
            # Update external_id if provided and not set
            if external_id and not account.external_user_id:
                account.external_user_id = external_id
                self.db.flush()
            return account.id

        # Create new account
        account = ExternalAccount(
            provider_id=provider_id,
            external_username=username,
            external_user_id=external_id,
            remote_status="unknown",
        )
        self.db.add(account)
        self.db.flush()
        return account.id

    # =========================================================================
    # GET LEAD
    # =========================================================================

    def get_lead(self, lead_id: int) -> Optional[LeadPost]:
        """Get a lead by ID.

        Args:
            lead_id: The lead ID.

        Returns:
            The LeadPost or None if not found.
        """
        return self.db.query(LeadPost).filter(LeadPost.id == lead_id).first()

    def get_lead_by_external_id(
        self,
        provider_id: str,
        external_post_id: str,
    ) -> Optional[LeadPost]:
        """Get a lead by provider ID and external post ID.

        Args:
            provider_id: Provider ID.
            external_post_id: External post ID.

        Returns:
            The LeadPost or None if not found.
        """
        return (
            self.db.query(LeadPost)
            .filter(
                LeadPost.provider_id == provider_id,
                LeadPost.external_post_id == external_post_id,
            )
            .first()
        )

    # =========================================================================
    # LIST LEADS
    # =========================================================================

    def _build_leads_query(
        self,
        provider_id: Optional[str] = None,
        source_location: Optional[str] = None,
        status: Optional[str] = None,
        lead_source: Optional[str] = None,
        search: Optional[str] = None,
    ):
        """Build a query for leads with filters.

        Args:
            provider_id: Filter by provider (optional).
            source_location: Filter by source location (optional).
            status: Filter by status (optional).
            lead_source: Filter by lead source ('manual', 'scout_watch') (optional).
            search: Search term for title, body, source_location (optional).

        Returns:
            SQLAlchemy query object.
        """
        from sqlalchemy import or_

        query = self.db.query(LeadPost)

        if provider_id:
            query = query.filter(LeadPost.provider_id == provider_id)

        if source_location:
            query = query.filter(LeadPost.source_location == source_location)

        if status:
            query = query.filter(LeadPost.status == status)

        if lead_source:
            query = query.filter(LeadPost.lead_source == lead_source)

        if search:
            search_term = f"%{search}%"
            # Join with ExternalAccount to search by author username
            query = query.outerjoin(
                ExternalAccount,
                LeadPost.author_account_id == ExternalAccount.id,
            )
            query = query.filter(
                or_(
                    LeadPost.title.ilike(search_term),
                    LeadPost.body_text.ilike(search_term),
                    LeadPost.source_location.ilike(search_term),
                    ExternalAccount.external_username.ilike(search_term),
                )
            )

        return query

    def list_leads(
        self,
        provider_id: Optional[str] = None,
        source_location: Optional[str] = None,
        status: Optional[str] = None,
        lead_source: Optional[str] = None,
        search: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[LeadPost]:
        """List leads with optional filters.

        Args:
            provider_id: Filter by provider (optional).
            source_location: Filter by source location (optional).
            status: Filter by status (optional).
            lead_source: Filter by lead source ('manual', 'scout_watch') (optional).
            search: Search term for title, body, author, source_location (optional).
            offset: Pagination offset.
            limit: Maximum results.

        Returns:
            List of LeadPost objects.
        """
        query = self._build_leads_query(
            provider_id=provider_id,
            source_location=source_location,
            status=status,
            lead_source=lead_source,
            search=search,
        )

        # Order by created_at descending (newest first)
        query = query.order_by(LeadPost.created_at.desc())

        return query.offset(offset).limit(limit).all()

    def count_leads(
        self,
        provider_id: Optional[str] = None,
        source_location: Optional[str] = None,
        status: Optional[str] = None,
        lead_source: Optional[str] = None,
        search: Optional[str] = None,
    ) -> int:
        """Count leads with optional filters.

        Args:
            provider_id: Filter by provider (optional).
            source_location: Filter by source location (optional).
            status: Filter by status (optional).
            lead_source: Filter by lead source ('manual', 'scout_watch') (optional).
            search: Search term for title, body, author, source_location (optional).

        Returns:
            Total count of matching leads.
        """
        query = self._build_leads_query(
            provider_id=provider_id,
            source_location=source_location,
            status=status,
            lead_source=lead_source,
            search=search,
        )

        return query.count()

    # =========================================================================
    # HISTORICAL DUPLICATE MERGE
    # =========================================================================

    def merge_duplicate_author_leads(self, dry_run: bool = True) -> dict:
        """Merge pre-existing duplicate-author leads onto one survivor each.

        Groups active leads by `(provider_id, author_account_id)`; where a group
        has more than one lead, the newest post wins. Analysis history and
        scout-post linkage are repointed to the survivor and the losers are
        soft-deleted — never hard-deleted, per the data-preservation principle.

        Args:
            dry_run: When True (the default), report the plan without mutating.

        Returns:
            A report dict with the merge groups and totals.
        """
        from rediska_core.domain.models import AuditLog, LeadAnalysis, ScoutWatchPost

        candidates = (
            self.db.query(LeadPost)
            .filter(
                LeadPost.author_account_id.isnot(None),
                LeadPost.status.notin_(INACTIVE_STATUSES),
                LeadPost.deleted_at.is_(None),
            )
            .all()
        )

        by_author: dict[tuple[str, int], list[LeadPost]] = {}
        for lead in candidates:
            if lead.author_account_id is None:
                continue
            by_author.setdefault((lead.provider_id, lead.author_account_id), []).append(lead)

        now = datetime.utcnow()
        groups: list[dict] = []

        for (provider_id, account_id), leads in by_author.items():
            if len(leads) < 2:
                continue

            # Newest post wins; fall back to newest row for undated posts.
            ordered = sorted(
                leads,
                key=lambda lead: (
                    lead.post_created_at or datetime.min,
                    lead.created_at or datetime.min,
                    lead.id,
                ),
                reverse=True,
            )
            survivor, losers = ordered[0], ordered[1:]
            loser_ids = [lead.id for lead in losers]

            group = {
                "provider_id": provider_id,
                "author_account_id": account_id,
                "survivor_lead_id": survivor.id,
                "merged_lead_ids": loser_ids,
            }
            groups.append(group)

            if dry_run:
                continue

            self.db.query(LeadAnalysis).filter(
                LeadAnalysis.lead_id.in_(loser_ids)
            ).update({LeadAnalysis.lead_id: survivor.id}, synchronize_session=False)

            self.db.query(ScoutWatchPost).filter(
                ScoutWatchPost.lead_id.in_(loser_ids)
            ).update({ScoutWatchPost.lead_id: survivor.id}, synchronize_session=False)

            for loser in losers:
                loser.deleted_at = now

            survivor.updated_at = now

            self.db.add(
                AuditLog(
                    ts=now,
                    actor="system",
                    action_type="lead.merge_duplicates",
                    result="ok",
                    provider_id=provider_id,
                    entity_type="lead_post",
                    entity_id=survivor.id,
                    request_json={"author_account_id": account_id},
                    response_json={"merged_lead_ids": loser_ids},
                )
            )

        if not dry_run:
            self.db.flush()

        return {
            "dry_run": dry_run,
            "groups": groups,
            "duplicate_groups": len(groups),
            "leads_merged": sum(len(group["merged_lead_ids"]) for group in groups),
        }

    # =========================================================================
    # UPDATE STATUS
    # =========================================================================

    def update_status(self, lead_id: int, status: str) -> Optional[LeadPost]:
        """Update a lead's status.

        Args:
            lead_id: The lead ID.
            status: New status value.

        Returns:
            The updated LeadPost or None if not found.

        Raises:
            ValueError: If status is invalid.
        """
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}. Must be one of {VALID_STATUSES}")

        lead = self.get_lead(lead_id)
        if not lead:
            return None

        lead.status = status
        self.db.flush()
        return lead


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "LeadsService",
    "VALID_STATUSES",
    "INACTIVE_STATUSES",
]
