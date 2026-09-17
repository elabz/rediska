"""Unit tests for lead-triage-and-feedback.

Covers:
1. New model fields round-trip
2. Lead listing: priority-first ordering, expired exclusion, sort override
3. Auto-expiry (scout-only, dry run, disabled, audit)
4. Needs-review queue (filter, keyset pagination, dismiss)
5. Retention: needs-review posts are never purged, dismissed or not
6. Calibration report computation over seeded data
"""

from datetime import datetime, timedelta

import pytest

from rediska_core.domain.models import (
    AnalysisDimension,
    AuditLog,
    CalibrationReport,
    ExternalAccount,
    LeadAnalysis,
    LeadPost,
    Provider,
    ScoutWatch,
    ScoutWatchPost,
    ScoutWatchRun,
)
from rediska_core.domain.services.calibration_report import CalibrationReportService
from rediska_core.domain.services.leads import VALID_STATUSES, LeadsService
from rediska_core.domain.services.scout_watch import ScoutWatchError, ScoutWatchService

NOW = datetime(2026, 9, 16, 12, 0, 0)


# =============================================================================
# FIXTURES / HELPERS
# =============================================================================


@pytest.fixture
def provider(db_session):
    p = Provider(provider_id="reddit", display_name="Reddit", enabled=True)
    db_session.add(p)
    db_session.flush()
    return p


@pytest.fixture
def watch(db_session, provider):
    w = ScoutWatch(
        provider_id="reddit",
        source_location="r/test_triage",
        sort_by="new",
        time_filter="day",
        min_confidence=0.7,
    )
    db_session.add(w)
    db_session.flush()
    return w


_seq = {"n": 0}


def _lead(
    db_session,
    *,
    status="new",
    priority=None,
    lead_source="scout_watch",
    days_old=0,
    watch=None,
    recommendation=None,
    author=None,
    deleted=False,
):
    _seq["n"] += 1
    n = _seq["n"]
    lead = LeadPost(
        provider_id="reddit",
        source_location="r/test_triage",
        external_post_id=f"test_lead_{n}",
        post_url=f"https://reddit.com/comments/test_lead_{n}",
        title=f"test lead {n}",
        status=status,
        priority=priority,
        lead_source=lead_source,
        scout_watch_id=watch.id if watch else None,
        analysis_recommendation=recommendation,
        author_account_id=author.id if author else None,
        remote_visibility="unknown",
        created_at=NOW - timedelta(days=days_old),
        deleted_at=NOW if deleted else None,
    )
    db_session.add(lead)
    db_session.flush()
    return lead


def _post(
    db_session,
    watch,
    *,
    recommendation="needs_review",
    status="analyzed",
    minutes_old=0,
    dismissed=False,
    triaged=False,
    lead=None,
    results=None,
    run=None,
):
    _seq["n"] += 1
    post = ScoutWatchPost(
        watch_id=watch.id,
        run_id=run.id if run else None,
        external_post_id=f"test_post_{_seq['n']}",
        post_title="test post",
        post_author="test_author",
        first_seen_at=NOW - timedelta(minutes=minutes_old),
        analysis_status=status,
        analysis_recommendation=recommendation,
        dismissed_at=NOW if dismissed else None,
        triaged_at=NOW if triaged else None,
        lead_id=lead.id if lead else None,
        **({"dimension_results_json": results} if results is not None else {}),
    )
    db_session.add(post)
    db_session.flush()
    return post


def _account(db_session, name, *, contacted=False, engaged=False):
    account = ExternalAccount(
        provider_id="reddit",
        external_username=name,
        remote_status="active",
        contact_state="contacted" if contacted else "not_contacted",
        engagement_state="engaged" if engaged else "not_engaged",
    )
    db_session.add(account)
    db_session.flush()
    return account


# =============================================================================
# MODEL FIELDS
# =============================================================================


class TestModelFields:
    def test_lead_priority_and_expired_round_trip(self, db_session, provider):
        lead = _lead(db_session, status="expired", priority="high")
        lead.compatibility_score = 0.9
        db_session.commit()
        db_session.expire_all()

        stored = db_session.get(LeadPost, lead.id)
        assert stored.status == "expired"
        assert stored.priority == "high"
        assert stored.compatibility_score == 0.9

    def test_scout_post_triage_markers_default_null(self, db_session, watch):
        post = _post(db_session, watch)
        assert post.dismissed_at is None
        assert post.triaged_at is None

    def test_calibration_report_row(self, db_session):
        row = CalibrationReport(
            period_start=NOW - timedelta(days=7),
            period_end=NOW,
            report_json={"overall": {}},
        )
        db_session.add(row)
        db_session.flush()
        assert row.id is not None
        assert row.created_at is not None

    def test_expired_is_a_valid_status(self):
        assert "expired" in VALID_STATUSES


# =============================================================================
# LISTING
# =============================================================================


class TestListing:
    def test_default_order_is_priority_then_recency(self, db_session, provider):
        low_new = _lead(db_session, priority="low", days_old=0)
        unranked = _lead(db_session, priority=None, days_old=0)
        high_old = _lead(db_session, priority="high", days_old=5)
        medium = _lead(db_session, priority="medium", days_old=1)
        high_new = _lead(db_session, priority="high", days_old=1)

        ids = [lead.id for lead in LeadsService(db_session).list_leads()]
        assert ids == [high_new.id, high_old.id, medium.id, low_new.id, unranked.id]

    def test_newest_sort_ignores_priority(self, db_session, provider):
        older_high = _lead(db_session, priority="high", days_old=3)
        newer_low = _lead(db_session, priority="low", days_old=0)

        ids = [lead.id for lead in LeadsService(db_session).list_leads(sort="newest")]
        assert ids == [newer_low.id, older_high.id]

    def test_expired_hidden_by_default_and_listed_on_request(self, db_session, provider):
        active = _lead(db_session, status="new")
        expired = _lead(db_session, status="expired")
        service = LeadsService(db_session)

        assert [lead.id for lead in service.list_leads()] == [active.id]
        assert service.count_leads() == 1
        assert [lead.id for lead in service.list_leads(status="expired")] == [expired.id]
        assert service.count_leads(status="expired") == 1

    def test_soft_deleted_leads_are_not_listed_or_counted(self, db_session, provider):
        active = _lead(db_session)
        _lead(db_session, deleted=True)
        _lead(db_session, status="expired", deleted=True)
        service = LeadsService(db_session)

        assert [lead.id for lead in service.list_leads()] == [active.id]
        assert service.count_leads() == 1
        assert service.count_leads(status="expired") == 0

    def test_posted_within_days_uses_post_date_then_save_date(self, db_session, provider):
        now = datetime.utcnow()
        recent_post = _lead(db_session)
        recent_post.post_created_at = now - timedelta(days=3)
        old_post_new_save = _lead(db_session)  # saved now, but posted a month ago
        old_post_new_save.created_at = now
        old_post_new_save.post_created_at = now - timedelta(days=30)
        undated_recent = _lead(db_session)
        undated_recent.created_at = now - timedelta(days=10)
        undated_old = _lead(db_session)
        undated_old.created_at = now - timedelta(days=20)
        db_session.flush()
        service = LeadsService(db_session)

        within_14 = {lead.id for lead in service.list_leads(posted_within_days=14)}
        assert within_14 == {recent_post.id, undated_recent.id}
        assert service.count_leads(posted_within_days=14) == 2
        assert service.count_leads(posted_within_days=7) == 1
        assert service.count_leads() == 4

    def test_revive_expired_lead(self, db_session, provider):
        lead = _lead(db_session, status="expired")
        service = LeadsService(db_session)
        service.update_status(lead.id, "saved")
        assert [row.id for row in service.list_leads()] == [lead.id]

    def test_expired_lead_is_not_active_for_author_dedupe(self, db_session, provider):
        author = _account(db_session, "test_expired_author")
        _lead(db_session, status="expired", author=author)
        assert LeadsService(db_session).get_active_lead_for_author("reddit", author.id) is None


# =============================================================================
# AUTO-EXPIRY
# =============================================================================


class TestExpiry:
    def _seed(self, db_session):
        return {
            "stale_scout": _lead(db_session, days_old=20),
            "fresh_scout": _lead(db_session, days_old=3),
            "stale_manual": _lead(db_session, lead_source="manual", days_old=40),
            "stale_saved": _lead(db_session, status="saved", days_old=40),
            "stale_deleted": _lead(db_session, days_old=40, deleted=True),
        }

    def test_expires_only_stale_untouched_scout_leads(self, db_session, provider):
        leads = self._seed(db_session)
        result = LeadsService(db_session).expire_stale_leads(14, dry_run=False, now=NOW)

        assert result["count"] == 1
        assert result["lead_ids"] == [leads["stale_scout"].id]
        db_session.expire_all()
        assert db_session.get(LeadPost, leads["stale_scout"].id).status == "expired"
        assert db_session.get(LeadPost, leads["fresh_scout"].id).status == "new"
        assert db_session.get(LeadPost, leads["stale_manual"].id).status == "new"
        assert db_session.get(LeadPost, leads["stale_saved"].id).status == "saved"
        assert db_session.get(LeadPost, leads["stale_deleted"].id).status == "new"

        audit = db_session.query(AuditLog).filter(AuditLog.action_type == "lead.expire").all()
        assert len(audit) == 1
        assert audit[0].actor == "system"
        assert audit[0].response_json["lead_ids"] == [leads["stale_scout"].id]

    def test_dry_run_reports_without_mutating(self, db_session, provider):
        leads = self._seed(db_session)
        result = LeadsService(db_session).expire_stale_leads(14, dry_run=True, now=NOW)

        assert result["dry_run"] is True
        assert result["count"] == 1
        db_session.expire_all()
        assert db_session.get(LeadPost, leads["stale_scout"].id).status == "new"
        assert (
            db_session.query(AuditLog).filter(AuditLog.action_type == "lead.expire").count()
            == 0
        )
        dry = (
            db_session.query(AuditLog)
            .filter(AuditLog.action_type == "lead.expire_dry_run")
            .one()
        )
        assert dry.response_json == {"would_expire": 1}

    def test_zero_days_disables(self, db_session, provider):
        leads = self._seed(db_session)
        result = LeadsService(db_session).expire_stale_leads(0, dry_run=False, now=NOW)

        assert result["disabled"] is True
        assert result["count"] == 0
        db_session.expire_all()
        assert db_session.get(LeadPost, leads["stale_scout"].id).status == "new"

    def test_audit_is_batched(self, db_session, provider, monkeypatch):
        import rediska_core.domain.services.leads as leads_module

        monkeypatch.setattr(leads_module, "EXPIRY_AUDIT_BATCH", 2)
        for _ in range(5):
            _lead(db_session, days_old=30)

        result = LeadsService(db_session).expire_stale_leads(14, dry_run=False, now=NOW)
        assert result["count"] == 5
        rows = db_session.query(AuditLog).filter(AuditLog.action_type == "lead.expire").all()
        assert sorted(len(r.response_json["lead_ids"]) for r in rows) == [1, 2, 2]


# =============================================================================
# NEEDS-REVIEW QUEUE
# =============================================================================


class TestNeedsReviewQueue:
    def test_queue_filters_untriaged_needs_review(self, db_session, watch):
        lead = _lead(db_session)
        pending = _post(db_session, watch, minutes_old=1)
        _post(db_session, watch, recommendation="suitable")
        _post(db_session, watch, recommendation="not_recommended")
        _post(db_session, watch, dismissed=True)
        _post(db_session, watch, triaged=True)
        _post(db_session, watch, lead=lead)
        _post(db_session, watch, status="failed")

        service = ScoutWatchService(db_session)
        posts, next_cursor = service.list_needs_review()
        assert [p.id for p in posts] == [pending.id]
        assert next_cursor is None
        assert service.count_needs_review() == 1

    def test_queue_spans_watches_newest_first(self, db_session, watch):
        other = ScoutWatch(provider_id="reddit", source_location="r/test_other")
        db_session.add(other)
        db_session.flush()
        older = _post(db_session, watch, minutes_old=10)
        newer = _post(db_session, other, minutes_old=1)

        posts, _ = ScoutWatchService(db_session).list_needs_review()
        assert [p.id for p in posts] == [newer.id, older.id]

        only_first, _ = ScoutWatchService(db_session).list_needs_review(watch_id=watch.id)
        assert [p.id for p in only_first] == [older.id]

    def test_keyset_pagination_covers_ties(self, db_session, watch):
        # Two posts share a timestamp so the id tiebreak is exercised.
        a = _post(db_session, watch, minutes_old=5)
        b = _post(db_session, watch, minutes_old=5)
        c = _post(db_session, watch, minutes_old=1)
        service = ScoutWatchService(db_session)

        page1, cursor = service.list_needs_review(limit=2)
        assert [p.id for p in page1] == [c.id, b.id]
        assert cursor is not None
        page2, cursor2 = service.list_needs_review(cursor=cursor, limit=2)
        assert [p.id for p in page2] == [a.id]
        assert cursor2 is None

    def test_malformed_cursor_raises_value_error(self, db_session, watch):
        with pytest.raises(ValueError):
            ScoutWatchService(db_session).list_needs_review(cursor="garbage")

    def test_dismiss_removes_from_queue(self, db_session, watch):
        post = _post(db_session, watch)
        service = ScoutWatchService(db_session)
        service.dismiss_post(post)

        assert post.dismissed_at is not None
        assert service.count_needs_review() == 0

    def test_dismiss_promoted_post_is_refused(self, db_session, watch):
        post = _post(db_session, watch, lead=_lead(db_session))
        with pytest.raises(ScoutWatchError):
            ScoutWatchService(db_session).dismiss_post(post)


# =============================================================================
# RETENTION
# =============================================================================


class TestNeedsReviewRetention:
    def test_old_needs_review_posts_survive_cleanup(self, db_session, watch):
        old = datetime.utcnow() - timedelta(days=5)
        run = ScoutWatchRun(watch_id=watch.id, started_at=old, status="completed")
        db_session.add(run)
        db_session.flush()
        untriaged = _post(db_session, watch, run=run, results={"gate_verdict": {}})
        dismissed = _post(db_session, watch, run=run, dismissed=True, results={"gate_verdict": {}})
        post_ids = [untriaged.id, dismissed.id]

        result = ScoutWatchService(db_session).delete_old_runs(retention_days=3)

        assert result["posts_deleted"] == 0
        db_session.expire_all()
        survivors = db_session.query(ScoutWatchPost).filter(ScoutWatchPost.id.in_(post_ids)).all()
        assert len(survivors) == 2
        assert ScoutWatchService(db_session).count_needs_review() == 1


# =============================================================================
# CALIBRATION REPORT
# =============================================================================


GATE_VERDICT_UNCLEAR = {
    "recommendation": "needs_review",
    "score": 0.5,
    "gate_results": [
        {"gate": "gender", "status": "pass", "reason": ""},
        {"gate": "location", "status": "unclear", "reason": ""},
    ],
}


class TestCalibrationReport:
    def _seed(self, db_session, watch):
        contacted = _account(db_session, "test_contacted", contacted=True)
        engaged = _account(db_session, "test_engaged", contacted=True, engaged=True)

        # Leads: 4 suitable from the watch (2 ignored, 1 contacted, 1 engaged),
        # 1 manual, 1 outside the cohort window.
        _lead(db_session, watch=watch, recommendation="suitable", status="ignored", days_old=2)
        _lead(db_session, watch=watch, recommendation="suitable", status="ignored", days_old=2)
        _lead(db_session, watch=watch, recommendation="suitable", status="contacted", author=contacted, days_old=2)
        _lead(db_session, watch=watch, recommendation="suitable", status="new", author=engaged, days_old=2)
        _lead(db_session, lead_source="manual", recommendation="suitable", status="saved", days_old=1)
        _lead(db_session, watch=watch, recommendation="suitable", status="ignored", days_old=60)

        # Posts in the period: 2 needs_review (1 dismissed), 1 promoted, 1 suitable
        # with a missing dimension, and 1 older than the period.
        full = {dim: {"x": 1} for dim in ("demographics", "preferences", "relationship_goals", "risk_flags", "sexual_preferences")}
        _post(db_session, watch, results={**full, "gate_verdict": GATE_VERDICT_UNCLEAR})
        _post(db_session, watch, dismissed=True, results={**full, "gate_verdict": GATE_VERDICT_UNCLEAR})
        _post(db_session, watch, triaged=True, lead=_lead(db_session, watch=watch, days_old=90), results={"gate_verdict": {}})
        missing_prefs = {k: v for k, v in full.items() if k != "preferences"}
        _post(db_session, watch, recommendation="suitable", results=missing_prefs)
        _post(db_session, watch, minutes_old=60 * 24 * 10)

        analysis = LeadAnalysis(
            lead_id=_lead(db_session, days_old=100).id,
            account_id=contacted.id,
            status="completed",
            started_at=NOW,
            prompt_versions_json={},
        )
        db_session.add(analysis)
        db_session.flush()
        for status in ("completed", "failed", "failed"):
            db_session.add(
                AnalysisDimension(
                    analysis_id=analysis.id,
                    dimension="relationship_goals",
                    started_at=NOW - timedelta(hours=1),
                    status=status,
                    input_data_json={},
                    prompt_version=1,
                )
            )
        db_session.flush()

    def test_compute_rates(self, db_session, watch):
        self._seed(db_session, watch)
        report = CalibrationReportService(db_session).compute(period_end=NOW + timedelta(minutes=1))

        overall = report["overall"]
        leads = overall["leads"]
        # Cohort excludes the 60- and 90-day-old leads.
        assert leads["suitable_leads"] == 5
        assert leads["suitable_ignored"] == 2
        assert leads["suitable_ignored_rate"] == 0.4
        assert leads["suitable_contacted"] == 2
        assert leads["contacted_engaged"] == 1
        assert leads["contacted_engaged_rate"] == 0.5

        posts = overall["posts"]
        assert posts["posts_analyzed"] == 4
        assert posts["recommendations"]["needs_review"] == 3
        assert posts["needs_review"] == {"total": 3, "promoted": 1, "dismissed": 1, "pending": 1}
        assert posts["gate_outcomes"]["location"]["unclear"] == 2
        assert posts["posts_without_gate_verdict"] == 2
        assert posts["dimension_failures"]["preferences"]["failed"] == 2
        # Queue size is not period-bound: the 10-day-old untriaged post counts.
        assert overall["needs_review_queue_size"] == 2
        assert overall["dimension_failures"]["relationship_goals"] == {
            "total": 3, "failed": 2, "rate": 0.6667,
        }

        (row,) = report["watches"]
        assert row["watch_id"] == watch.id
        assert row["leads"]["suitable_ignored_rate"] == 0.5
        assert overall["manual_leads"]["suitable_leads"] == 1

    def test_generate_stores_row(self, db_session, watch):
        report = CalibrationReportService(db_session).generate(period_end=NOW)
        assert report.id is not None
        assert report.period_end == NOW
        assert report.period_start == NOW - timedelta(days=7)
        assert CalibrationReportService(db_session).list_reports() == [report]

    def test_empty_data_has_null_rates(self, db_session, provider):
        report = CalibrationReportService(db_session).compute(period_end=NOW)
        assert report["overall"]["leads"]["suitable_ignored_rate"] is None
        assert report["watches"] == []
