"""Analysis service for lead analysis pipeline.

This service orchestrates the lead analysis workflow:
1. Fetches author profile from provider
2. Fetches author items (posts, comments) from provider
3. Creates/updates ProfileSnapshot and ProfileItem records
4. Indexes content in Elasticsearch
5. Generates embeddings for content
6. Updates ExternalAccount.analysis_state

Usage:
    service = AnalysisService(
        db=session,
        provider_adapter=adapter,
        indexing_service=indexing,
        embedding_service=embedding,
    )

    result = await service.analyze_lead(lead_id)
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    ExternalAccount,
    LeadPost,
    ProfileItem,
    ProfileSnapshot,
)
from rediska_core.providers.base import (
    PaginatedResult,
    ProfileItemType,
    ProviderAdapter,
    ProviderProfile,
    ProviderProfileItem,
)


# =============================================================================
# EXCEPTIONS
# =============================================================================


class AnalysisError(Exception):
    """Exception raised for analysis errors."""

    pass


# =============================================================================
# RESULT DATACLASS
# =============================================================================


@dataclass
class AnalysisResult:
    """Result of lead analysis."""

    lead_id: int
    account_id: int
    profile_snapshot_id: int
    profile_items_count: int
    indexed_count: int
    embedded_count: int
    success: bool
    error: Optional[str] = None


# =============================================================================
# SERVICE
# =============================================================================


class AnalysisService:
    """Service for analyzing leads and their authors.

    Orchestrates the full analysis pipeline including:
    - Fetching author profile and content from provider
    - Storing profile snapshots and items
    - Indexing content for search
    - Generating embeddings for similarity
    """

    def __init__(
        self,
        db: Session,
        provider_adapter: Optional[ProviderAdapter] = None,
        indexing_service: Optional[Any] = None,
        embedding_service: Optional[Any] = None,
    ):
        """Initialize the analysis service.

        Args:
            db: SQLAlchemy database session.
            provider_adapter: Provider adapter for API calls.
            indexing_service: Service for indexing content.
            embedding_service: Service for generating embeddings.
        """
        self.db = db
        self.provider_adapter = provider_adapter
        self.indexing_service = indexing_service
        self.embedding_service = embedding_service

    # =========================================================================
    # MAIN ANALYSIS METHOD
    # =========================================================================

    async def analyze_lead(self, lead_id: int) -> AnalysisResult:
        """Analyze a lead and its author.

        Fetches the author's profile and content, stores them locally,
        indexes for search, and generates embeddings.

        Args:
            lead_id: The lead post ID to analyze.

        Returns:
            AnalysisResult with analysis details.

        Raises:
            AnalysisError: If analysis fails.
        """
        # Get lead
        lead = self.db.query(LeadPost).filter(LeadPost.id == lead_id).first()
        if not lead:
            raise AnalysisError(f"Lead not found: {lead_id}")

        # Check lead has author
        if not lead.author_account_id:
            raise AnalysisError(f"Lead has no author: {lead_id}")

        # Get author account
        account = (
            self.db.query(ExternalAccount)
            .filter(ExternalAccount.id == lead.author_account_id)
            .first()
        )

        try:
            # Step 1: Fetch author profile from provider
            profile = await self._fetch_profile(account)
            if not profile:
                raise AnalysisError(
                    f"Failed to fetch profile for: {account.external_username}"
                )

            # Step 2: Create profile snapshot
            snapshot = self._create_profile_snapshot(account, profile)

            # Step 3: Fetch author items from provider (with pagination)
            items = await self._fetch_profile_items(account)

            # Step 4: Store profile items
            stored_items = self._store_profile_items(account, items)

            # Step 5: Index content
            indexed_count = self._index_content(account, snapshot, stored_items)

            # Step 6: Generate embeddings
            embedded_count = self._generate_embeddings(account, snapshot, stored_items)

            # Step 7: Update account analysis state
            self._update_analysis_state(account)

            return AnalysisResult(
                lead_id=lead_id,
                account_id=account.id,
                profile_snapshot_id=snapshot.id,
                profile_items_count=len(stored_items),
                indexed_count=indexed_count,
                embedded_count=embedded_count,
                success=True,
            )

        except AnalysisError:
            raise
        except Exception as e:
            raise AnalysisError(f"Analysis failed: {e}")

    # =========================================================================
    # PROFILE FETCHING
    # =========================================================================

    async def _fetch_profile(
        self, account: ExternalAccount
    ) -> Optional[ProviderProfile]:
        """Fetch the user's profile from the provider.

        Args:
            account: The external account to fetch.

        Returns:
            ProviderProfile if found, None otherwise.
        """
        if not self.provider_adapter:
            self.logger.error("Provider adapter not initialized")
            return None

        return await self.provider_adapter.fetch_profile(account.external_username)

    async def _fetch_profile_items(
        self, account: ExternalAccount
    ) -> list[ProviderProfileItem]:
        """Fetch all profile items with pagination.

        Args:
            account: The external account to fetch items for.

        Returns:
            List of all profile items across pages.
        """
        if not self.provider_adapter:
            return []

        all_items: list[ProviderProfileItem] = []
        cursor: Optional[str] = None

        while True:
            result: PaginatedResult[ProviderProfileItem] = (
                await self.provider_adapter.fetch_profile_items(
                    user_id=account.external_username,
                    cursor=cursor,
                    limit=100,
                )
            )

            all_items.extend(result.items)

            if not result.has_more or not result.next_cursor:
                break

            cursor = result.next_cursor

        return all_items

    # =========================================================================
    # PROFILE SNAPSHOT
    # =========================================================================

    def _create_profile_snapshot(
        self, account: ExternalAccount, profile: ProviderProfile
    ) -> ProfileSnapshot:
        """Create a profile snapshot for the account.

        Args:
            account: The external account.
            profile: The provider profile data.

        Returns:
            The created ProfileSnapshot.
        """
        snapshot = ProfileSnapshot(
            account_id=account.id,
            fetched_at=datetime.now(timezone.utc),
            signals_json={
                "username": profile.username,
                "display_name": profile.display_name,
                "bio": profile.bio,
                "karma": profile.karma,
                "created_at": (
                    profile.created_at.isoformat() if profile.created_at else None
                ),
                "is_verified": profile.is_verified,
                "is_suspended": profile.is_suspended,
            },
        )

        self.db.add(snapshot)
        self.db.commit()
        self.db.refresh(snapshot)

        return snapshot

    # =========================================================================
    # PROFILE ITEMS STORAGE
    # =========================================================================

    def _store_profile_items(
        self, account: ExternalAccount, items: list[ProviderProfileItem]
    ) -> list[ProfileItem]:
        """Store profile items, upserting existing ones.

        Args:
            account: The external account.
            items: List of provider profile items.

        Returns:
            List of stored ProfileItem records.
        """
        stored: list[ProfileItem] = []

        for item in items:
            # Check if item already exists
            existing = (
                self.db.query(ProfileItem)
                .filter(
                    ProfileItem.account_id == account.id,
                    ProfileItem.external_item_id == item.external_id,
                )
                .first()
            )

            if existing:
                # Update existing item
                existing.item_type = item.item_type.value
                existing.text_content = item.body_text
                existing.item_created_at = item.created_at
                stored.append(existing)
            else:
                # Create new item
                new_item = ProfileItem(
                    account_id=account.id,
                    item_type=item.item_type.value,
                    external_item_id=item.external_id,
                    text_content=item.body_text,
                    item_created_at=item.created_at,
                )
                self.db.add(new_item)
                stored.append(new_item)

        self.db.commit()

        # Refresh all items to get IDs
        for item in stored:
            self.db.refresh(item)

        return stored

    # =========================================================================
    # INDEXING
    # =========================================================================

    def _index_content(
        self,
        account: ExternalAccount,
        snapshot: ProfileSnapshot,
        items: list[ProfileItem],
    ) -> int:
        """Index content in Elasticsearch.

        Args:
            account: The external account.
            snapshot: The profile snapshot.
            items: List of profile items.

        Returns:
            Number of documents indexed.
        """
        if not self.indexing_service:
            return 0

        count = 0

        # Index profile snapshot
        if self.indexing_service.upsert_content("profile_snapshot", snapshot.id):
            count += 1

        # Index profile items
        for item in items:
            if self.indexing_service.upsert_content("profile_item", item.id):
                count += 1

        return count

    # =========================================================================
    # EMBEDDINGS
    # =========================================================================

    def _generate_embeddings(
        self,
        account: ExternalAccount,
        snapshot: ProfileSnapshot,
        items: list[ProfileItem],
    ) -> int:
        """Generate embeddings for content.

        Args:
            account: The external account.
            snapshot: The profile snapshot.
            items: List of profile items.

        Returns:
            Number of embeddings generated.
        """
        if not self.embedding_service:
            return 0

        count = 0

        # Generate embeddings for profile items with text content
        for item in items:
            if item.text_content:
                result = self.embedding_service.generate_embedding(
                    doc_type="profile_item",
                    entity_id=item.id,
                    text=item.text_content,
                )
                if result.get("success"):
                    count += 1

        return count

    # =========================================================================
    # ANALYSIS STATE UPDATE
    # =========================================================================

    def _update_analysis_state(self, account: ExternalAccount) -> None:
        """Update the account's analysis state.

        Args:
            account: The external account to update.
        """
        account.analysis_state = "analyzed"

        # Only set first_analyzed_at if not already set
        if not account.first_analyzed_at:
            account.first_analyzed_at = datetime.now(timezone.utc)

        account.last_fetched_at = datetime.now(timezone.utc)

        self.db.commit()


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "AnalysisService",
    "AnalysisError",
    "AnalysisResult",
]
