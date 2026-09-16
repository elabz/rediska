"""Unit tests: evaluated scout posts (and their runs) survive history cleanup."""

from datetime import datetime, timedelta, timezone

import pytest

from rediska_core.domain.models import (
    Provider,
    ScoutWatch,
    ScoutWatchPost,
    ScoutWatchRun,
)
from rediska_core.domain.services.scout_watch import ScoutWatchService


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def watch(db_session):
    db_session.add(Provider(provider_id="reddit", display_name="Reddit", enabled=True))
    db_session.flush()
    w = ScoutWatch(provider_id="reddit", source_location="r/test_sub", sort_by="new", time_filter="day")
    db_session.add(w)
    db_session.flush()
    return w


def _run(db_session, watch, days_old):
    run = ScoutWatchRun(
        watch_id=watch.id,
        started_at=_now() - timedelta(days=days_old),
        completed_at=_now() - timedelta(days=days_old),
        status="completed",
    )
    db_session.add(run)
    db_session.flush()
    return run


def _post(db_session, watch, run, ext_id, *, analysed=True, evaluated=False):
    # Omit the JSON column entirely for sightings: passing None would store a
    # JSON ``null`` (not SQL NULL), which the retention predicate treats as
    # analysis output. Production inserts leave the column unset.
    extra = (
        {"analysis_recommendation": "not_recommended", "dimension_results_json": {"gate_verdict": {}}}
        if analysed
        else {}
    )
    post = ScoutWatchPost(
        watch_id=watch.id,
        run_id=run.id,
        external_post_id=ext_id,
        post_title=f"scout {ext_id}",
        first_seen_at=run.started_at,
        analysis_status="analyzed" if analysed else "skipped",
        evaluated_at=_now() if evaluated else None,
        **extra,
    )
    db_session.add(post)
    db_session.flush()
    return post


class TestDeleteOldRunsEvaluated:
    def test_evaluated_post_and_run_survive(self, db_session, watch):
        old_run = _run(db_session, watch, days_old=10)
        evaluated = _post(db_session, watch, old_run, "ev", evaluated=True)
        analysed_only = _post(db_session, watch, old_run, "an")
        sighting = _post(db_session, watch, old_run, "sg", analysed=False)

        other_old = _run(db_session, watch, days_old=10)
        other_sighting = _post(db_session, watch, other_old, "os", analysed=False)

        fresh = _run(db_session, watch, days_old=1)
        fresh_post = _post(db_session, watch, fresh, "fp", analysed=False)

        ids = {
            "old_run": old_run.id, "other_old": other_old.id, "fresh": fresh.id,
            "evaluated": evaluated.id, "analysed_only": analysed_only.id,
            "sighting": sighting.id, "other_sighting": other_sighting.id,
            "fresh_post": fresh_post.id,
        }

        result = ScoutWatchService(db_session).delete_old_runs(retention_days=3)

        assert result == {"runs_deleted": 1, "posts_deleted": 2, "posts_retained": 1}

        db_session.expunge_all()
        # Evaluated post kept, still attached to its (kept) run
        kept_eval = db_session.get(ScoutWatchPost, ids["evaluated"])
        assert kept_eval is not None and kept_eval.run_id == ids["old_run"]
        assert db_session.get(ScoutWatchRun, ids["old_run"]) is not None
        # Analysed-but-unevaluated post kept but detached (existing behaviour)
        kept = db_session.get(ScoutWatchPost, ids["analysed_only"])
        assert kept is not None and kept.run_id is None
        # Plain sightings on old runs are gone, and the run with nothing left is gone
        assert db_session.get(ScoutWatchPost, ids["sighting"]) is None
        assert db_session.get(ScoutWatchPost, ids["other_sighting"]) is None
        assert db_session.get(ScoutWatchRun, ids["other_old"]) is None
        # Fresh run untouched
        assert db_session.get(ScoutWatchRun, ids["fresh"]) is not None
        assert db_session.get(ScoutWatchPost, ids["fresh_post"]) is not None

    def test_unevaluated_old_post_is_deleted(self, db_session, watch):
        old_run = _run(db_session, watch, days_old=10)
        sighting = _post(db_session, watch, old_run, "sg", analysed=False)
        run_id, post_id = old_run.id, sighting.id
        result = ScoutWatchService(db_session).delete_old_runs(retention_days=3)
        assert result["posts_deleted"] == 1
        assert result["runs_deleted"] == 1
        db_session.expunge_all()
        assert db_session.get(ScoutWatchPost, post_id) is None
        assert db_session.get(ScoutWatchRun, run_id) is None
