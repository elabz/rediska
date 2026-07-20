"""Unit tests for Epic 7.1 - Leads service.

Tests cover:
1. Saving posts as leads
2. Lead status management
3. Lead retrieval
4. Author account handling
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from rediska_core.domain.models import (
    ExternalAccount,
    LeadPost,
    Provider,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def setup_provider(db_session):
    """Set up provider for tests."""
    provider = Provider(
        provider_id="reddit",
        display_name="Reddit",
        enabled=True,
    )
    db_session.add(provider)
    db_session.flush()
    return provider


@pytest.fixture
def setup_author_account(db_session, setup_provider):
    """Set up an author account for tests."""
    account = ExternalAccount(
        provider_id="reddit",
        external_username="test_author",
        external_user_id="t2_author123",
        remote_status="active",
    )
    db_session.add(account)
    db_session.flush()
    return account


# =============================================================================
# SAVE LEAD TESTS
# =============================================================================


class TestSaveLead:
    """Tests for saving posts as leads."""

    def test_save_lead_creates_new_lead_post(self, db_session, setup_provider):
        """Saving a new lead should create a lead_posts row."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        result = service.save_lead(
            provider_id="reddit",
            source_location="r/programming",
            external_post_id="abc123",
            post_url="https://reddit.com/r/programming/comments/abc123",
            title="Looking for developers",
            body_text="We need Python developers",
        )

        assert result is not None
        assert result.id is not None
        assert result.status == "saved"
        assert result.source_location == "r/programming"
        assert result.external_post_id == "abc123"

    def test_save_lead_sets_status_to_saved(self, db_session, setup_provider):
        """Saving a lead should set status to 'saved'."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        result = service.save_lead(
            provider_id="reddit",
            source_location="r/python",
            external_post_id="xyz789",
            post_url="https://reddit.com/r/python/comments/xyz789",
        )

        assert result.status == "saved"

    def test_save_lead_upserts_existing_lead(self, db_session, setup_provider):
        """Saving an existing lead should update it, not create duplicate."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        # First save
        result1 = service.save_lead(
            provider_id="reddit",
            source_location="r/programming",
            external_post_id="abc123",
            post_url="https://reddit.com/r/programming/comments/abc123",
            title="Original title",
        )

        # Second save with same external_post_id
        result2 = service.save_lead(
            provider_id="reddit",
            source_location="r/programming",
            external_post_id="abc123",
            post_url="https://reddit.com/r/programming/comments/abc123",
            title="Updated title",
        )

        # Should be the same record
        assert result1.id == result2.id
        assert result2.title == "Updated title"

        # Only one record should exist
        count = db_session.query(LeadPost).filter(
            LeadPost.external_post_id == "abc123"
        ).count()
        assert count == 1

    def test_save_lead_with_author_username(
        self, db_session, setup_provider, setup_author_account
    ):
        """Saving a lead with author should link to external_account."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        result = service.save_lead(
            provider_id="reddit",
            source_location="r/programming",
            external_post_id="post456",
            post_url="https://reddit.com/r/programming/comments/post456",
            author_username="test_author",
        )

        assert result.author_account_id == setup_author_account.id

    def test_save_lead_creates_author_account_if_not_exists(
        self, db_session, setup_provider
    ):
        """Saving a lead with new author should create external_account."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        result = service.save_lead(
            provider_id="reddit",
            source_location="r/programming",
            external_post_id="post789",
            post_url="https://reddit.com/r/programming/comments/post789",
            author_username="new_author",
        )

        assert result.author_account_id is not None

        # Check account was created
        account = db_session.query(ExternalAccount).filter(
            ExternalAccount.external_username == "new_author"
        ).first()
        assert account is not None
        assert account.provider_id == "reddit"

    def test_save_lead_with_post_created_at(self, db_session, setup_provider):
        """Saving a lead should store post_created_at timestamp."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)
        post_time = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

        result = service.save_lead(
            provider_id="reddit",
            source_location="r/programming",
            external_post_id="time_post",
            post_url="https://reddit.com/r/programming/comments/time_post",
            post_created_at=post_time,
        )

        assert result.post_created_at == post_time

    def test_save_lead_preserves_new_status_on_first_save(
        self, db_session, setup_provider
    ):
        """First save should change status from 'new' to 'saved'."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        # Create a 'new' lead directly
        lead = LeadPost(
            provider_id="reddit",
            source_location="r/test",
            external_post_id="new_lead",
            post_url="https://reddit.com/r/test/comments/new_lead",
            status="new",
        )
        db_session.add(lead)
        db_session.flush()

        # Now save it
        result = service.save_lead(
            provider_id="reddit",
            source_location="r/test",
            external_post_id="new_lead",
            post_url="https://reddit.com/r/test/comments/new_lead",
        )

        assert result.status == "saved"


class TestGetLead:
    """Tests for retrieving leads."""

    def test_get_lead_by_id(self, db_session, setup_provider):
        """Should retrieve lead by ID."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        # Create a lead
        lead = service.save_lead(
            provider_id="reddit",
            source_location="r/test",
            external_post_id="get_test",
            post_url="https://reddit.com/r/test/comments/get_test",
            title="Test Post",
        )

        # Retrieve it
        result = service.get_lead(lead.id)

        assert result is not None
        assert result.id == lead.id
        assert result.title == "Test Post"

    def test_get_lead_not_found_returns_none(self, db_session, setup_provider):
        """Should return None for non-existent lead."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        result = service.get_lead(99999)

        assert result is None

    def test_get_lead_by_external_id(self, db_session, setup_provider):
        """Should retrieve lead by provider_id and external_post_id."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        # Create a lead
        lead = service.save_lead(
            provider_id="reddit",
            source_location="r/test",
            external_post_id="ext_get_test",
            post_url="https://reddit.com/r/test/comments/ext_get_test",
        )

        # Retrieve by external ID
        result = service.get_lead_by_external_id("reddit", "ext_get_test")

        assert result is not None
        assert result.id == lead.id


class TestListLeads:
    """Tests for listing leads."""

    def test_list_leads_returns_all(self, db_session, setup_provider):
        """Should return all leads."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        # Create multiple leads
        for i in range(3):
            service.save_lead(
                provider_id="reddit",
                source_location="r/test",
                external_post_id=f"list_test_{i}",
                post_url=f"https://reddit.com/r/test/comments/list_test_{i}",
            )

        result = service.list_leads()

        assert len(result) == 3

    def test_list_leads_filters_by_status(self, db_session, setup_provider):
        """Should filter leads by status."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        # Create leads with different statuses
        service.save_lead(
            provider_id="reddit",
            source_location="r/test",
            external_post_id="saved_lead",
            post_url="https://reddit.com/r/test/comments/saved_lead",
        )

        # Create a 'new' lead directly
        new_lead = LeadPost(
            provider_id="reddit",
            source_location="r/test",
            external_post_id="new_lead",
            post_url="https://reddit.com/r/test/comments/new_lead",
            status="new",
        )
        db_session.add(new_lead)
        db_session.flush()

        # Filter by status
        saved_leads = service.list_leads(status="saved")
        new_leads = service.list_leads(status="new")

        assert len(saved_leads) == 1
        assert len(new_leads) == 1

    def test_list_leads_filters_by_source_location(self, db_session, setup_provider):
        """Should filter leads by source_location."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        # Create leads in different locations
        service.save_lead(
            provider_id="reddit",
            source_location="r/python",
            external_post_id="python_post",
            post_url="https://reddit.com/r/python/comments/python_post",
        )
        service.save_lead(
            provider_id="reddit",
            source_location="r/javascript",
            external_post_id="js_post",
            post_url="https://reddit.com/r/javascript/comments/js_post",
        )

        result = service.list_leads(source_location="r/python")

        assert len(result) == 1
        assert result[0].source_location == "r/python"

    def test_list_leads_pagination(self, db_session, setup_provider):
        """Should support pagination with offset and limit."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        # Create multiple leads
        for i in range(10):
            service.save_lead(
                provider_id="reddit",
                source_location="r/test",
                external_post_id=f"page_test_{i}",
                post_url=f"https://reddit.com/r/test/comments/page_test_{i}",
            )

        # Get first page
        page1 = service.list_leads(offset=0, limit=5)
        # Get second page
        page2 = service.list_leads(offset=5, limit=5)

        assert len(page1) == 5
        assert len(page2) == 5
        # Should be different leads
        page1_ids = {l.id for l in page1}
        page2_ids = {l.id for l in page2}
        assert page1_ids.isdisjoint(page2_ids)


class TestUpdateLeadStatus:
    """Tests for updating lead status."""

    def test_update_status_to_ignored(self, db_session, setup_provider):
        """Should update lead status to 'ignored'."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        lead = service.save_lead(
            provider_id="reddit",
            source_location="r/test",
            external_post_id="ignore_test",
            post_url="https://reddit.com/r/test/comments/ignore_test",
        )

        result = service.update_status(lead.id, "ignored")

        assert result is not None
        assert result.status == "ignored"

    def test_update_status_to_contacted(self, db_session, setup_provider):
        """Should update lead status to 'contacted'."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        lead = service.save_lead(
            provider_id="reddit",
            source_location="r/test",
            external_post_id="contact_test",
            post_url="https://reddit.com/r/test/comments/contact_test",
        )

        result = service.update_status(lead.id, "contacted")

        assert result is not None
        assert result.status == "contacted"

    def test_update_status_invalid_status_raises_error(
        self, db_session, setup_provider
    ):
        """Should raise error for invalid status value."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        lead = service.save_lead(
            provider_id="reddit",
            source_location="r/test",
            external_post_id="invalid_test",
            post_url="https://reddit.com/r/test/comments/invalid_test",
        )

        with pytest.raises(ValueError) as exc_info:
            service.update_status(lead.id, "invalid_status")

        assert "Invalid status" in str(exc_info.value)


# =============================================================================
# AUTHOR-LEVEL DEDUPE TESTS
# =============================================================================


class TestGetActiveLeadForAuthor:
    """Tests for author-level active lead lookup."""

    def test_returns_none_when_author_has_no_leads(
        self, db_session, setup_provider, setup_author_account
    ):
        """An author with no leads has no active lead."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        assert service.get_active_lead_for_author("reddit", setup_author_account.id) is None

    def test_returns_saved_lead(self, db_session, setup_provider, setup_author_account):
        """A saved lead is active."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)
        lead = service.save_lead(
            provider_id="reddit",
            source_location="r/test",
            external_post_id="active_1",
            post_url="https://reddit.com/r/test/comments/active_1",
            author_username="test_author",
        )

        found = service.get_active_lead_for_author("reddit", setup_author_account.id)
        assert found is not None
        assert found.id == lead.id

    def test_ignored_lead_is_not_active(
        self, db_session, setup_provider, setup_author_account
    ):
        """An ignored lead is a standing negative verdict, not an active lead."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)
        lead = service.save_lead(
            provider_id="reddit",
            source_location="r/test",
            external_post_id="ignored_1",
            post_url="https://reddit.com/r/test/comments/ignored_1",
            author_username="test_author",
        )
        service.update_status(lead.id, "ignored")

        assert service.get_active_lead_for_author("reddit", setup_author_account.id) is None

    def test_soft_deleted_lead_is_not_active(
        self, db_session, setup_provider, setup_author_account
    ):
        """A locally deleted lead is not active."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)
        lead = service.save_lead(
            provider_id="reddit",
            source_location="r/test",
            external_post_id="deleted_1",
            post_url="https://reddit.com/r/test/comments/deleted_1",
            author_username="test_author",
        )
        lead.deleted_at = datetime.utcnow()
        db_session.flush()

        assert service.get_active_lead_for_author("reddit", setup_author_account.id) is None

    def test_contacted_lead_is_still_active(
        self, db_session, setup_provider, setup_author_account
    ):
        """Contacted leads remain active - only 'ignored' deactivates."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)
        lead = service.save_lead(
            provider_id="reddit",
            source_location="r/test",
            external_post_id="contacted_1",
            post_url="https://reddit.com/r/test/comments/contacted_1",
            author_username="test_author",
        )
        service.update_status(lead.id, "contacted")

        found = service.get_active_lead_for_author("reddit", setup_author_account.id)
        assert found is not None
        assert found.id == lead.id


class TestSaveLeadAttachesToExistingAuthorLead:
    """Tests for at-most-one-active-lead-per-author on save."""

    def test_second_post_by_same_author_attaches(
        self, db_session, setup_provider, setup_author_account
    ):
        """A second post by an author with an active lead creates no new lead."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        first = service.save_lead(
            provider_id="reddit",
            source_location="r/one",
            external_post_id="post_one",
            post_url="https://reddit.com/r/one/comments/post_one",
            title="First post",
            body_text="First body",
            author_username="test_author",
        )
        second = service.save_lead(
            provider_id="reddit",
            source_location="r/two",
            external_post_id="post_two",
            post_url="https://reddit.com/r/two/comments/post_two",
            title="Second post",
            body_text="Second body",
            author_username="test_author",
        )

        assert second.id == first.id
        assert getattr(second, "_attached") is True
        assert db_session.query(LeadPost).count() == 1

    def test_attached_lead_keeps_its_primary_post_fields(
        self, db_session, setup_provider, setup_author_account
    ):
        """Attaching must not overwrite the lead's own post identity."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        service.save_lead(
            provider_id="reddit",
            source_location="r/one",
            external_post_id="keep_one",
            post_url="https://reddit.com/r/one/comments/keep_one",
            title="First post",
            body_text="First body",
            author_username="test_author",
        )
        attached = service.save_lead(
            provider_id="reddit",
            source_location="r/two",
            external_post_id="keep_two",
            post_url="https://reddit.com/r/two/comments/keep_two",
            title="Second post",
            body_text="Second body",
            author_username="test_author",
        )

        assert attached.external_post_id == "keep_one"
        assert attached.title == "First post"
        assert attached.source_location == "r/one"

    def test_attached_post_becomes_a_profile_item(
        self, db_session, setup_provider, setup_author_account
    ):
        """The attached post's content is preserved as a profile_item."""
        from rediska_core.domain.models import ProfileItem
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        service.save_lead(
            provider_id="reddit",
            source_location="r/one",
            external_post_id="item_one",
            post_url="https://reddit.com/r/one/comments/item_one",
            title="First post",
            body_text="First body",
            author_username="test_author",
        )
        service.save_lead(
            provider_id="reddit",
            source_location="r/two",
            external_post_id="item_two",
            post_url="https://reddit.com/r/two/comments/item_two",
            title="Second post",
            body_text="Second body",
            author_username="test_author",
        )

        item_ids = {
            item.external_item_id
            for item in db_session.query(ProfileItem)
            .filter(ProfileItem.account_id == setup_author_account.id)
            .all()
        }
        assert "item_one" in item_ids
        assert "item_two" in item_ids

    def test_resaving_the_same_post_is_not_an_attach(
        self, db_session, setup_provider, setup_author_account
    ):
        """Re-saving the same post keeps per-post upsert semantics."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        first = service.save_lead(
            provider_id="reddit",
            source_location="r/one",
            external_post_id="same_post",
            post_url="https://reddit.com/r/one/comments/same_post",
            title="Original title",
            author_username="test_author",
        )
        again = service.save_lead(
            provider_id="reddit",
            source_location="r/one",
            external_post_id="same_post",
            post_url="https://reddit.com/r/one/comments/same_post",
            title="Updated title",
            author_username="test_author",
        )

        assert again.id == first.id
        assert getattr(again, "_attached") is False
        assert again.title == "Updated title"

    def test_ignored_author_lead_is_not_resurrected(
        self, db_session, setup_provider, setup_author_account
    ):
        """A new post by an ignored author creates a separate lead, not a revival."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        first = service.save_lead(
            provider_id="reddit",
            source_location="r/one",
            external_post_id="ign_one",
            post_url="https://reddit.com/r/one/comments/ign_one",
            author_username="test_author",
        )
        service.update_status(first.id, "ignored")

        second = service.save_lead(
            provider_id="reddit",
            source_location="r/two",
            external_post_id="ign_two",
            post_url="https://reddit.com/r/two/comments/ign_two",
            author_username="test_author",
        )

        assert second.id != first.id
        assert getattr(second, "_attached") is False
        assert first.status == "ignored"

    def test_authorless_posts_keep_per_post_semantics(self, db_session, setup_provider):
        """Posts with no resolvable author never attach to each other."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        first = service.save_lead(
            provider_id="reddit",
            source_location="r/one",
            external_post_id="anon_one",
            post_url="https://reddit.com/r/one/comments/anon_one",
        )
        second = service.save_lead(
            provider_id="reddit",
            source_location="r/one",
            external_post_id="anon_two",
            post_url="https://reddit.com/r/one/comments/anon_two",
        )

        assert first.id != second.id
        assert getattr(second, "_attached") is False

    def test_different_authors_get_separate_leads(self, db_session, setup_provider):
        """Author-level dedupe must not collapse distinct authors."""
        from rediska_core.domain.services.leads import LeadsService

        service = LeadsService(db=db_session)

        first = service.save_lead(
            provider_id="reddit",
            source_location="r/one",
            external_post_id="auth_a",
            post_url="https://reddit.com/r/one/comments/auth_a",
            author_username="author_a",
        )
        second = service.save_lead(
            provider_id="reddit",
            source_location="r/one",
            external_post_id="auth_b",
            post_url="https://reddit.com/r/one/comments/auth_b",
            author_username="author_b",
        )

        assert first.id != second.id
        assert getattr(second, "_attached") is False
