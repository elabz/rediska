"""Unit tests for source trials, trial-watch isolation, and watch yield (source-discovery).

All data is synthetic.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from rediska_core.domain.models import (
    ExternalAccount,
    Job,
    LeadPost,
    Provider,
    ScoutWatch,
    ScoutWatchPost,
    ScoutWatchRun,
    SourceCandidate,
    SourceTrial,
)
from rediska_core.domain.services.source_discovery import (
    DiscoveryConflictError,
    DiscoveryError,
    SourceDiscoveryService,
)

NOW = datetime.utcnow()


@pytest.fixture
def provider(db_session):
    db_session.add(Provider(provider_id="reddit", display_name="Reddit", enabled=True))
    db_session.flush()


def make_candidate(db, name="r/test_candidate", kind="location", status="new"):
    c = SourceCandidate(
        provider_id="reddit", kind=kind, name=name, origin="mined", status=status,
        evidence_json={}, evidence_count=3, lift=2.0, created_at=NOW, updated_at=NOW,
    )
    db.add(c)
    db.flush()
    return c


def svc(db):
    return SourceDiscoveryService(db, min_qualified_authors=3, window_days=180, trial_sample=25)


def gate(*failures):
    return {
        "gate_verdict": {
            "recommendation": "not_recommended",
            "score": 0.2,
            "gate_results": [{"gate": g, "status": "fail", "reason": "x"} for g in failures],
        }
    }


# =============================================================================
# TRIAL CREATION / CANCELLATION
# =============================================================================


class TestStartTrial:
    def test_creates_hidden_watch_trial_and_job(self, db_session, provider):
        c = make_candidate(db_session)

        trial = svc(db_session).start_trial(c)

        watch = db_session.get(ScoutWatch, trial.watch_id)
        assert watch.is_trial is True and watch.is_active is False
        assert watch.source_location == "r/test_candidate"
        assert c.watch_id == watch.id
        assert trial.status == "queued" and trial.sample_size == 25
        job = db_session.get(Job, trial.job_id)
        assert job.dedupe_key == f"discovery.run_trial:{trial.id}"
        assert job.queue_name == "scout" and job.max_attempts == 1

    def test_reuses_trial_watch_on_second_trial(self, db_session, provider):
        c = make_candidate(db_session)
        s = svc(db_session)
        first = s.start_trial(c)
        first.status = "completed"
        db_session.flush()

        second = s.start_trial(c)

        assert second.watch_id == first.watch_id

    def test_second_trial_refused_while_one_runs(self, db_session, provider):
        a = make_candidate(db_session, "r/test_a")
        b = make_candidate(db_session, "r/test_b")
        s = svc(db_session)
        s.start_trial(a)

        with pytest.raises(DiscoveryConflictError):
            s.start_trial(b)
        assert db_session.query(SourceTrial).count() == 1
        assert db_session.query(Job).count() == 1

    def test_external_host_cannot_be_trialled(self, db_session, provider):
        host = make_candidate(db_session, "listings.example.test", kind="external_host")

        with pytest.raises(DiscoveryError, match="never fetched"):
            svc(db_session).start_trial(host)
        assert db_session.query(ScoutWatch).count() == 0

    def test_sample_size_capped(self, db_session, provider):
        with pytest.raises(DiscoveryError):
            svc(db_session).start_trial(make_candidate(db_session), sample_size=51)


class TestCancelTrial:
    def test_queued_trial_cancels_immediately(self, db_session, provider):
        s = svc(db_session)
        trial = s.start_trial(make_candidate(db_session))

        s.cancel_trial(trial)

        assert trial.status == "cancelled"
        assert db_session.get(Job, trial.job_id).status == "cancelled"

    def test_running_trial_is_cancelled_by_worker_then_forced(self, db_session, provider):
        s = svc(db_session)
        trial = s.start_trial(make_candidate(db_session))
        trial.status = "running"
        db_session.flush()

        s.cancel_trial(trial)
        assert trial.status == "running"  # worker stops between posts
        assert db_session.get(Job, trial.job_id).status == "cancelled"

        s.cancel_trial(trial)  # asked again: force (worker may have died)
        assert trial.status == "cancelled"


# =============================================================================
# YIELD REPORT
# =============================================================================


class TestTrialYield:
    def test_yield_numbers(self, db_session, provider):
        s = svc(db_session)
        c = make_candidate(db_session)
        trial = s.start_trial(c)
        run = ScoutWatchRun(watch_id=trial.watch_id, started_at=NOW, status="completed")
        db_session.add(run)
        db_session.flush()
        trial.run_id = run.id

        def post(i, status, rec=None, results=None):
            db_session.add(ScoutWatchPost(
                watch_id=trial.watch_id, run_id=run.id, external_post_id=f"test_y{i}",
                first_seen_at=NOW, analysis_status=status, analysis_recommendation=rec,
                dimension_results_json=results,
            ))

        i = 0
        for _ in range(4):
            post(i := i + 1, "analyzed", "suitable", gate())
        for _ in range(6):
            post(i := i + 1, "analyzed", "needs_review", gate())
        for n in range(10):
            post(i := i + 1, "analyzed", "not_recommended",
                 gate("location") if n < 7 else gate("gender"))
        post(i := i + 1, "skipped")
        post(i := i + 1, "failed")
        db_session.flush()

        report = s.build_trial_yield(
            trial, posts_fetched=25, skipped_empty=3, link_only_resolved=2,
            post_ages_hours=[1.0, 5.0, 9.0],
        )

        assert report["posts_fetched"] == 25
        assert report["skipped_empty"] == 3
        assert report["link_only_resolved"] == 2
        assert (report["suitable"], report["needs_review"], report["not_recommended"]) == (4, 6, 10)
        assert report["skipped_prior_verdict"] == 1 and report["failed"] == 1
        assert report["top_failing_gate"] == "location"
        assert report["top_failing_gate_count"] == 7
        assert report["median_post_age_hours"] == 5.0
        # A trial never creates leads by itself.
        assert db_session.query(LeadPost).count() == 0


# =============================================================================
# ACCEPT
# =============================================================================


class TestAccept:
    def test_accept_converts_trial_watch_in_place(self, db_session, provider):
        s = svc(db_session)
        c = make_candidate(db_session)
        trial = s.start_trial(c)
        trial.status = "completed"
        c.status = "trialled"
        db_session.add(ScoutWatchPost(
            watch_id=trial.watch_id, external_post_id="test_seen", first_seen_at=NOW,
            analysis_status="analyzed", analysis_recommendation="needs_review",
        ))
        db_session.flush()

        watch = s.accept(c, search_query="test query", sort_by="new", min_confidence=0.8)

        assert watch.id == trial.watch_id
        assert watch.is_trial is False and watch.is_active is True
        assert watch.search_query == "test query" and watch.min_confidence == 0.8
        assert c.status == "accepted" and c.watch_id == watch.id
        # Seen posts stay with the watch, so they are deduped, not re-analysed.
        from rediska_core.domain.services.scout_watch import ScoutWatchService
        assert ScoutWatchService(db_session).is_post_seen(watch.id, "test_seen")
        assert db_session.query(ScoutWatch).count() == 1

    def test_accept_without_trial_creates_exactly_one_watch(self, db_session, provider):
        s = svc(db_session)
        c = make_candidate(db_session)

        watch = s.accept(c)

        assert db_session.query(ScoutWatch).count() == 1
        assert watch.source_location == "r/test_candidate" and watch.is_trial is False
        with pytest.raises(DiscoveryConflictError):
            s.accept(c)
        assert db_session.query(ScoutWatch).count() == 1

    def test_accept_refused_while_trial_runs(self, db_session, provider):
        s = svc(db_session)
        c = make_candidate(db_session)
        s.start_trial(c)

        with pytest.raises(DiscoveryConflictError):
            s.accept(c)

    def test_dismissed_must_be_restored_first(self, db_session, provider):
        s = svc(db_session)
        c = make_candidate(db_session)
        s.dismiss(c)

        with pytest.raises(DiscoveryConflictError):
            s.accept(c)
        s.restore(c)
        assert c.status == "new"


# =============================================================================
# TRIAL POSTS STAY OFF SHARED SURFACES
# =============================================================================


@pytest.fixture
def trial_and_real(db_session, provider):
    real = ScoutWatch(provider_id="reddit", source_location="r/test_real")
    db_session.add(real)
    db_session.flush()
    c = make_candidate(db_session, "r/test_trialled")
    trial = svc(db_session).start_trial(c)
    trial.status = "completed"
    c.status = "trialled"
    db_session.flush()
    trial_watch = db_session.get(ScoutWatch, trial.watch_id)
    for watch in (real, trial_watch):
        db_session.add(ScoutWatchPost(
            watch_id=watch.id, external_post_id=f"test_s{watch.id}", first_seen_at=NOW,
            analysis_status="analyzed", analysis_recommendation="needs_review",
            dimension_results_json={"demographics": {"age": 30}, **gate()},
        ))
    db_session.flush()
    return real, trial_watch, c


class TestSurfaces:
    def test_calibration_report_excludes_trials(self, db_session, trial_and_real):
        from rediska_core.domain.services.calibration_report import CalibrationReportService

        real, trial_watch, _ = trial_and_real
        report = CalibrationReportService(db_session).compute(
            period_end=NOW + timedelta(hours=1)
        )

        assert [w["watch_id"] for w in report["watches"]] == [real.id]
        assert report["overall"]["needs_review_queue_size"] == 1

    def test_evaluation_queue_sampling_excludes_trials(self, db_session, trial_and_real):
        from rediska_core.domain.services.analysis_evaluation import AnalysisEvaluationService

        real, trial_watch, _ = trial_and_real
        candidates = AnalysisEvaluationService(db_session)._scout_candidates(None, None)

        assert {c.watch_id for c in candidates} == {real.id}

    def test_run_all_watches_source_skips_trials(self, db_session, trial_and_real):
        from rediska_core.domain.services.scout_watch import ScoutWatchService

        real, trial_watch, _ = trial_and_real
        trial_watch.is_active = True  # even if somehow activated
        db_session.flush()

        active = ScoutWatchService(db_session).list_watches(is_active=True)

        assert [w.id for w in active] == [real.id]


class TestHistoryCleanup:
    def _old_run(self, db, watch_id, ext):
        started = datetime.now(timezone.utc) - timedelta(days=10)
        run = ScoutWatchRun(watch_id=watch_id, started_at=started, status="completed")
        db.add(run)
        db.flush()
        db.add(ScoutWatchPost(
            watch_id=watch_id, run_id=run.id, external_post_id=ext, first_seen_at=started,
            analysis_status="skipped",
        ))
        db.flush()
        return run

    def test_unresolved_trial_runs_are_exempt_until_dismissed(self, db_session, trial_and_real):
        from rediska_core.domain.services.scout_watch import ScoutWatchService

        real, trial_watch, candidate = trial_and_real
        self._old_run(db_session, real.id, "test_old_real")
        trial_run_id = self._old_run(db_session, trial_watch.id, "test_old_trial").id

        result = ScoutWatchService(db_session).delete_old_runs(retention_days=3)

        assert result["runs_deleted"] == 1
        assert db_session.get(ScoutWatchRun, trial_run_id) is not None

        svc(db_session).dismiss(candidate)
        result = ScoutWatchService(db_session).delete_old_runs(retention_days=3)

        assert result["runs_deleted"] == 1
        db_session.expire_all()
        assert db_session.get(ScoutWatchRun, trial_run_id) is None


# =============================================================================
# WATCH YIELD
# =============================================================================


def _watch_with_posts(db, name, posts, suitable=0):
    watch = ScoutWatch(provider_id="reddit", source_location=name)
    db.add(watch)
    db.flush()
    for i in range(posts):
        db.add(ScoutWatchPost(
            watch_id=watch.id, external_post_id=f"{name}_{i}", first_seen_at=NOW,
            analysis_status="analyzed",
            analysis_recommendation="suitable" if i < suitable else "not_recommended",
        ))
    db.flush()
    return watch


class TestWatchYield:
    def test_low_yield_watch_is_visible(self, db_session, provider):
        watch = _watch_with_posts(db_session, "r/test_low", posts=400)

        y = svc(db_session).watch_yields([watch.id])[watch.id]

        assert y["posts_seen"] == 400
        assert y["suitable"] == 0 and y["not_recommended"] == 400
        assert y["leads_created"] == 0 and y["window_days"] == 30

    def test_leads_and_contact_outcomes(self, db_session, provider):
        watch = _watch_with_posts(db_session, "r/test_good", posts=3, suitable=2)
        for i, (contacted, engaged) in enumerate([(True, True), (True, False), (False, False)]):
            account = ExternalAccount(
                provider_id="reddit", external_username=f"test_y_{i}",
                contact_state="contacted" if contacted else "not_contacted",
                engagement_state="engaged" if engaged else "not_engaged",
            )
            db_session.add(account)
            db_session.flush()
            db_session.add(LeadPost(
                provider_id="reddit", source_location="r/test_good",
                external_post_id=f"test_yl_{i}", post_url="https://reddit.com/x",
                author_account_id=account.id, scout_watch_id=watch.id,
                lead_source="scout_watch",
            ))
        db_session.flush()

        y = svc(db_session).watch_yields([watch.id])[watch.id]

        assert y["suitable"] == 2
        assert (y["leads_created"], y["leads_contacted"], y["leads_engaged"]) == (3, 2, 1)

    def test_old_posts_outside_window(self, db_session, provider):
        watch = _watch_with_posts(db_session, "r/test_old", posts=0)
        db_session.add(ScoutWatchPost(
            watch_id=watch.id, external_post_id="test_old_1",
            first_seen_at=NOW - timedelta(days=45), analysis_status="analyzed",
            analysis_recommendation="suitable",
        ))
        db_session.flush()

        assert svc(db_session).watch_yields([watch.id])[watch.id]["posts_seen"] == 0

    def test_query_count_constant_as_watches_grow(self, db_session, provider, sync_engine):
        few = [_watch_with_posts(db_session, f"r/test_few_{i}", posts=2).id for i in range(2)]
        many = [_watch_with_posts(db_session, f"r/test_many_{i}", posts=2).id for i in range(12)]

        def count_queries(ids):
            statements = []
            listener = lambda *args: statements.append(args[2])  # noqa: E731
            event.listen(sync_engine, "before_cursor_execute", listener)
            try:
                svc(db_session).watch_yields(ids)
            finally:
                event.remove(sync_engine, "before_cursor_execute", listener)
            return len(statements)

        assert count_queries(few) == count_queries(few + many)
