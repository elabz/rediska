"""Directory service for listing accounts by workflow state.

This service provides:
1. Listing accounts by analysis state (analyzed)
2. Listing accounts by contact state (contacted)
3. Listing accounts by engagement state (engaged)
4. Filtering by provider
5. Pagination support
6. Including related data (profile snapshots)

Usage:
    service = DirectoryService(db=session)

    # List analyzed accounts
    analyzed = service.list_analyzed(provider_id="reddit", limit=20)

    # List contacted accounts
    contacted = service.list_contacted()

    # List engaged accounts
    engaged = service.list_engaged()

    # Get counts
    count = service.count_analyzed()
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from rediska_core.domain.models import ExternalAccount, ProfileSnapshot


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class DirectoryEntry:
    """Entry in a directory listing.

    Represents an external account with relevant workflow data.
    """

    id: int
    provider_id: str
    external_username: str
    external_user_id: Optional[str]
    remote_status: str

    # State fields
    analysis_state: str
    contact_state: str
    engagement_state: str

    # Timestamps
    first_analyzed_at: Optional[datetime]
    first_contacted_at: Optional[datetime]
    first_inbound_after_contact_at: Optional[datetime]
    created_at: datetime

    # Related data
    latest_summary: Optional[str] = None
    lead_count: int = 0


# =============================================================================
# SERVICE
# =============================================================================


class DirectoryService:
    """Service for listing accounts by workflow state.

    Provides directory views for:
    - Analyzed: Accounts that have been analyzed
    - Contacted: Accounts that have been contacted
    - Engaged: Accounts that have responded after contact
    """

    def __init__(self, db: Session):
        """Initialize the directory service.

        Args:
            db: SQLAlchemy database session.
        """
        self.db = db

    # =========================================================================
    # ANALYZED DIRECTORY
    # =========================================================================

    def list_analyzed(
        self,
        provider_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[DirectoryEntry]:
        """List accounts that have been analyzed.

        Args:
            provider_id: Optional filter by provider.
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            List of DirectoryEntry objects.
        """
        query = self.db.query(ExternalAccount).filter(
            ExternalAccount.analysis_state == "analyzed",
            ExternalAccount.deleted_at.is_(None),
        )

        if provider_id:
            query = query.filter(ExternalAccount.provider_id == provider_id)

        # Sort by first_analyzed_at descending (most recently analyzed first)
        query = query.order_by(desc(ExternalAccount.first_analyzed_at))

        query = query.offset(offset).limit(limit)

        accounts = query.all()
        return [self._to_directory_entry(account) for account in accounts]

    def count_analyzed(self, provider_id: Optional[str] = None) -> int:
        """Count accounts that have been analyzed.

        Args:
            provider_id: Optional filter by provider.

        Returns:
            Count of analyzed accounts.
        """
        query = self.db.query(func.count(ExternalAccount.id)).filter(
            ExternalAccount.analysis_state == "analyzed",
            ExternalAccount.deleted_at.is_(None),
        )

        if provider_id:
            query = query.filter(ExternalAccount.provider_id == provider_id)

        return query.scalar() or 0

    # =========================================================================
    # CONTACTED DIRECTORY
    # =========================================================================

    def list_contacted(
        self,
        provider_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[DirectoryEntry]:
        """List accounts that have been contacted.

        Args:
            provider_id: Optional filter by provider.
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            List of DirectoryEntry objects.
        """
        query = self.db.query(ExternalAccount).filter(
            ExternalAccount.contact_state == "contacted",
            ExternalAccount.deleted_at.is_(None),
        )

        if provider_id:
            query = query.filter(ExternalAccount.provider_id == provider_id)

        # Sort by first_contacted_at descending (most recently contacted first)
        query = query.order_by(desc(ExternalAccount.first_contacted_at))

        query = query.offset(offset).limit(limit)

        accounts = query.all()
        return [self._to_directory_entry(account) for account in accounts]

    def count_contacted(self, provider_id: Optional[str] = None) -> int:
        """Count accounts that have been contacted.

        Args:
            provider_id: Optional filter by provider.

        Returns:
            Count of contacted accounts.
        """
        query = self.db.query(func.count(ExternalAccount.id)).filter(
            ExternalAccount.contact_state == "contacted",
            ExternalAccount.deleted_at.is_(None),
        )

        if provider_id:
            query = query.filter(ExternalAccount.provider_id == provider_id)

        return query.scalar() or 0

    # =========================================================================
    # ENGAGED DIRECTORY
    # =========================================================================

    def list_engaged(
        self,
        provider_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[DirectoryEntry]:
        """List accounts that have engaged (responded after contact).

        Args:
            provider_id: Optional filter by provider.
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            List of DirectoryEntry objects.
        """
        query = self.db.query(ExternalAccount).filter(
            ExternalAccount.engagement_state == "engaged",
            ExternalAccount.deleted_at.is_(None),
        )

        if provider_id:
            query = query.filter(ExternalAccount.provider_id == provider_id)

        # Sort by first_inbound_after_contact_at descending
        query = query.order_by(desc(ExternalAccount.first_inbound_after_contact_at))

        query = query.offset(offset).limit(limit)

        accounts = query.all()
        return [self._to_directory_entry(account) for account in accounts]

    def count_engaged(self, provider_id: Optional[str] = None) -> int:
        """Count accounts that have engaged.

        Args:
            provider_id: Optional filter by provider.

        Returns:
            Count of engaged accounts.
        """
        query = self.db.query(func.count(ExternalAccount.id)).filter(
            ExternalAccount.engagement_state == "engaged",
            ExternalAccount.deleted_at.is_(None),
        )

        if provider_id:
            query = query.filter(ExternalAccount.provider_id == provider_id)

        return query.scalar() or 0

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _to_directory_entry(self, account: ExternalAccount) -> DirectoryEntry:
        """Convert an ExternalAccount to a DirectoryEntry.

        Args:
            account: The external account.

        Returns:
            DirectoryEntry with account data and related info.
        """
        # Get latest profile snapshot summary
        latest_summary = None
        latest_snapshot = (
            self.db.query(ProfileSnapshot)
            .filter(ProfileSnapshot.account_id == account.id)
            .order_by(desc(ProfileSnapshot.fetched_at))
            .first()
        )
        if latest_snapshot:
            latest_summary = latest_snapshot.summary_text

        # Count lead posts
        lead_count = len(account.lead_posts) if account.lead_posts else 0

        return DirectoryEntry(
            id=account.id,
            provider_id=account.provider_id,
            external_username=account.external_username,
            external_user_id=account.external_user_id,
            remote_status=account.remote_status,
            analysis_state=account.analysis_state,
            contact_state=account.contact_state,
            engagement_state=account.engagement_state,
            first_analyzed_at=account.first_analyzed_at,
            first_contacted_at=account.first_contacted_at,
            first_inbound_after_contact_at=account.first_inbound_after_contact_at,
            created_at=account.created_at,
            latest_summary=latest_summary,
            lead_count=lead_count,
        )


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "DirectoryService",
    "DirectoryEntry",
]
