"""Unit tests for DirectoryService.

Tests the directory service which provides:
1. Listing accounts by analysis state (analyzed)
2. Listing accounts by contact state (contacted)
3. Listing accounts by engagement state (engaged)
4. Filtering and pagination
5. Fetching related data (profile snapshots, lead posts)
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    ExternalAccount,
    LeadPost,
    ProfileSnapshot,
    Provider,
)
from rediska_core.domain.services.directory import (
    DirectoryEntry,
    DirectoryService,
)


# =============================================================================
# FIXTURES
# =============================================================================


# Note: db_session fixture comes from conftest.py


@pytest.fixture
def setup_provider(db_session):
    """Set up provider for tests."""
    provider = Provider(provider_id="reddit", display_name="Reddit")
    db_session.add(provider)
    db_session.flush()
    return provider


@pytest.fixture
def setup_accounts(db_session, setup_provider):
    """Set up external accounts with various states."""
    accounts = []

    # Account 1: analyzed, not contacted
    account1 = ExternalAccount(
        provider_id="reddit",
        external_username="user_analyzed",
        external_user_id="t2_analyzed",
        analysis_state="analyzed",
        contact_state="not_contacted",
        engagement_state="not_engaged",
        first_analyzed_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )
    db_session.add(account1)
    accounts.append(account1)

    # Account 2: analyzed and contacted
    account2 = ExternalAccount(
        provider_id="reddit",
        external_username="user_contacted",
        external_user_id="t2_contacted",
        analysis_state="analyzed",
        contact_state="contacted",
        engagement_state="not_engaged",
        first_analyzed_at=datetime(2024, 1, 10, tzinfo=timezone.utc),
        first_contacted_at=datetime(2024, 1, 20, tzinfo=timezone.utc),
    )
    db_session.add(account2)
    accounts.append(account2)

    # Account 3: analyzed, contacted, and engaged
    account3 = ExternalAccount(
        provider_id="reddit",
        external_username="user_engaged",
        external_user_id="t2_engaged",
        analysis_state="analyzed",
        contact_state="contacted",
        engagement_state="engaged",
        first_analyzed_at=datetime(2024, 1, 5, tzinfo=timezone.utc),
        first_contacted_at=datetime(2024, 1, 12, tzinfo=timezone.utc),
        first_inbound_after_contact_at=datetime(2024, 1, 25, tzinfo=timezone.utc),
    )
    db_session.add(account3)
    accounts.append(account3)

    # Account 4: not analyzed
    account4 = ExternalAccount(
        provider_id="reddit",
        external_username="user_not_analyzed",
        external_user_id="t2_not_analyzed",
        analysis_state="not_analyzed",
        contact_state="not_contacted",
        engagement_state="not_engaged",
    )
    db_session.add(account4)
    accounts.append(account4)

    db_session.flush()
    return accounts


@pytest.fixture
def setup_profile_snapshots(db_session, setup_accounts):
    """Set up profile snapshots for analyzed accounts."""
    snapshots = []

    for account in setup_accounts:
        if account.analysis_state == "analyzed":
            snapshot = ProfileSnapshot(
                account_id=account.id,
                fetched_at=datetime.now(timezone.utc),
                summary_text=f"Summary for {account.external_username}",
                signals_json={"karma": 100},
            )
            db_session.add(snapshot)
            snapshots.append(snapshot)

    db_session.flush()
    return snapshots


@pytest.fixture
def setup_lead_posts(db_session, setup_accounts, setup_provider):
    """Set up lead posts for accounts."""
    leads = []

    for i, account in enumerate(setup_accounts[:3]):  # First 3 accounts have leads
        lead = LeadPost(
            provider_id="reddit",
            source_location="r/test",
            external_post_id=f"post_{account.external_username}",
            post_url=f"https://reddit.com/r/test/comments/{account.external_username}",
            author_account_id=account.id,
            title=f"Post by {account.external_username}",
            status="saved",
        )
        db_session.add(lead)
        leads.append(lead)

    db_session.flush()
    return leads


# =============================================================================
# ANALYZED DIRECTORY TESTS
# =============================================================================


class TestAnalyzedDirectory:
    """Tests for listing analyzed accounts."""

    def test_list_analyzed_returns_analyzed_accounts(
        self, db_session, setup_accounts
    ):
        """list_analyzed should return accounts with analysis_state='analyzed'."""
        service = DirectoryService(db=db_session)

        result = service.list_analyzed()

        # Should include accounts 1, 2, 3 (all analyzed)
        assert len(result) == 3
        for entry in result:
            assert entry.analysis_state == "analyzed"

    def test_list_analyzed_excludes_not_analyzed(
        self, db_session, setup_accounts
    ):
        """list_analyzed should exclude accounts with analysis_state='not_analyzed'."""
        service = DirectoryService(db=db_session)

        result = service.list_analyzed()

        usernames = [e.external_username for e in result]
        assert "user_not_analyzed" not in usernames

    def test_list_analyzed_returns_directory_entries(
        self, db_session, setup_accounts
    ):
        """list_analyzed should return DirectoryEntry objects."""
        service = DirectoryService(db=db_session)

        result = service.list_analyzed()

        assert len(result) > 0
        entry = result[0]
        assert isinstance(entry, DirectoryEntry)
        assert hasattr(entry, "id")
        assert hasattr(entry, "external_username")
        assert hasattr(entry, "analysis_state")

    def test_list_analyzed_with_pagination(
        self, db_session, setup_accounts
    ):
        """list_analyzed should support pagination."""
        service = DirectoryService(db=db_session)

        result = service.list_analyzed(limit=2, offset=0)
        assert len(result) == 2

        result2 = service.list_analyzed(limit=2, offset=2)
        assert len(result2) == 1

    def test_list_analyzed_filters_by_provider(
        self, db_session, setup_accounts
    ):
        """list_analyzed should filter by provider_id."""
        service = DirectoryService(db=db_session)

        result = service.list_analyzed(provider_id="reddit")
        assert len(result) == 3

        result_other = service.list_analyzed(provider_id="twitter")
        assert len(result_other) == 0


# =============================================================================
# CONTACTED DIRECTORY TESTS
# =============================================================================


class TestContactedDirectory:
    """Tests for listing contacted accounts."""

    def test_list_contacted_returns_contacted_accounts(
        self, db_session, setup_accounts
    ):
        """list_contacted should return accounts with contact_state='contacted'."""
        service = DirectoryService(db=db_session)

        result = service.list_contacted()

        # Should include accounts 2, 3 (both contacted)
        assert len(result) == 2
        for entry in result:
            assert entry.contact_state == "contacted"

    def test_list_contacted_excludes_not_contacted(
        self, db_session, setup_accounts
    ):
        """list_contacted should exclude accounts with contact_state='not_contacted'."""
        service = DirectoryService(db=db_session)

        result = service.list_contacted()

        usernames = [e.external_username for e in result]
        assert "user_analyzed" not in usernames
        assert "user_not_analyzed" not in usernames

    def test_list_contacted_with_pagination(
        self, db_session, setup_accounts
    ):
        """list_contacted should support pagination."""
        service = DirectoryService(db=db_session)

        result = service.list_contacted(limit=1, offset=0)
        assert len(result) == 1

        result2 = service.list_contacted(limit=1, offset=1)
        assert len(result2) == 1


# =============================================================================
# ENGAGED DIRECTORY TESTS
# =============================================================================


class TestEngagedDirectory:
    """Tests for listing engaged accounts."""

    def test_list_engaged_returns_engaged_accounts(
        self, db_session, setup_accounts
    ):
        """list_engaged should return accounts with engagement_state='engaged'."""
        service = DirectoryService(db=db_session)

        result = service.list_engaged()

        # Should only include account 3 (engaged)
        assert len(result) == 1
        assert result[0].engagement_state == "engaged"
        assert result[0].external_username == "user_engaged"

    def test_list_engaged_excludes_not_engaged(
        self, db_session, setup_accounts
    ):
        """list_engaged should exclude accounts with engagement_state='not_engaged'."""
        service = DirectoryService(db=db_session)

        result = service.list_engaged()

        usernames = [e.external_username for e in result]
        assert "user_analyzed" not in usernames
        assert "user_contacted" not in usernames
        assert "user_not_analyzed" not in usernames

    def test_list_engaged_empty_when_none_engaged(
        self, db_session, setup_provider
    ):
        """list_engaged should return empty list when no engaged accounts."""
        # Create account that's not engaged
        account = ExternalAccount(
            provider_id="reddit",
            external_username="user_test",
            engagement_state="not_engaged",
        )
        db_session.add(account)
        db_session.flush()

        service = DirectoryService(db=db_session)

        result = service.list_engaged()

        assert len(result) == 0


# =============================================================================
# DIRECTORY ENTRY DATA TESTS
# =============================================================================


class TestDirectoryEntryData:
    """Tests for DirectoryEntry data structure."""

    def test_entry_includes_timestamps(
        self, db_session, setup_accounts
    ):
        """DirectoryEntry should include relevant timestamps."""
        service = DirectoryService(db=db_session)

        result = service.list_analyzed()

        # Find the engaged user (has all timestamps)
        engaged_entry = next(
            e for e in result if e.external_username == "user_engaged"
        )

        assert engaged_entry.first_analyzed_at is not None
        assert engaged_entry.first_contacted_at is not None
        assert engaged_entry.first_inbound_after_contact_at is not None

    def test_entry_includes_account_info(
        self, db_session, setup_accounts
    ):
        """DirectoryEntry should include account information."""
        service = DirectoryService(db=db_session)

        result = service.list_analyzed()

        entry = result[0]
        assert entry.id is not None
        assert entry.provider_id == "reddit"
        assert entry.external_username is not None
        assert entry.external_user_id is not None

    def test_entry_includes_latest_snapshot_summary(
        self, db_session, setup_accounts, setup_profile_snapshots
    ):
        """DirectoryEntry should include latest profile snapshot summary."""
        service = DirectoryService(db=db_session)

        result = service.list_analyzed()

        # Entries should have latest_summary from profile snapshots
        entry = result[0]
        assert entry.latest_summary is not None


# =============================================================================
# COUNT TESTS
# =============================================================================


class TestDirectoryCounts:
    """Tests for directory count methods."""

    def test_count_analyzed(self, db_session, setup_accounts):
        """count_analyzed should return correct count."""
        service = DirectoryService(db=db_session)

        count = service.count_analyzed()

        assert count == 3

    def test_count_contacted(self, db_session, setup_accounts):
        """count_contacted should return correct count."""
        service = DirectoryService(db=db_session)

        count = service.count_contacted()

        assert count == 2

    def test_count_engaged(self, db_session, setup_accounts):
        """count_engaged should return correct count."""
        service = DirectoryService(db=db_session)

        count = service.count_engaged()

        assert count == 1

    def test_count_with_provider_filter(self, db_session, setup_accounts):
        """count methods should support provider filter."""
        service = DirectoryService(db=db_session)

        count = service.count_analyzed(provider_id="reddit")
        assert count == 3

        count_other = service.count_analyzed(provider_id="twitter")
        assert count_other == 0


# =============================================================================
# SORTING TESTS
# =============================================================================


class TestDirectorySorting:
    """Tests for directory sorting."""

    def test_list_analyzed_sorted_by_analyzed_at_desc(
        self, db_session, setup_accounts
    ):
        """list_analyzed should sort by first_analyzed_at descending by default."""
        service = DirectoryService(db=db_session)

        result = service.list_analyzed()

        # Should be sorted by first_analyzed_at descending
        # user_analyzed (Jan 15) > user_contacted (Jan 10) > user_engaged (Jan 5)
        assert result[0].external_username == "user_analyzed"
        assert result[1].external_username == "user_contacted"
        assert result[2].external_username == "user_engaged"

    def test_list_contacted_sorted_by_contacted_at_desc(
        self, db_session, setup_accounts
    ):
        """list_contacted should sort by first_contacted_at descending."""
        service = DirectoryService(db=db_session)

        result = service.list_contacted()

        # user_contacted (Jan 20) > user_engaged (Jan 12)
        assert result[0].external_username == "user_contacted"
        assert result[1].external_username == "user_engaged"
