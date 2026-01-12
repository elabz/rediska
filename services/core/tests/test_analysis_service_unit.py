"""Unit tests for AnalysisService.

Tests the lead analysis pipeline which:
1. Fetches author profile from provider
2. Fetches author items (posts, comments) from provider
3. Creates/updates ProfileSnapshot and ProfileItem records
4. Indexes content in Elasticsearch
5. Generates embeddings for content
6. Updates ExternalAccount.analysis_state
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    ExternalAccount,
    LeadPost,
    ProfileItem,
    ProfileSnapshot,
    Provider,
)
from rediska_core.domain.services.analysis import (
    AnalysisError,
    AnalysisResult,
    AnalysisService,
)
from rediska_core.providers.base import (
    PaginatedResult,
    ProfileItemType,
    ProviderProfile,
    ProviderProfileItem,
)


# =============================================================================
# FIXTURES
# =============================================================================


# Note: db_session fixture comes from conftest.py


@pytest.fixture
def mock_provider_adapter():
    """Create a mock provider adapter."""
    adapter = AsyncMock()
    adapter.provider_id = "reddit"
    return adapter


@pytest.fixture
def mock_indexing_service():
    """Create a mock indexing service."""
    service = MagicMock()
    service.upsert_content.return_value = True
    return service


@pytest.fixture
def mock_embedding_service():
    """Create a mock embedding service."""
    service = MagicMock()
    service.generate_embedding.return_value = {"success": True, "status": "embedded"}
    return service


@pytest.fixture
def setup_provider(db_session):
    """Set up provider for tests."""
    provider = Provider(provider_id="reddit", display_name="Reddit")
    db_session.add(provider)
    db_session.flush()
    return provider


@pytest.fixture
def setup_account(db_session, setup_provider):
    """Set up external account for tests."""
    account = ExternalAccount(
        provider_id="reddit",
        external_username="test_author",
        external_user_id="t2_abc123",
        remote_status="active",
        analysis_state="not_analyzed",
    )
    db_session.add(account)
    db_session.flush()
    return account


@pytest.fixture
def setup_lead(db_session, setup_provider, setup_account):
    """Set up a lead post for tests."""
    lead = LeadPost(
        provider_id="reddit",
        source_location="r/programming",
        external_post_id="post123",
        post_url="https://reddit.com/r/programming/comments/post123",
        author_account_id=setup_account.id,
        title="Test Post",
        body_text="This is a test post content.",
        status="saved",
    )
    db_session.add(lead)
    db_session.flush()
    return lead


@pytest.fixture
def sample_profile():
    """Sample provider profile data."""
    return ProviderProfile(
        external_id="t2_abc123",
        username="test_author",
        display_name="Test Author",
        bio="I am a test user for testing purposes.",
        created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        karma=1000,
        is_verified=False,
        is_suspended=False,
        raw_data={"link_karma": 500, "comment_karma": 500},
    )


@pytest.fixture
def sample_profile_items():
    """Sample provider profile items."""
    return [
        ProviderProfileItem(
            external_id="t3_item1",
            item_type=ProfileItemType.POST,
            author_id="t2_abc123",
            title="My First Post",
            body_text="This is my first post content.",
            created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
            url="https://reddit.com/r/test/comments/item1",
            score=50,
            raw_data={},
        ),
        ProviderProfileItem(
            external_id="t1_item2",
            item_type=ProfileItemType.COMMENT,
            author_id="t2_abc123",
            title=None,
            body_text="This is my comment on a post.",
            created_at=datetime(2024, 1, 20, tzinfo=timezone.utc),
            url="https://reddit.com/r/test/comments/abc/comment/item2",
            score=10,
            raw_data={},
        ),
    ]


# =============================================================================
# ANALYZE LEAD TESTS
# =============================================================================


class TestAnalyzeLead:
    """Tests for analyze_lead method."""

    @pytest.mark.asyncio
    async def test_analyze_lead_fetches_profile(
        self,
        db_session,
        setup_lead,
        setup_account,
        mock_provider_adapter,
        mock_indexing_service,
        mock_embedding_service,
        sample_profile,
        sample_profile_items,
    ):
        """analyze_lead should fetch author profile from provider."""
        mock_provider_adapter.fetch_profile.return_value = sample_profile
        mock_provider_adapter.fetch_profile_items.return_value = PaginatedResult(
            items=sample_profile_items,
            next_cursor=None,
            has_more=False,
        )

        service = AnalysisService(
            db=db_session,
            provider_adapter=mock_provider_adapter,
            indexing_service=mock_indexing_service,
            embedding_service=mock_embedding_service,
        )

        result = await service.analyze_lead(setup_lead.id)

        mock_provider_adapter.fetch_profile.assert_called_once_with(
            setup_account.external_username
        )

    @pytest.mark.asyncio
    async def test_analyze_lead_fetches_profile_items(
        self,
        db_session,
        setup_lead,
        setup_account,
        mock_provider_adapter,
        mock_indexing_service,
        mock_embedding_service,
        sample_profile,
        sample_profile_items,
    ):
        """analyze_lead should fetch author items from provider."""
        mock_provider_adapter.fetch_profile.return_value = sample_profile
        mock_provider_adapter.fetch_profile_items.return_value = PaginatedResult(
            items=sample_profile_items,
            next_cursor=None,
            has_more=False,
        )

        service = AnalysisService(
            db=db_session,
            provider_adapter=mock_provider_adapter,
            indexing_service=mock_indexing_service,
            embedding_service=mock_embedding_service,
        )

        result = await service.analyze_lead(setup_lead.id)

        mock_provider_adapter.fetch_profile_items.assert_called()

    @pytest.mark.asyncio
    async def test_analyze_lead_creates_profile_snapshot(
        self,
        db_session,
        setup_lead,
        setup_account,
        mock_provider_adapter,
        mock_indexing_service,
        mock_embedding_service,
        sample_profile,
        sample_profile_items,
    ):
        """analyze_lead should create a ProfileSnapshot."""
        mock_provider_adapter.fetch_profile.return_value = sample_profile
        mock_provider_adapter.fetch_profile_items.return_value = PaginatedResult(
            items=sample_profile_items,
            next_cursor=None,
            has_more=False,
        )

        service = AnalysisService(
            db=db_session,
            provider_adapter=mock_provider_adapter,
            indexing_service=mock_indexing_service,
            embedding_service=mock_embedding_service,
        )

        result = await service.analyze_lead(setup_lead.id)

        # Check that a profile snapshot was created
        snapshot = (
            db_session.query(ProfileSnapshot)
            .filter(ProfileSnapshot.account_id == setup_account.id)
            .first()
        )
        assert snapshot is not None
        assert snapshot.fetched_at is not None

    @pytest.mark.asyncio
    async def test_analyze_lead_creates_profile_items(
        self,
        db_session,
        setup_lead,
        setup_account,
        mock_provider_adapter,
        mock_indexing_service,
        mock_embedding_service,
        sample_profile,
        sample_profile_items,
    ):
        """analyze_lead should create ProfileItem records."""
        mock_provider_adapter.fetch_profile.return_value = sample_profile
        mock_provider_adapter.fetch_profile_items.return_value = PaginatedResult(
            items=sample_profile_items,
            next_cursor=None,
            has_more=False,
        )

        service = AnalysisService(
            db=db_session,
            provider_adapter=mock_provider_adapter,
            indexing_service=mock_indexing_service,
            embedding_service=mock_embedding_service,
        )

        result = await service.analyze_lead(setup_lead.id)

        # Check that profile items were created
        items = (
            db_session.query(ProfileItem)
            .filter(ProfileItem.account_id == setup_account.id)
            .all()
        )
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_analyze_lead_indexes_content(
        self,
        db_session,
        setup_lead,
        setup_account,
        mock_provider_adapter,
        mock_indexing_service,
        mock_embedding_service,
        sample_profile,
        sample_profile_items,
    ):
        """analyze_lead should index content in Elasticsearch."""
        mock_provider_adapter.fetch_profile.return_value = sample_profile
        mock_provider_adapter.fetch_profile_items.return_value = PaginatedResult(
            items=sample_profile_items,
            next_cursor=None,
            has_more=False,
        )

        service = AnalysisService(
            db=db_session,
            provider_adapter=mock_provider_adapter,
            indexing_service=mock_indexing_service,
            embedding_service=mock_embedding_service,
        )

        result = await service.analyze_lead(setup_lead.id)

        # Should index profile snapshot and profile items
        assert mock_indexing_service.upsert_content.call_count >= 1

    @pytest.mark.asyncio
    async def test_analyze_lead_generates_embeddings(
        self,
        db_session,
        setup_lead,
        setup_account,
        mock_provider_adapter,
        mock_indexing_service,
        mock_embedding_service,
        sample_profile,
        sample_profile_items,
    ):
        """analyze_lead should generate embeddings for content."""
        mock_provider_adapter.fetch_profile.return_value = sample_profile
        mock_provider_adapter.fetch_profile_items.return_value = PaginatedResult(
            items=sample_profile_items,
            next_cursor=None,
            has_more=False,
        )

        service = AnalysisService(
            db=db_session,
            provider_adapter=mock_provider_adapter,
            indexing_service=mock_indexing_service,
            embedding_service=mock_embedding_service,
        )

        result = await service.analyze_lead(setup_lead.id)

        # Should generate embeddings for profile items
        assert mock_embedding_service.generate_embedding.call_count >= 1

    @pytest.mark.asyncio
    async def test_analyze_lead_updates_analysis_state(
        self,
        db_session,
        setup_lead,
        setup_account,
        mock_provider_adapter,
        mock_indexing_service,
        mock_embedding_service,
        sample_profile,
        sample_profile_items,
    ):
        """analyze_lead should update ExternalAccount.analysis_state."""
        mock_provider_adapter.fetch_profile.return_value = sample_profile
        mock_provider_adapter.fetch_profile_items.return_value = PaginatedResult(
            items=sample_profile_items,
            next_cursor=None,
            has_more=False,
        )

        service = AnalysisService(
            db=db_session,
            provider_adapter=mock_provider_adapter,
            indexing_service=mock_indexing_service,
            embedding_service=mock_embedding_service,
        )

        result = await service.analyze_lead(setup_lead.id)

        # Refresh account from DB
        db_session.refresh(setup_account)
        assert setup_account.analysis_state == "analyzed"
        assert setup_account.first_analyzed_at is not None

    @pytest.mark.asyncio
    async def test_analyze_lead_returns_result(
        self,
        db_session,
        setup_lead,
        setup_account,
        mock_provider_adapter,
        mock_indexing_service,
        mock_embedding_service,
        sample_profile,
        sample_profile_items,
    ):
        """analyze_lead should return an AnalysisResult."""
        mock_provider_adapter.fetch_profile.return_value = sample_profile
        mock_provider_adapter.fetch_profile_items.return_value = PaginatedResult(
            items=sample_profile_items,
            next_cursor=None,
            has_more=False,
        )

        service = AnalysisService(
            db=db_session,
            provider_adapter=mock_provider_adapter,
            indexing_service=mock_indexing_service,
            embedding_service=mock_embedding_service,
        )

        result = await service.analyze_lead(setup_lead.id)

        assert isinstance(result, AnalysisResult)
        assert result.lead_id == setup_lead.id
        assert result.account_id == setup_account.id
        assert result.profile_items_count == 2
        assert result.success is True


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


class TestAnalysisErrorHandling:
    """Tests for error handling in analysis service."""

    @pytest.mark.asyncio
    async def test_analyze_lead_not_found_raises_error(
        self,
        db_session,
        setup_provider,
        mock_provider_adapter,
        mock_indexing_service,
        mock_embedding_service,
    ):
        """analyze_lead should raise error for non-existent lead."""
        service = AnalysisService(
            db=db_session,
            provider_adapter=mock_provider_adapter,
            indexing_service=mock_indexing_service,
            embedding_service=mock_embedding_service,
        )

        with pytest.raises(AnalysisError, match="Lead not found"):
            await service.analyze_lead(99999)

    @pytest.mark.asyncio
    async def test_analyze_lead_no_author_raises_error(
        self,
        db_session,
        setup_provider,
        mock_provider_adapter,
        mock_indexing_service,
        mock_embedding_service,
    ):
        """analyze_lead should raise error if lead has no author."""
        # Create lead without author
        lead = LeadPost(
            provider_id="reddit",
            source_location="r/test",
            external_post_id="orphan_post",
            post_url="https://reddit.com/r/test/comments/orphan",
            author_account_id=None,
            status="saved",
        )
        db_session.add(lead)
        db_session.commit()

        service = AnalysisService(
            db=db_session,
            provider_adapter=mock_provider_adapter,
            indexing_service=mock_indexing_service,
            embedding_service=mock_embedding_service,
        )

        with pytest.raises(AnalysisError, match="Lead has no author"):
            await service.analyze_lead(lead.id)

    @pytest.mark.asyncio
    async def test_analyze_lead_profile_fetch_fails(
        self,
        db_session,
        setup_lead,
        setup_account,
        mock_provider_adapter,
        mock_indexing_service,
        mock_embedding_service,
    ):
        """analyze_lead should handle profile fetch failure."""
        mock_provider_adapter.fetch_profile.return_value = None

        service = AnalysisService(
            db=db_session,
            provider_adapter=mock_provider_adapter,
            indexing_service=mock_indexing_service,
            embedding_service=mock_embedding_service,
        )

        with pytest.raises(AnalysisError, match="Failed to fetch profile"):
            await service.analyze_lead(setup_lead.id)

    @pytest.mark.asyncio
    async def test_analyze_lead_provider_error(
        self,
        db_session,
        setup_lead,
        setup_account,
        mock_provider_adapter,
        mock_indexing_service,
        mock_embedding_service,
    ):
        """analyze_lead should handle provider API errors."""
        mock_provider_adapter.fetch_profile.side_effect = Exception("API Error")

        service = AnalysisService(
            db=db_session,
            provider_adapter=mock_provider_adapter,
            indexing_service=mock_indexing_service,
            embedding_service=mock_embedding_service,
        )

        with pytest.raises(AnalysisError, match="Analysis failed"):
            await service.analyze_lead(setup_lead.id)


# =============================================================================
# PROFILE ITEM STORAGE TESTS
# =============================================================================


class TestProfileItemStorage:
    """Tests for storing profile items."""

    @pytest.mark.asyncio
    async def test_stores_post_type_items(
        self,
        db_session,
        setup_lead,
        setup_account,
        mock_provider_adapter,
        mock_indexing_service,
        mock_embedding_service,
        sample_profile,
    ):
        """Should store post-type profile items correctly."""
        items = [
            ProviderProfileItem(
                external_id="t3_post1",
                item_type=ProfileItemType.POST,
                author_id="t2_abc123",
                title="A Post",
                body_text="Post content here.",
                created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
                url="https://reddit.com/r/test/comments/post1",
                score=100,
                raw_data={},
            ),
        ]
        mock_provider_adapter.fetch_profile.return_value = sample_profile
        mock_provider_adapter.fetch_profile_items.return_value = PaginatedResult(
            items=items,
            next_cursor=None,
            has_more=False,
        )

        service = AnalysisService(
            db=db_session,
            provider_adapter=mock_provider_adapter,
            indexing_service=mock_indexing_service,
            embedding_service=mock_embedding_service,
        )

        await service.analyze_lead(setup_lead.id)

        stored = (
            db_session.query(ProfileItem)
            .filter(ProfileItem.account_id == setup_account.id)
            .first()
        )
        assert stored is not None
        assert stored.item_type == "post"
        assert stored.external_item_id == "t3_post1"
        assert stored.text_content == "Post content here."

    @pytest.mark.asyncio
    async def test_stores_comment_type_items(
        self,
        db_session,
        setup_lead,
        setup_account,
        mock_provider_adapter,
        mock_indexing_service,
        mock_embedding_service,
        sample_profile,
    ):
        """Should store comment-type profile items correctly."""
        items = [
            ProviderProfileItem(
                external_id="t1_comment1",
                item_type=ProfileItemType.COMMENT,
                author_id="t2_abc123",
                title=None,
                body_text="This is a comment.",
                created_at=datetime(2024, 1, 20, tzinfo=timezone.utc),
                url="https://reddit.com/r/test/comments/abc/comment/comment1",
                score=25,
                raw_data={},
            ),
        ]
        mock_provider_adapter.fetch_profile.return_value = sample_profile
        mock_provider_adapter.fetch_profile_items.return_value = PaginatedResult(
            items=items,
            next_cursor=None,
            has_more=False,
        )

        service = AnalysisService(
            db=db_session,
            provider_adapter=mock_provider_adapter,
            indexing_service=mock_indexing_service,
            embedding_service=mock_embedding_service,
        )

        await service.analyze_lead(setup_lead.id)

        stored = (
            db_session.query(ProfileItem)
            .filter(ProfileItem.account_id == setup_account.id)
            .first()
        )
        assert stored is not None
        assert stored.item_type == "comment"
        assert stored.text_content == "This is a comment."

    @pytest.mark.asyncio
    async def test_upserts_existing_items(
        self,
        db_session,
        setup_lead,
        setup_account,
        mock_provider_adapter,
        mock_indexing_service,
        mock_embedding_service,
        sample_profile,
    ):
        """Should upsert existing profile items instead of duplicating."""
        # Create existing item
        existing = ProfileItem(
            account_id=setup_account.id,
            item_type="post",
            external_item_id="t3_existing",
            text_content="Old content",
        )
        db_session.add(existing)
        db_session.commit()

        items = [
            ProviderProfileItem(
                external_id="t3_existing",
                item_type=ProfileItemType.POST,
                author_id="t2_abc123",
                title="Updated Post",
                body_text="New content",
                created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
                url="https://reddit.com/r/test/comments/existing",
                score=100,
                raw_data={},
            ),
        ]
        mock_provider_adapter.fetch_profile.return_value = sample_profile
        mock_provider_adapter.fetch_profile_items.return_value = PaginatedResult(
            items=items,
            next_cursor=None,
            has_more=False,
        )

        service = AnalysisService(
            db=db_session,
            provider_adapter=mock_provider_adapter,
            indexing_service=mock_indexing_service,
            embedding_service=mock_embedding_service,
        )

        await service.analyze_lead(setup_lead.id)

        # Should only have one item (upserted, not duplicated)
        items_count = (
            db_session.query(ProfileItem)
            .filter(ProfileItem.account_id == setup_account.id)
            .count()
        )
        assert items_count == 1

        # Content should be updated
        stored = (
            db_session.query(ProfileItem)
            .filter(ProfileItem.external_item_id == "t3_existing")
            .first()
        )
        assert stored.text_content == "New content"


# =============================================================================
# PAGINATION TESTS
# =============================================================================


class TestProfileItemsPagination:
    """Tests for paginated profile item fetching."""

    @pytest.mark.asyncio
    async def test_fetches_multiple_pages(
        self,
        db_session,
        setup_lead,
        setup_account,
        mock_provider_adapter,
        mock_indexing_service,
        mock_embedding_service,
        sample_profile,
    ):
        """Should fetch all pages of profile items."""
        page1_items = [
            ProviderProfileItem(
                external_id=f"t3_item{i}",
                item_type=ProfileItemType.POST,
                author_id="t2_abc123",
                title=f"Post {i}",
                body_text=f"Content {i}",
                created_at=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
                url=f"https://reddit.com/r/test/comments/item{i}",
                score=10,
                raw_data={},
            )
            for i in range(5)
        ]
        page2_items = [
            ProviderProfileItem(
                external_id=f"t3_item{i}",
                item_type=ProfileItemType.POST,
                author_id="t2_abc123",
                title=f"Post {i}",
                body_text=f"Content {i}",
                created_at=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
                url=f"https://reddit.com/r/test/comments/item{i}",
                score=10,
                raw_data={},
            )
            for i in range(5, 10)
        ]

        mock_provider_adapter.fetch_profile.return_value = sample_profile
        mock_provider_adapter.fetch_profile_items.side_effect = [
            PaginatedResult(items=page1_items, next_cursor="page2", has_more=True),
            PaginatedResult(items=page2_items, next_cursor=None, has_more=False),
        ]

        service = AnalysisService(
            db=db_session,
            provider_adapter=mock_provider_adapter,
            indexing_service=mock_indexing_service,
            embedding_service=mock_embedding_service,
        )

        result = await service.analyze_lead(setup_lead.id)

        # Should have fetched all 10 items across 2 pages
        assert result.profile_items_count == 10
        assert mock_provider_adapter.fetch_profile_items.call_count == 2


# =============================================================================
# ALREADY ANALYZED TESTS
# =============================================================================


class TestAlreadyAnalyzed:
    """Tests for handling already-analyzed accounts."""

    @pytest.mark.asyncio
    async def test_reanalyzes_if_already_analyzed(
        self,
        db_session,
        setup_lead,
        setup_account,
        mock_provider_adapter,
        mock_indexing_service,
        mock_embedding_service,
        sample_profile,
        sample_profile_items,
    ):
        """Should reanalyze even if already analyzed (refresh)."""
        # Mark as already analyzed
        setup_account.analysis_state = "analyzed"
        setup_account.first_analyzed_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        db_session.commit()

        mock_provider_adapter.fetch_profile.return_value = sample_profile
        mock_provider_adapter.fetch_profile_items.return_value = PaginatedResult(
            items=sample_profile_items,
            next_cursor=None,
            has_more=False,
        )

        service = AnalysisService(
            db=db_session,
            provider_adapter=mock_provider_adapter,
            indexing_service=mock_indexing_service,
            embedding_service=mock_embedding_service,
        )

        result = await service.analyze_lead(setup_lead.id)

        # Should still succeed (refresh analysis)
        assert result.success is True
        mock_provider_adapter.fetch_profile.assert_called_once()

    @pytest.mark.asyncio
    async def test_preserves_first_analyzed_at(
        self,
        db_session,
        setup_lead,
        setup_account,
        mock_provider_adapter,
        mock_indexing_service,
        mock_embedding_service,
        sample_profile,
        sample_profile_items,
    ):
        """Should preserve first_analyzed_at on reanalysis."""
        # Use naive datetime since SQLite strips timezone
        original_analyzed_at = datetime(2024, 1, 1, 0, 0, 0)
        setup_account.analysis_state = "analyzed"
        setup_account.first_analyzed_at = original_analyzed_at
        db_session.commit()

        mock_provider_adapter.fetch_profile.return_value = sample_profile
        mock_provider_adapter.fetch_profile_items.return_value = PaginatedResult(
            items=sample_profile_items,
            next_cursor=None,
            has_more=False,
        )

        service = AnalysisService(
            db=db_session,
            provider_adapter=mock_provider_adapter,
            indexing_service=mock_indexing_service,
            embedding_service=mock_embedding_service,
        )

        await service.analyze_lead(setup_lead.id)

        db_session.refresh(setup_account)
        assert setup_account.first_analyzed_at == original_analyzed_at
