"""Unit tests for author-level scout watch dedupe.

Tests cover:
1. The pre-pipeline verdict gate (check_author_verdict)
2. Author-level attach in save_lead_from_watch
"""

from datetime import datetime, timezone

import pytest

from rediska_core.domain.models import (
    DoNotContact,
    ExternalAccount,
    LeadPost,
    Provider,
    ScoutWatch,
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
def author(db_session, setup_provider):
    """Set up an author account for tests."""
    account = ExternalAccount(
        provider_id="reddit",
        external_username="watched_author",
        remote_status="active",
    )
    db_session.add(account)
    db_session.flush()
    return account


@pytest.fixture
def watch(db_session, setup_provider):
    """Set up a scout watch."""
    watch = ScoutWatch(
        provider_id="reddit",
        source_location="r/watched",
        sort_by="new",
        time_filter="day",
        auto_analyze=True,
        min_confidence=0.7,
        is_active=True,
    )
    db_session.add(watch)
    db_session.flush()
    return watch


def _post_data(external_post_id: str, **overrides) -> dict:
    """Build normalized post data for save_lead_from_watch."""
    data = {
        "provider_id": "reddit",
        "source_location": "r/watched",
        "external_post_id": external_post_id,
        "post_url": f"https://reddit.com/comments/{external_post_id}",
        "title": f"Title {external_post_id}",
        "body_text": f"Body {external_post_id}",
        "author_username": "watched_author",
    }
    data.update(overrides)
    return data


# =============================================================================
# VERDICT GATE TESTS
# =============================================================================


class TestCheckAuthorVerdict:
    """Tests for the pre-pipeline standing-verdict gate."""

    def test_unknown_author_has_no_verdict(self, db_session, setup_provider):
        """An author with no local record proceeds to analysis."""
        from rediska_core.domain.services.scout_watch import ScoutWatchService

        service = ScoutWatchService(db_session)

        assert service.check_author_verdict("reddit", "never_seen") is None

    def test_known_author_without_history_has_no_verdict(
        self, db_session, setup_provider, author
    ):
        """A known but un-analysed author proceeds to analysis."""
        from rediska_core.domain.services.scout_watch import ScoutWatchService

        service = ScoutWatchService(db_session)

        assert service.check_author_verdict("reddit", "watched_author") is None

    def test_do_not_contact_author_is_skipped(self, db_session, setup_provider, author):
        """Do-not-contact is the highest-precedence verdict."""
        from rediska_core.domain.services.scout_watch import (
            SKIP_DO_NOT_CONTACT,
            ScoutWatchService,
        )

        db_session.add(
            DoNotContact(provider_id="reddit", external_username="watched_author")
        )
        db_session.flush()

        service = ScoutWatchService(db_session)

        assert service.check_author_verdict("reddit", "watched_author") == SKIP_DO_NOT_CONTACT

    def test_do_not_contact_applies_to_unknown_accounts(
        self, db_session, setup_provider
    ):
        """Do-not-contact is checked before the account lookup."""
        from rediska_core.domain.services.scout_watch import (
            SKIP_DO_NOT_CONTACT,
            ScoutWatchService,
        )

        db_session.add(
            DoNotContact(provider_id="reddit", external_username="blocked_stranger")
        )
        db_session.flush()

        service = ScoutWatchService(db_session)

        assert (
            service.check_author_verdict("reddit", "blocked_stranger")
            == SKIP_DO_NOT_CONTACT
        )

    def test_contacted_author_is_skipped(self, db_session, setup_provider, author):
        """An already-contacted author needs no fresh analysis."""
        from rediska_core.domain.services.scout_watch import (
            SKIP_ALREADY_CONTACTED,
            ScoutWatchService,
        )

        author.contact_state = "contacted"
        db_session.flush()

        service = ScoutWatchService(db_session)

        assert (
            service.check_author_verdict("reddit", "watched_author")
            == SKIP_ALREADY_CONTACTED
        )

    def test_engaged_author_is_skipped(self, db_session, setup_provider, author):
        """An engaged author needs no fresh analysis."""
        from rediska_core.domain.services.scout_watch import (
            SKIP_ALREADY_ENGAGED,
            ScoutWatchService,
        )

        author.engagement_state = "engaged"
        db_session.flush()

        service = ScoutWatchService(db_session)

        assert (
            service.check_author_verdict("reddit", "watched_author")
            == SKIP_ALREADY_ENGAGED
        )

    def test_ignored_lead_author_is_skipped(self, db_session, setup_provider, author):
        """An ignored lead is a standing negative verdict on the author."""
        from rediska_core.domain.services.leads import LeadsService
        from rediska_core.domain.services.scout_watch import (
            SKIP_LEAD_IGNORED,
            ScoutWatchService,
        )

        leads_service = LeadsService(db_session)
        lead = leads_service.save_lead(
            provider_id="reddit",
            source_location="r/watched",
            external_post_id="ignored_post",
            post_url="https://reddit.com/comments/ignored_post",
            author_username="watched_author",
        )
        leads_service.update_status(lead.id, "ignored")

        service = ScoutWatchService(db_session)

        assert (
            service.check_author_verdict("reddit", "watched_author") == SKIP_LEAD_IGNORED
        )

    def test_active_lead_author_is_not_skipped(self, db_session, setup_provider, author):
        """An author with an active lead still runs — the post attaches to it."""
        from rediska_core.domain.services.leads import LeadsService
        from rediska_core.domain.services.scout_watch import ScoutWatchService

        LeadsService(db_session).save_lead(
            provider_id="reddit",
            source_location="r/watched",
            external_post_id="active_post",
            post_url="https://reddit.com/comments/active_post",
            author_username="watched_author",
        )

        service = ScoutWatchService(db_session)

        assert service.check_author_verdict("reddit", "watched_author") is None

    def test_active_lead_wins_over_a_stale_ignored_lead(
        self, db_session, setup_provider, author
    ):
        """An author with both ignored and active leads is not skipped."""
        from rediska_core.domain.services.leads import LeadsService
        from rediska_core.domain.services.scout_watch import ScoutWatchService

        leads_service = LeadsService(db_session)
        old = leads_service.save_lead(
            provider_id="reddit",
            source_location="r/watched",
            external_post_id="stale_ignored",
            post_url="https://reddit.com/comments/stale_ignored",
            author_username="watched_author",
        )
        leads_service.update_status(old.id, "ignored")

        db_session.add(
            LeadPost(
                provider_id="reddit",
                source_location="r/watched",
                external_post_id="fresh_active",
                post_url="https://reddit.com/comments/fresh_active",
                author_account_id=author.id,
                status="saved",
                remote_visibility="unknown",
            )
        )
        db_session.flush()

        service = ScoutWatchService(db_session)

        assert service.check_author_verdict("reddit", "watched_author") is None


# =============================================================================
# ATTACH TESTS
# =============================================================================


class TestSaveLeadFromWatchAttaches:
    """Tests for author-level attach on the scout promotion path."""

    def test_second_qualifying_post_attaches_to_existing_lead(
        self, db_session, setup_provider, author, watch
    ):
        """Two qualifying posts by one author yield one lead."""
        from rediska_core.domain.services.scout_watch import ScoutWatchService

        service = ScoutWatchService(db_session)

        first = service.save_lead_from_watch(watch, _post_data("promo_one"))
        first_id = first.id
        # The flag lives on the returned instance, so read it before the next
        # call — SQLAlchemy's identity map hands back the same object.
        assert getattr(first, "_attached") is False

        second = service.save_lead_from_watch(watch, _post_data("promo_two"))

        assert second.id == first_id
        assert getattr(second, "_attached") is True
        assert db_session.query(LeadPost).count() == 1

    def test_attached_post_is_preserved_as_a_profile_item(
        self, db_session, setup_provider, author, watch
    ):
        """The attached post's content survives as a profile_item."""
        from rediska_core.domain.models import ProfileItem
        from rediska_core.domain.services.scout_watch import ScoutWatchService

        service = ScoutWatchService(db_session)

        service.save_lead_from_watch(watch, _post_data("item_one"))
        service.save_lead_from_watch(watch, _post_data("item_two"))

        item_ids = {
            item.external_item_id
            for item in db_session.query(ProfileItem)
            .filter(ProfileItem.account_id == author.id)
            .all()
        }
        assert "item_two" in item_ids

    def test_resaving_the_same_post_is_not_an_attach(
        self, db_session, setup_provider, author, watch
    ):
        """Re-promoting the same post keeps per-post semantics."""
        from rediska_core.domain.services.scout_watch import ScoutWatchService

        service = ScoutWatchService(db_session)

        first = service.save_lead_from_watch(watch, _post_data("same_promo"))
        again = service.save_lead_from_watch(watch, _post_data("same_promo"))

        assert again.id == first.id
        assert getattr(again, "_attached") is False

    def test_ignored_author_gets_a_fresh_lead_not_a_revival(
        self, db_session, setup_provider, author, watch
    ):
        """Manual promotion of an ignored author creates a new lead."""
        from rediska_core.domain.services.leads import LeadsService
        from rediska_core.domain.services.scout_watch import ScoutWatchService

        service = ScoutWatchService(db_session)

        first = service.save_lead_from_watch(watch, _post_data("rev_one"))
        LeadsService(db_session).update_status(first.id, "ignored")

        second = service.save_lead_from_watch(watch, _post_data("rev_two"))

        assert second.id != first.id
        assert getattr(second, "_attached") is False

    def test_authorless_posts_never_attach(self, db_session, setup_provider, watch):
        """Posts with no author keep per-post semantics."""
        from rediska_core.domain.services.scout_watch import ScoutWatchService

        service = ScoutWatchService(db_session)

        first = service.save_lead_from_watch(
            watch, _post_data("anon_one", author_username=None)
        )
        second = service.save_lead_from_watch(
            watch, _post_data("anon_two", author_username=None)
        )

        assert first.id != second.id
        assert getattr(second, "_attached") is False


# =============================================================================
# CONTENT-CHANGE RE-ANALYSIS
# =============================================================================


class TestIgnoredVerdictIsContentSensitive:
    """An ignored author is only skipped for content already analysed."""

    @pytest.fixture
    def ignored_author(self, db_session, setup_provider, author):
        """An author whose only lead was ignored."""
        from rediska_core.domain.services.leads import LeadsService

        leads_service = LeadsService(db_session)
        lead = leads_service.save_lead(
            provider_id="reddit",
            source_location="r/watched",
            external_post_id="rejected_post",
            post_url="https://reddit.com/comments/rejected_post",
            title="Original title",
            body_text="Original body text",
            author_username="watched_author",
        )
        leads_service.update_status(lead.id, "ignored")
        return lead

    def test_same_content_is_still_skipped(self, db_session, ignored_author):
        """A crosspost of already-analysed text stays skipped."""
        from rediska_core.domain.services.scout_watch import (
            SKIP_LEAD_IGNORED,
            ScoutWatchService,
        )

        service = ScoutWatchService(db_session)

        assert (
            service.check_author_verdict(
                "reddit",
                "watched_author",
                post_title="Original title",
                post_body="Original body text",
            )
            == SKIP_LEAD_IGNORED
        )

    def test_whitespace_and_case_differences_are_not_content_changes(
        self, db_session, ignored_author
    ):
        """Trivial reformatting must not trigger a costly re-analysis."""
        from rediska_core.domain.services.scout_watch import (
            SKIP_LEAD_IGNORED,
            ScoutWatchService,
        )

        service = ScoutWatchService(db_session)

        assert (
            service.check_author_verdict(
                "reddit",
                "watched_author",
                post_title="ORIGINAL   Title",
                post_body="Original\n\nbody   text",
            )
            == SKIP_LEAD_IGNORED
        )

    def test_new_content_is_reanalysed(self, db_session, ignored_author):
        """A genuinely different post gets another look."""
        from rediska_core.domain.services.scout_watch import ScoutWatchService

        service = ScoutWatchService(db_session)

        assert (
            service.check_author_verdict(
                "reddit",
                "watched_author",
                post_title="Now looking for something completely different",
                post_body="My situation changed and so did what I want",
            )
            is None
        )

    def test_missing_content_falls_back_to_the_author_verdict(
        self, db_session, ignored_author
    ):
        """With nothing to compare, the standing verdict still applies."""
        from rediska_core.domain.services.scout_watch import (
            SKIP_LEAD_IGNORED,
            ScoutWatchService,
        )

        service = ScoutWatchService(db_session)

        assert (
            service.check_author_verdict("reddit", "watched_author")
            == SKIP_LEAD_IGNORED
        )

    def test_content_already_analysed_via_a_scout_post_is_skipped(
        self, db_session, setup_provider, author, watch, ignored_author
    ):
        """Analysis recorded on a scout sighting also counts as already seen."""
        from rediska_core.domain.models import ScoutWatchPost
        from rediska_core.domain.services.scout_watch import (
            SKIP_LEAD_IGNORED,
            ScoutWatchService,
        )

        db_session.add(
            ScoutWatchPost(
                watch_id=watch.id,
                external_post_id="seen_elsewhere",
                post_title="Seen by another watch",
                post_body="Judged already",
                post_author="watched_author",
                first_seen_at=datetime.now(timezone.utc),
                analysis_status="analyzed",
                analysis_recommendation="not_recommended",
            )
        )
        db_session.flush()

        service = ScoutWatchService(db_session)

        assert (
            service.check_author_verdict(
                "reddit",
                "watched_author",
                post_title="Seen by another watch",
                post_body="Judged already",
            )
            == SKIP_LEAD_IGNORED
        )

    def test_do_not_contact_ignores_content_entirely(
        self, db_session, setup_provider, author
    ):
        """Do-not-contact is about the relationship, not the post."""
        from rediska_core.domain.services.scout_watch import (
            SKIP_DO_NOT_CONTACT,
            ScoutWatchService,
        )

        db_session.add(
            DoNotContact(provider_id="reddit", external_username="watched_author")
        )
        db_session.flush()

        service = ScoutWatchService(db_session)

        assert (
            service.check_author_verdict(
                "reddit",
                "watched_author",
                post_title="Brand new content",
                post_body="Never seen before",
            )
            == SKIP_DO_NOT_CONTACT
        )

    def test_contacted_author_ignores_content_entirely(
        self, db_session, setup_provider, author
    ):
        """Already talking to them — new content does not change that."""
        from rediska_core.domain.services.scout_watch import (
            SKIP_ALREADY_CONTACTED,
            ScoutWatchService,
        )

        author.contact_state = "contacted"
        db_session.flush()

        service = ScoutWatchService(db_session)

        assert (
            service.check_author_verdict(
                "reddit",
                "watched_author",
                post_title="Brand new content",
                post_body="Never seen before",
            )
            == SKIP_ALREADY_CONTACTED
        )


class TestContentFingerprint:
    """Tests for the content fingerprint helper."""

    def test_identical_content_matches(self):
        from rediska_core.domain.services.scout_watch import content_fingerprint

        assert content_fingerprint("Title", "Body") == content_fingerprint("Title", "Body")

    def test_case_and_whitespace_are_normalised(self):
        from rediska_core.domain.services.scout_watch import content_fingerprint

        assert content_fingerprint("A  Title", "The\tBody") == content_fingerprint(
            "a title", "the body"
        )

    def test_different_content_differs(self):
        from rediska_core.domain.services.scout_watch import content_fingerprint

        assert content_fingerprint("Title", "Body") != content_fingerprint(
            "Title", "Different body"
        )

    def test_empty_content_has_no_fingerprint(self):
        from rediska_core.domain.services.scout_watch import content_fingerprint

        assert content_fingerprint(None, None) is None
        assert content_fingerprint("", "   ") is None
