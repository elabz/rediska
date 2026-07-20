"""Unit tests for merging historical duplicate-author leads.

Covers the dry-run/apply split, FK repointing, soft-delete of losers,
and idempotency on re-run.
"""

from datetime import datetime, timedelta

import pytest

from rediska_core.domain.models import (
    AuditLog,
    ExternalAccount,
    LeadAnalysis,
    LeadPost,
    Provider,
    ScoutWatch,
    ScoutWatchPost,
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
        external_username="dup_author",
        remote_status="active",
    )
    db_session.add(account)
    db_session.flush()
    return account


BASE = datetime(2026, 1, 1, 12, 0, 0)


def _lead(db_session, account_id, external_post_id, days_old=0, status="saved"):
    """Create a lead directly, bypassing the author-dedupe in save_lead."""
    lead = LeadPost(
        provider_id="reddit",
        source_location="r/dupes",
        external_post_id=external_post_id,
        post_url=f"https://reddit.com/comments/{external_post_id}",
        author_account_id=account_id,
        post_created_at=BASE - timedelta(days=days_old),
        status=status,
        remote_visibility="unknown",
    )
    db_session.add(lead)
    db_session.flush()
    return lead


def _analysis(db_session, lead_id, account_id):
    """Attach an analysis record to a lead."""
    analysis = LeadAnalysis(
        lead_id=lead_id,
        account_id=account_id,
        status="completed",
        started_at=BASE,
        completed_at=BASE,
        prompt_versions_json={},
    )
    db_session.add(analysis)
    db_session.flush()
    return analysis


# =============================================================================
# DRY RUN
# =============================================================================


class TestMergeDryRun:
    """The default dry run reports without mutating."""

    def test_dry_run_reports_groups(self, db_session, setup_provider, author):
        """Duplicates are grouped with a survivor and losers."""
        from rediska_core.domain.services.leads import LeadsService

        newest = _lead(db_session, author.id, "newest", days_old=0)
        middle = _lead(db_session, author.id, "middle", days_old=5)
        oldest = _lead(db_session, author.id, "oldest", days_old=10)

        report = LeadsService(db_session).merge_duplicate_author_leads(dry_run=True)

        assert report["dry_run"] is True
        assert report["duplicate_groups"] == 1
        assert report["leads_merged"] == 2

        group = report["groups"][0]
        assert group["survivor_lead_id"] == newest.id
        assert set(group["merged_lead_ids"]) == {middle.id, oldest.id}

    def test_dry_run_mutates_nothing(self, db_session, setup_provider, author):
        """No rows are soft-deleted and no audit entries are written."""
        from rediska_core.domain.services.leads import LeadsService

        _lead(db_session, author.id, "one", days_old=0)
        _lead(db_session, author.id, "two", days_old=3)

        LeadsService(db_session).merge_duplicate_author_leads(dry_run=True)

        assert db_session.query(LeadPost).filter(LeadPost.deleted_at.isnot(None)).count() == 0
        assert (
            db_session.query(AuditLog)
            .filter(AuditLog.action_type == "lead.merge_duplicates")
            .count()
            == 0
        )

    def test_single_lead_author_is_not_a_group(self, db_session, setup_provider, author):
        """An author with one lead needs no merge."""
        from rediska_core.domain.services.leads import LeadsService

        _lead(db_session, author.id, "solo", days_old=0)

        report = LeadsService(db_session).merge_duplicate_author_leads(dry_run=True)

        assert report["duplicate_groups"] == 0
        assert report["groups"] == []


# =============================================================================
# APPLIED MERGE
# =============================================================================


class TestMergeApplied:
    """An applied merge repoints history and soft-deletes losers."""

    def test_newest_post_survives_and_losers_are_soft_deleted(
        self, db_session, setup_provider, author
    ):
        """One lead survives; the rest are soft-deleted, never removed."""
        from rediska_core.domain.services.leads import LeadsService

        newest = _lead(db_session, author.id, "newest", days_old=0)
        middle = _lead(db_session, author.id, "middle", days_old=5)
        oldest = _lead(db_session, author.id, "oldest", days_old=10)

        LeadsService(db_session).merge_duplicate_author_leads(dry_run=False)

        assert newest.deleted_at is None
        assert middle.deleted_at is not None
        assert oldest.deleted_at is not None
        # Soft delete only — the rows are still there.
        assert db_session.query(LeadPost).count() == 3

    def test_analyses_are_repointed_to_the_survivor(
        self, db_session, setup_provider, author
    ):
        """Analysis history accumulates on the surviving lead."""
        from rediska_core.domain.services.leads import LeadsService

        newest = _lead(db_session, author.id, "newest", days_old=0)
        loser = _lead(db_session, author.id, "loser", days_old=5)

        survivor_analysis = _analysis(db_session, newest.id, author.id)
        loser_analysis = _analysis(db_session, loser.id, author.id)

        LeadsService(db_session).merge_duplicate_author_leads(dry_run=False)
        db_session.expire_all()

        assert db_session.get(LeadAnalysis, survivor_analysis.id).lead_id == newest.id
        assert db_session.get(LeadAnalysis, loser_analysis.id).lead_id == newest.id

    def test_scout_posts_are_repointed_to_the_survivor(
        self, db_session, setup_provider, author
    ):
        """Both scout posts end up linked to the single surviving lead."""
        from rediska_core.domain.services.leads import LeadsService

        newest = _lead(db_session, author.id, "newest", days_old=0)
        loser = _lead(db_session, author.id, "loser", days_old=5)

        watch = ScoutWatch(
            provider_id="reddit",
            source_location="r/dupes",
            sort_by="new",
            time_filter="day",
            auto_analyze=True,
            min_confidence=0.7,
            is_active=True,
        )
        db_session.add(watch)
        db_session.flush()

        scout_post = ScoutWatchPost(
            watch_id=watch.id,
            external_post_id="loser",
            first_seen_at=BASE,
            analysis_status="analyzed",
            lead_id=loser.id,
        )
        db_session.add(scout_post)
        db_session.flush()

        LeadsService(db_session).merge_duplicate_author_leads(dry_run=False)
        db_session.expire_all()

        assert db_session.get(ScoutWatchPost, scout_post.id).lead_id == newest.id

    def test_merge_is_audit_logged_per_group(self, db_session, setup_provider, author):
        """Each merge group writes one audit entry naming the losers."""
        from rediska_core.domain.services.leads import LeadsService

        newest = _lead(db_session, author.id, "newest", days_old=0)
        loser = _lead(db_session, author.id, "loser", days_old=5)

        LeadsService(db_session).merge_duplicate_author_leads(dry_run=False)

        entries = (
            db_session.query(AuditLog)
            .filter(AuditLog.action_type == "lead.merge_duplicates")
            .all()
        )
        assert len(entries) == 1
        assert entries[0].entity_id == newest.id
        assert entries[0].response_json == {"merged_lead_ids": [loser.id]}

    def test_ignored_leads_are_left_alone(self, db_session, setup_provider, author):
        """Ignored leads are not active, so they are neither survivor nor loser."""
        from rediska_core.domain.services.leads import LeadsService

        ignored = _lead(db_session, author.id, "ignored", days_old=0, status="ignored")
        active = _lead(db_session, author.id, "active", days_old=5)

        report = LeadsService(db_session).merge_duplicate_author_leads(dry_run=False)

        assert report["duplicate_groups"] == 0
        assert ignored.deleted_at is None
        assert active.deleted_at is None

    def test_different_authors_are_never_merged(self, db_session, setup_provider, author):
        """Grouping is per author."""
        from rediska_core.domain.services.leads import LeadsService

        other = ExternalAccount(
            provider_id="reddit",
            external_username="other_author",
            remote_status="active",
        )
        db_session.add(other)
        db_session.flush()

        mine = _lead(db_session, author.id, "mine", days_old=0)
        theirs = _lead(db_session, other.id, "theirs", days_old=5)

        report = LeadsService(db_session).merge_duplicate_author_leads(dry_run=False)

        assert report["duplicate_groups"] == 0
        assert mine.deleted_at is None
        assert theirs.deleted_at is None

    def test_rerun_is_idempotent(self, db_session, setup_provider, author):
        """A second run finds nothing left to merge."""
        from rediska_core.domain.services.leads import LeadsService

        _lead(db_session, author.id, "newest", days_old=0)
        _lead(db_session, author.id, "loser", days_old=5)

        service = LeadsService(db_session)
        first = service.merge_duplicate_author_leads(dry_run=False)
        second = service.merge_duplicate_author_leads(dry_run=False)

        assert first["leads_merged"] == 1
        assert second["duplicate_groups"] == 0
        assert second["leads_merged"] == 0
        assert (
            db_session.query(AuditLog)
            .filter(AuditLog.action_type == "lead.merge_duplicates")
            .count()
            == 1
        )


# =============================================================================
# ANALYSIS RETENTION
# =============================================================================


class TestAnalysisRetention:
    """Analysis output is never destroyed by retention or merge."""

    def test_merge_never_deletes_analyses(self, db_session, setup_provider, author):
        """Every analysis row survives a merge — none are dropped."""
        from rediska_core.domain.services.leads import LeadsService

        newest = _lead(db_session, author.id, "newest", days_old=0)
        loser = _lead(db_session, author.id, "loser", days_old=5)
        _analysis(db_session, newest.id, author.id)
        _analysis(db_session, loser.id, author.id)

        before = db_session.query(LeadAnalysis).count()
        LeadsService(db_session).merge_duplicate_author_leads(dry_run=False)

        assert db_session.query(LeadAnalysis).count() == before

    def test_history_cleanup_retains_posts_with_analysis(
        self, db_session, setup_provider, author
    ):
        """Expiring a run must not take its analysed posts with it."""
        from datetime import timezone

        from rediska_core.domain.models import ScoutWatchRun
        from rediska_core.domain.services.scout_watch import ScoutWatchService

        watch = ScoutWatch(
            provider_id="reddit",
            source_location="r/dupes",
            sort_by="new",
            time_filter="day",
            auto_analyze=True,
            min_confidence=0.7,
            is_active=True,
        )
        db_session.add(watch)
        db_session.flush()

        old_run = ScoutWatchRun(
            watch_id=watch.id,
            started_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            status="completed",
        )
        db_session.add(old_run)
        db_session.flush()

        analysed = ScoutWatchPost(
            watch_id=watch.id,
            run_id=old_run.id,
            external_post_id="analysed",
            first_seen_at=datetime(2020, 1, 1),
            analysis_status="analyzed",
            analysis_recommendation="not_recommended",
            dimension_results_json={"demographics": {"age": 30}},
        )
        bare = ScoutWatchPost(
            watch_id=watch.id,
            run_id=old_run.id,
            external_post_id="bare",
            first_seen_at=datetime(2020, 1, 1),
            analysis_status="skipped",
        )
        db_session.add_all([analysed, bare])
        db_session.flush()
        analysed_id, bare_id = analysed.id, bare.id

        result = ScoutWatchService(db_session).delete_old_runs(retention_days=3)

        assert result["runs_deleted"] == 1
        assert result["posts_retained"] == 1
        assert result["posts_deleted"] == 1

        db_session.expire_all()
        survivor = db_session.get(ScoutWatchPost, analysed_id)
        assert survivor is not None
        assert survivor.dimension_results_json == {"demographics": {"age": 30}}
        assert survivor.run_id is None
        assert db_session.get(ScoutWatchPost, bare_id) is None
