"""Copy detection in the scout pipeline: fingerprint on record, ring-suspect skip.

Synthetic text and `test_` users only.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from rediska_core.domain.models import (
    ExternalAccount,
    PostFingerprint,
    Provider,
    ScoutWatchPost,
    ScoutWatchRun,
    SourceCandidate,
    SourceTrial,
)
from rediska_core.domain.services import scout_watch as scout_watch_module
from rediska_core.domain.services.post_copy import fingerprint_post
from rediska_core.domain.services.scout_watch import (
    SKIP_COPY_RING_SUSPECT,
    SKIP_REASON_TEXT,
    ScoutWatchService,
)
from rediska_core.domain.services.source_discovery import SourceDiscoveryService

BODY = " ".join(f"w{i}" for i in range(300))
NOW = datetime.utcnow()


@pytest.fixture
def world(db_session):
    db_session.add(Provider(provider_id="reddit", display_name="Reddit", enabled=True))
    db_session.flush()
    service = ScoutWatchService(db_session)
    watch = service.create_watch(source_location="r/test_watch", search_query="x")
    run = service.create_run(watch.id)
    return SimpleNamespace(service=service, watch=watch, run=run)


def record(world, ext_id, author, body=BODY, posted_at=None):
    return world.service.record_post(
        watch_id=world.watch.id,
        run_id=world.run.id,
        external_post_id=ext_id,
        post_title="A title",
        post_body=body,
        post_author=author,
        posted_at=posted_at,
    )


def verdict(world, ext_id, author, **kw):
    return world.service.check_author_verdict(
        "reddit", author, post_title="A title", post_body=BODY, external_post_id=ext_id, **kw
    )


class TestRecordPostFingerprints:
    def test_scout_post_is_fingerprinted_on_record(self, db_session, world):
        record(world, "test_p1", "test_a", posted_at=NOW)
        row = db_session.query(PostFingerprint).filter_by(external_post_id="test_p1").one()
        assert row.source == "scout" and row.location == "r/test_watch"
        assert row.posted_at == NOW and row.sketch is not None

    def test_empty_body_is_recorded_without_fingerprint(self, db_session, world):
        record(world, "test_p1", "test_a", body="")
        assert db_session.query(ScoutWatchPost).count() == 1
        assert db_session.query(PostFingerprint).count() == 0

    def test_fingerprint_survives_history_cleanup(self, db_session, world):
        post = record(world, "test_p1", "test_a")
        record(world, "test_p2", "test_b")
        db_session.delete(post)
        db_session.flush()
        assert db_session.query(PostFingerprint).count() == 2


class TestRingSkip:
    def test_third_account_of_a_ring_is_skipped(self, db_session, world):
        record(world, "test_p1", "test_a", posted_at=NOW - timedelta(days=3))
        record(world, "test_p2", "test_b", posted_at=NOW - timedelta(days=1))
        assert verdict(world, "test_p2", "test_b") is None  # 2 authors: not handled
        record(world, "test_p3", "test_c", posted_at=NOW)
        assert verdict(world, "test_p3", "test_c") == SKIP_COPY_RING_SUSPECT
        assert "spam ring" in SKIP_REASON_TEXT[SKIP_COPY_RING_SUSPECT]

    def test_short_template_ring_is_not_skipped(self, db_session, world):
        short = " ".join(f"t{i}" for i in range(80))  # ~310 chars: clusters, below 400
        for i, name in enumerate(("test_a", "test_b", "test_c")):
            record(world, f"test_s{i}", name, body=short)
        from rediska_core.domain.models import CopyCluster

        (cluster,) = db_session.query(CopyCluster).all()
        assert cluster.author_count == 3 and not cluster.handled
        assert verdict(world, "test_s2", "test_c") is None

    def test_confirmed_two_account_ring_is_skipped(self, db_session, world):
        from rediska_core.domain.services.post_copy import decide

        record(world, "test_p1", "test_a")
        post = record(world, "test_p2", "test_b")
        cluster_id = db_session.query(PostFingerprint).filter_by(
            external_post_id=post.external_post_id).one().id
        from rediska_core.domain.models import CopyClusterMember

        cid = db_session.query(CopyClusterMember).filter_by(fingerprint_id=cluster_id).one().cluster_id
        decide(db_session, cid, "confirmed_ring")
        assert verdict(world, "test_p2", "test_b") == SKIP_COPY_RING_SUSPECT

    def test_returning_author_is_analysed(self, db_session, world):
        db_session.add(ExternalAccount(
            provider_id="reddit", external_username="test_old", remote_status="deleted"
        ))
        db_session.flush()
        fingerprint_post(
            db_session, provider_id="reddit", external_post_id="test_old1",
            author_username="test_old", body_text=BODY, source="profile_item",
            posted_at=NOW - timedelta(days=60),
        )
        record(world, "test_p2", "test_new", posted_at=NOW)
        assert verdict(world, "test_p2", "test_new") is None

    def test_flag_off_does_not_skip(self, db_session, world, monkeypatch):
        record(world, "test_p1", "test_a")
        record(world, "test_p2", "test_b")
        record(world, "test_p3", "test_c")
        monkeypatch.setattr(
            scout_watch_module, "get_settings",
            lambda: SimpleNamespace(copy_skip_ring_suspects=False),
        )
        assert verdict(world, "test_p3", "test_c") is None

    def test_trial_and_manual_reanalysis_bypass_skip(self, db_session, world):
        record(world, "test_p1", "test_a")
        record(world, "test_p2", "test_b")
        record(world, "test_p3", "test_c")
        assert verdict(world, "test_p3", "test_c", copy_check=False) is None

    def test_do_not_contact_still_wins(self, db_session, world):
        from rediska_core.domain.services.ban_list import BanListService
        from rediska_core.domain.services.scout_watch import SKIP_DO_NOT_CONTACT

        record(world, "test_p1", "test_a")
        record(world, "test_p2", "test_b")
        BanListService(db_session).ban("reddit", "test_b", reason="scam")
        assert verdict(world, "test_p2", "test_b") == SKIP_DO_NOT_CONTACT


class TestTrialYield:
    def test_trial_posts_are_tagged_and_ring_suspects_counted(self, db_session, world):
        world.watch.is_trial = True
        candidate = SourceCandidate(
            provider_id="reddit", kind="location", name="r/test_watch", origin="mined",
            status="new", evidence_json={}, evidence_count=3, created_at=NOW, updated_at=NOW,
        )
        db_session.add(candidate)
        db_session.flush()
        trial = SourceTrial(
            candidate_id=candidate.id, watch_id=world.watch.id, run_id=world.run.id,
            status="running", sample_size=25, created_at=NOW,
        )
        db_session.add(trial)
        db_session.flush()

        record(world, "test_p1", "test_a")
        record(world, "test_p2", "test_b")
        record(world, "test_p3", "test_c", body=" ".join(f"z{i}" for i in range(300)))
        assert {r.source for r in db_session.query(PostFingerprint).all()} == {"trial"}

        report = SourceDiscoveryService(db_session).build_trial_yield(
            trial, posts_fetched=3, skipped_empty=0, link_only_resolved=0, post_ages_hours=[],
        )
        assert report["copy_ring_suspects"] == 2
        assert db_session.query(ScoutWatchRun).count() == 1
