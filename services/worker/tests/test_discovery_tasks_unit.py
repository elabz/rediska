"""Unit tests for source discovery worker tasks (source-discovery).

run_trial is exercised against an in-memory SQLite database with the Reddit
adapter and the per-post analysis replaced by fakes. All data is synthetic.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_CORE_PATH = Path(__file__).resolve().parents[2] / "core"
if str(_CORE_PATH) not in sys.path:
    sys.path.insert(0, str(_CORE_PATH))

from sqlalchemy import StaticPool, create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rediska_worker.tasks import discovery as discovery_module  # noqa: E402
from rediska_worker.tasks import scout as scout_module  # noqa: E402


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def session_factory():
    from sqlalchemy.dialects import sqlite

    from rediska_core.domain.models import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    original = sqlite.dialect.type_compiler_cls.visit_BIGINT
    sqlite.dialect.type_compiler_cls.visit_BIGINT = lambda self, type_, **kw: "INTEGER"
    try:
        Base.metadata.create_all(bind=engine)
    finally:
        sqlite.dialect.type_compiler_cls.visit_BIGINT = original
    yield sessionmaker(bind=engine)
    engine.dispose()


@pytest.fixture
def trial_setup(session_factory):
    """A location candidate with a queued trial (via the core service)."""
    from rediska_core.domain.models import Provider, SourceCandidate
    from rediska_core.domain.services.source_discovery import SourceDiscoveryService

    db = session_factory()
    db.add(Provider(provider_id="reddit", display_name="Reddit", enabled=True))
    now = datetime.utcnow()
    candidate = SourceCandidate(
        provider_id="reddit", kind="location", name="r/test_trial", origin="mined",
        status="new", evidence_json={}, evidence_count=3, lift=2.0,
        created_at=now, updated_at=now,
    )
    db.add(candidate)
    db.flush()
    trial = SourceDiscoveryService(db, trial_sample=25).start_trial(candidate, sample_size=4)
    db.commit()
    ids = {"trial_id": trial.id, "candidate_id": candidate.id, "job_id": trial.job_id,
           "watch_id": trial.watch_id}
    db.close()
    return ids


def provider_post(i, body="Synthetic personals ad text", url=None, hours_old=2):
    from rediska_core.providers.base import ProviderPost

    return ProviderPost(
        external_id=f"test_tp{i}",
        author_id=f"t2_test{i}",
        author_username=f"test_trial_author_{i}",
        title=f"Synthetic title {i}",
        url=url or f"/r/test_trial/comments/test_tp{i}/",
        location="r/test_trial",
        body_text=body,
        created_at=datetime.now(timezone.utc) - timedelta(hours=hours_old),
    )


def fake_adapter(posts):
    adapter = MagicMock()
    result = MagicMock()
    result.items = posts

    async def browse_location(**kwargs):
        return result

    async def aclose():
        return None

    adapter.browse_location = browse_location
    adapter.aclose = aclose
    return adapter


def fake_analysis(session_factory, recommendations, on_call=None):
    """Replacement for analyze_and_decide.apply: writes a verdict on the post."""
    from rediska_core.domain.models import ScoutWatchPost

    calls = []

    def apply(kwargs):
        calls.append(kwargs)
        db = session_factory()
        post = db.get(ScoutWatchPost, kwargs["scout_post_id"])
        rec = recommendations[len(calls) - 1]
        post.analysis_status = "analyzed"
        post.analysis_recommendation = rec
        post.dimension_results_json = {
            "gate_verdict": {
                "recommendation": rec,
                "score": 0.95 if rec == "suitable" else 0.2,
                "gate_results": [] if rec == "suitable"
                else [{"gate": "location", "status": "fail", "reason": "far"}],
            }
        }
        db.commit()
        db.close()
        if on_call:
            on_call(len(calls))
        return MagicMock()

    return apply, calls


def run_trial(session_factory, trial_id, posts, apply):
    with (
        patch.object(discovery_module, "_get_db_session", side_effect=session_factory),
        patch.object(scout_module, "_get_reddit_adapter", return_value=fake_adapter(posts)),
        patch.object(scout_module.analyze_and_decide, "apply", side_effect=apply),
    ):
        return discovery_module.run_trial(trial_id)


# =============================================================================
# run_trial
# =============================================================================


class TestRunTrial:
    def test_completes_with_yield_and_never_creates_leads(self, session_factory, trial_setup):
        from rediska_core.domain.models import (
            Job, LeadPost, SourceCandidate, SourceLinkSighting, SourceTrial,
        )

        posts = [
            provider_post(1),
            provider_post(2),
            provider_post(3, body="", url="https://listings.example.test/ad/3"),
            provider_post(4),
        ]
        apply, calls = fake_analysis(
            session_factory, ["suitable", "not_recommended", "needs_review"]
        )

        result = run_trial(session_factory, trial_setup["trial_id"], posts, apply)

        assert result["status"] == "completed"
        db = session_factory()
        trial = db.get(SourceTrial, trial_setup["trial_id"])
        assert trial.status == "completed" and trial.progress == 4 and trial.posts_total == 4
        y = trial.yield_json
        assert y["posts_fetched"] == 4 and y["skipped_empty"] == 1
        assert (y["suitable"], y["needs_review"], y["not_recommended"]) == (1, 1, 1)
        assert y["top_failing_gate"] == "location"
        assert y["median_post_age_hours"] == pytest.approx(2.0, abs=0.1)
        assert db.get(SourceCandidate, trial_setup["candidate_id"]).status == "trialled"
        assert db.get(Job, trial_setup["job_id"]).status == "done"
        # The suitable, high-scoring post was not promoted (the fake never
        # promotes, and the real pipeline refuses on trial watches).
        assert db.query(LeadPost).count() == 0
        # The unregistered link-only post was recorded, not fetched.
        assert db.query(SourceLinkSighting).one().host == "listings.example.test"
        assert all(c["watch_id"] == trial_setup["watch_id"] for c in calls)

    def test_cancel_mid_run_stops_between_posts(self, session_factory, trial_setup):
        from rediska_core.domain.models import Job, SourceCandidate, SourceTrial

        def cancel_after_first(n):
            if n == 1:
                db = session_factory()
                db.get(Job, trial_setup["job_id"]).status = "cancelled"
                db.commit()
                db.close()

        apply, calls = fake_analysis(
            session_factory, ["needs_review"] * 4, on_call=cancel_after_first
        )

        result = run_trial(
            session_factory, trial_setup["trial_id"], [provider_post(i) for i in range(4)], apply
        )

        assert result["status"] == "cancelled"
        assert len(calls) == 1
        db = session_factory()
        trial = db.get(SourceTrial, trial_setup["trial_id"])
        assert trial.status == "cancelled" and trial.progress == 1
        assert trial.yield_json["needs_review"] == 1
        assert db.get(SourceCandidate, trial_setup["candidate_id"]).status == "new"
        assert db.get(Job, trial_setup["job_id"]).status == "cancelled"

    def test_redelivery_of_running_trial_is_skipped(self, session_factory, trial_setup):
        from rediska_core.domain.models import SourceTrial

        db = session_factory()
        db.get(SourceTrial, trial_setup["trial_id"]).status = "running"
        db.commit()
        db.close()
        apply, calls = fake_analysis(session_factory, [])

        result = run_trial(session_factory, trial_setup["trial_id"], [provider_post(1)], apply)

        assert result["status"] == "skipped"
        assert calls == []

    def test_cancelled_before_start(self, session_factory, trial_setup):
        from rediska_core.domain.models import Job, SourceTrial

        db = session_factory()
        db.get(Job, trial_setup["job_id"]).status = "cancelled"
        db.commit()
        db.close()
        apply, calls = fake_analysis(session_factory, [])

        result = run_trial(session_factory, trial_setup["trial_id"], [provider_post(1)], apply)

        assert result["status"] == "cancelled" and calls == []
        db = session_factory()
        assert db.get(SourceTrial, trial_setup["trial_id"]).status == "cancelled"


# =============================================================================
# Trial guard in the scout pipeline
# =============================================================================


class TestTrialGuard:
    def test_trial_watch_never_auto_promotes(self):
        verdict = {"recommendation": "suitable", "score": 0.99}

        assert scout_module._should_promote(verdict, 0.7) is True
        assert scout_module._should_promote(verdict, 0.7, is_trial=True) is False


# =============================================================================
# mine_candidates
# =============================================================================


class TestMineCandidates:
    def test_one_run_per_day(self, session_factory):
        from rediska_core.domain.models import Job

        with (
            patch.object(discovery_module, "_get_db_session", side_effect=session_factory),
            patch(
                "rediska_core.domain.services.source_discovery.SourceDiscoveryService.mine"
            ) as mine,
        ):
            mine.return_value.to_dict.return_value = {"created": 0}
            first = discovery_module.mine_candidates(run_date="2026-09-18")
            second = discovery_module.mine_candidates(run_date="2026-09-18")

        assert first["status"] == "success"
        assert second["status"] == "skipped"
        assert mine.call_count == 1
        db = session_factory()
        job = db.query(Job).one()
        assert job.dedupe_key == "discovery.mine_candidates:2026-09-18" and job.status == "done"
