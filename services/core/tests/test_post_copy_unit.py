"""Post copy detection: fingerprints, matching, clusters, classification, decisions.

Synthetic text and `test_` users only.
"""

import os
import random
from datetime import datetime, timedelta

import pytest

from rediska_core.domain.models import (
    AuditLog,
    CopyCluster,
    CopyClusterMember,
    CopyClusterSuppression,
    DoNotContact,
    ExternalAccount,
    LeadPost,
    PostFingerprint,
    PostFingerprintBand,
    Provider,
)
from rediska_core.domain.services import post_copy
from rediska_core.domain.services.ban_list import BanListService
from rediska_core.domain.services.post_copy import (
    AuthorFacts,
    classify,
    compute_features,
    fingerprint_post,
    jaccard_estimate,
    shingle_hashes,
    normalise,
    bottom_k,
)

VOCAB = [f"w{i}" for i in range(2000)]
NOW = datetime(2026, 9, 1, 12, 0, 0)


def words(seed: int, n: int = 300) -> list[str]:
    rng = random.Random(seed)
    return [rng.choice(VOCAB) for _ in range(n)]


def text(ws: list[str]) -> str:
    return " ".join(ws)


def edited(ws: list[str], keep: int, seed: int) -> list[str]:
    """Keep the first `keep` words, replace the rest with fresh words."""
    return ws[:keep] + words(seed, len(ws) - keep)


def true_jaccard(a: str, b: str) -> float:
    sa, sb = shingle_hashes(normalise(a)), shingle_hashes(normalise(b))
    return len(sa & sb) / len(sa | sb)


@pytest.fixture
def provider(db_session):
    db_session.add(Provider(provider_id="reddit", display_name="Reddit", enabled=True))
    db_session.flush()
    return "reddit"


def fp(db, ext_id, author, body, posted_at=None, source="scout", **kw):
    return fingerprint_post(
        db,
        provider_id="reddit",
        external_post_id=ext_id,
        author_username=author,
        body_text=body,
        source=source,
        posted_at=posted_at,
        **kw,
    )


def account(db, name, status="active"):
    acc = ExternalAccount(
        provider_id="reddit", external_username=name, remote_status=status
    )
    db.add(acc)
    db.flush()
    return acc


# =============================================================================
# PURE FINGERPRINTING
# =============================================================================


class TestFeatures:
    def test_identical_text_same_hash_and_similarity_one(self):
        body = text(words(1))
        a, b = compute_features(body, 200), compute_features(body.upper() + "  ", 200)
        assert a.exact_hash == b.exact_hash
        assert jaccard_estimate(a.sketch, b.sketch) == 1.0

    def test_seventy_percent_overlap_is_above_threshold(self):
        base = words(2)
        a, b = text(base), text(edited(base, 255, seed=3))
        assert 0.6 < true_jaccard(a, b) < 0.85
        est = jaccard_estimate(compute_features(a, 200).sketch, compute_features(b, 200).sketch)
        assert est >= 0.5

    def test_twenty_percent_overlap_is_below_threshold(self):
        base = words(4)
        a, b = text(base), text(edited(base, 70, seed=5))
        est = jaccard_estimate(compute_features(a, 200).sketch, compute_features(b, 200).sketch)
        assert est < 0.5

    def test_short_body_gets_exact_hash_only(self):
        f = compute_features("looking for fun tonight, message me", 200)
        assert f.exact_hash and f.sketch is None

    def test_empty_body_has_no_features(self):
        assert compute_features("  ...  ", 200) is None
        assert compute_features(None, 200) is None

    def test_details_block_is_excluded(self):
        about = text(words(6))
        block = "[Listing details from weheartbdsm.com]\nLocation: Somewhere\nAge: 30"
        with_block = compute_features(f"{block}\n\n{about}", 200)
        assert with_block == compute_features(about, 200)

    def test_sketch_round_trip_and_bottom_k(self):
        f = compute_features(text(words(7)), 200)
        assert len(f.sketch) == 64 and list(f.sketch) == sorted(f.sketch)
        assert post_copy.unpack_sketch(post_copy.pack_sketch(f.sketch)) == f.sketch
        assert bottom_k([5, 1, 3, 1], k=2) == (1, 3)
        assert all(v < 2 ** 63 for v in f.sketch)


# =============================================================================
# CLASSIFICATION (pure) — every branch
# =============================================================================


class TestClassify:
    def a(self, name, *days, dead=False, first=None, last=None):
        return AuthorFacts(
            name, [NOW + timedelta(days=d) for d in days], dead=dead,
            first_activity=first, last_activity=last,
        )

    def test_three_authors_is_ring(self):
        assert classify([self.a("x", 0), self.a("y", 90), self.a("z", 200)], 7) == "ring_suspect"

    def test_two_live_within_window_is_ring(self):
        assert classify([self.a("x", 0), self.a("y", 2)], 7) == "ring_suspect"

    def test_within_window_with_dead_account_is_unclassified(self):
        assert classify([self.a("x", 0, dead=True), self.a("y", 2)], 7) == "unclassified"

    def test_dead_earlier_account_long_gap_is_returning(self):
        assert classify([self.a("x", 0, dead=True), self.a("y", 60)], 7) == "returning_author"

    def test_silent_earlier_account_long_gap_is_returning(self):
        x = self.a("x", 0, last=NOW + timedelta(days=1))
        y = self.a("y", 60, first=NOW + timedelta(days=59))
        assert classify([x, y], 7) == "returning_author"

    def test_earlier_account_still_active_is_unclassified(self):
        x = self.a("x", 0, last=NOW + timedelta(days=100))
        y = self.a("y", 60, first=NOW + timedelta(days=60))
        assert classify([x, y], 7) == "unclassified"

    def test_single_author_is_unclassified(self):
        assert classify([self.a("x", 0, 30)], 7) == "unclassified"


# =============================================================================
# INGEST + CLUSTERS
# =============================================================================


class TestFingerprintPost:
    def test_row_holds_no_text(self, db_session, provider):
        body = text(words(10))
        out = fp(db_session, "p1", "test_a", body)
        row = out.fingerprint
        assert out.created and row.sketch and row.char_len == len(body)
        for value in (row.author_username, row.location, row.external_post_id):
            assert value is None or body[:50] not in value
        bands = db_session.query(PostFingerprintBand).filter_by(fingerprint_id=row.id).count()
        assert bands == 8

    def test_second_path_does_not_create_second_row(self, db_session, provider):
        body = text(words(11))
        first = fp(db_session, "p1", "test_a", body, source="scout")
        acc = account(db_session, "test_a")
        again = fp(db_session, "p1", "test_a", body, source="lead", account_id=acc.id,
                   posted_at=NOW)
        assert not again.created and again.fingerprint.id == first.fingerprint.id
        assert again.fingerprint.account_id == acc.id and again.fingerprint.posted_at == NOW
        assert db_session.query(PostFingerprint).count() == 1

    def test_identical_text_from_second_account_clusters(self, db_session, provider):
        body = text(words(12))
        fp(db_session, "p1", "test_a", body)
        out = fp(db_session, "p2", "Test_B", body)
        cluster = db_session.get(CopyCluster, out.cluster_id)
        assert cluster.author_count == 2 and cluster.member_count == 2
        assert cluster.kind == "ring_suspect"  # two live accounts, same day
        assert db_session.query(AuditLog).filter_by(action_type="copy_cluster.create").count() == 1

    def test_lightly_edited_copy_clusters(self, db_session, provider):
        base = words(13)
        fp(db_session, "p1", "test_a", text(base))
        out = fp(db_session, "p2", "test_b", text(edited(base, 255, seed=14)))
        assert out.cluster_id is not None

    def test_low_overlap_does_not_cluster(self, db_session, provider):
        base = words(15)
        fp(db_session, "p1", "test_a", text(base))
        out = fp(db_session, "p2", "test_b", text(edited(base, 70, seed=16)))
        assert out.cluster_id is None and db_session.query(CopyCluster).count() == 0

    def test_own_repost_links_without_cluster(self, db_session, provider):
        body = text(words(17))
        first = fp(db_session, "p1", "test_a", body, posted_at=NOW)
        out = fp(db_session, "p2", "TEST_A", body, posted_at=NOW + timedelta(days=7))
        assert out.repost_of_id == first.fingerprint.id
        assert out.cluster_id is None and db_session.query(CopyCluster).count() == 0

    def test_short_identical_posts_never_cluster(self, db_session, provider):
        fp(db_session, "p1", "test_a", "looking for fun tonight")
        out = fp(db_session, "p2", "test_b", "looking for fun tonight")
        assert out.cluster_id is None

    def test_third_author_joins_and_audits(self, db_session, provider):
        body = text(words(18))
        first = fp(db_session, "p1", "test_a", body)
        fp(db_session, "p2", "test_b", body)
        out = fp(db_session, "p3", "test_c", body)
        cluster = db_session.get(CopyCluster, out.cluster_id)
        assert cluster.author_count == 3 and cluster.kind == "ring_suspect"
        assert db_session.query(AuditLog).filter_by(action_type="copy_cluster.join").count() == 1
        member = db_session.query(CopyClusterMember).filter_by(
            fingerprint_id=first.fingerprint.id).one()
        assert member.cluster_id == cluster.id

    def test_match_across_two_clusters_merges_them(self, db_session, provider):
        body = text(words(19))
        other = text(words(20))
        a = fp(db_session, "a", "test_a", body, link=False).fingerprint
        b = fp(db_session, "b", "test_b", body, link=False).fingerprint
        c = fp(db_session, "c", "test_c", body, link=False).fingerprint
        d = fp(db_session, "d", "test_d", other, link=False).fingerprint
        big = CopyCluster(provider_id="reddit", created_at=NOW, updated_at=NOW, member_count=2)
        small = CopyCluster(provider_id="reddit", created_at=NOW, updated_at=NOW, member_count=1,
                            decision="confirmed_ring")
        db_session.add_all([big, small])
        db_session.flush()
        for f, cl in ((a, big), (b, big), (c, small), (d, small)):
            db_session.add(CopyClusterMember(cluster_id=cl.id, fingerprint_id=f.id, joined_at=NOW))
        db_session.flush()
        small_id = small.id

        out = fp(db_session, "e", "test_e", body)
        assert out.cluster_id == big.id
        assert db_session.get(CopyCluster, small_id) is None
        assert big.member_count == 5 and big.decision == "confirmed_ring"
        assert db_session.query(AuditLog).filter_by(action_type="copy_cluster.merge").count() == 1

    def test_boilerplate_band_is_ignored(self, db_session, provider):
        body = text(words(21))
        target = compute_features(body, 200)
        sketch_blob = post_copy.pack_sketch(target.sketch)

        def dummies(n, start):
            for i in range(n):
                row = PostFingerprint(
                    provider_id="reddit", external_post_id=f"d{start + i}",
                    author_username=f"test_d{start + i}", first_seen_at=NOW, char_len=500,
                    exact_hash=os.urandom(16), sketch=sketch_blob, source="scout",
                )
                db_session.add(row)
                db_session.flush()
                for key in post_copy.band_keys(target.sketch):
                    db_session.add(PostFingerprintBand(band_hash=key, fingerprint_id=row.id))
            db_session.flush()

        probe = PostFingerprint(
            provider_id="reddit", external_post_id="probe", author_username="test_p",
            first_seen_at=NOW, char_len=500, exact_hash=os.urandom(16), sketch=sketch_blob,
            source="scout",
        )
        db_session.add(probe)
        dummies(5, 0)
        assert len(post_copy.find_matches(db_session, probe, target.sketch)) == 5
        dummies(post_copy.BOILERPLATE_BAND_LIMIT, 100)
        assert post_copy.find_matches(db_session, probe, target.sketch) == []

    def test_safe_wrapper_swallows_errors(self, db_session, provider, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("nope")

        monkeypatch.setattr(post_copy, "compute_features", boom)
        assert post_copy.safe_fingerprint_post(
            db_session, provider_id="reddit", external_post_id="x", author_username="test_a",
            body_text="hello", source="scout",
        ) is None


class TestClassificationFromStoredFacts:
    def test_deleted_account_comes_back(self, db_session, provider):
        base = words(30)
        account(db_session, "test_old", status="deleted")
        fp(db_session, "p1", "test_old", text(base), posted_at=NOW)
        out = fp(db_session, "p2", "test_new", text(edited(base, 260, seed=31)),
                 posted_at=NOW + timedelta(days=60))
        assert db_session.get(CopyCluster, out.cluster_id).kind == "returning_author"

    def test_status_change_recomputes(self, db_session, provider):
        body = text(words(32))
        old = account(db_session, "test_old")
        fp(db_session, "p1", "test_old", body, posted_at=NOW)
        fp(db_session, "p0", "test_old", text(words(33)), posted_at=NOW + timedelta(days=90))
        out = fp(db_session, "p2", "test_new", body, posted_at=NOW + timedelta(days=60))
        cluster = db_session.get(CopyCluster, out.cluster_id)
        assert cluster.kind == "unclassified"  # the old account kept posting

        old.remote_status = "suspended"
        db_session.flush()
        assert post_copy.recompute_clusters_for_author(db_session, "reddit", "TEST_OLD") == [
            cluster.id
        ]
        assert cluster.kind == "returning_author"


class TestDecisions:
    def _ring(self, db, seed=40):
        body = text(words(seed))
        fp(db, "p1", "test_a", body)
        return body, fp(db, "p2", "test_b", body).cluster_id

    def test_confirmed_ring_overrides_and_audits(self, db_session, provider):
        _, cid = self._ring(db_session)
        cluster = post_copy.decide(db_session, cid, "confirmed_ring", "same photos")
        assert cluster.effective_kind == "confirmed_ring" and cluster.kind == "ring_suspect"
        assert db_session.query(AuditLog).filter_by(action_type="copy_cluster.decision").count() == 1

    def test_coincidence_dissolves_and_suppresses(self, db_session, provider):
        body, cid = self._ring(db_session)
        post_copy.decide(db_session, cid, "coincidence")
        assert db_session.query(CopyClusterMember).count() == 0
        assert db_session.query(CopyClusterSuppression).count() == 2
        assert post_copy.list_clusters(db_session)[0] == []
        assert post_copy.copy_summaries(db_session, "reddit", ["p1", "p2"]) == {}

        later = fp(db_session, "p3", "test_c", body)
        assert later.cluster_id is None and later.suppressed
        again = fp(db_session, "p4", "test_d", body)
        assert again.cluster_id is None
        assert db_session.query(CopyCluster).filter(CopyCluster.decision.is_(None)).count() == 0

    def test_unknown_decision_rejected(self, db_session, provider):
        _, cid = self._ring(db_session)
        with pytest.raises(post_copy.CopyDecisionError):
            post_copy.decide(db_session, cid, "nonsense")
        with pytest.raises(post_copy.CopyClusterNotFound):
            post_copy.decide(db_session, 9999, "same_person")

    def test_decision_changes_nothing_else(self, db_session, provider):
        acc = account(db_session, "test_a")
        lead = LeadPost(provider_id="reddit", source_location="r/test", external_post_id="p1",
                        post_url="https://x/p1", author_account_id=acc.id, status="saved")
        db_session.add(lead)
        _, cid = self._ring(db_session)
        post_copy.decide(db_session, cid, "confirmed_ring")
        assert lead.status == "saved"
        assert db_session.query(DoNotContact).count() == 0


class TestReadModels:
    def test_copy_summaries_batched(self, db_session, provider):
        body = text(words(50))
        fp(db_session, "p1", "test_a", body, posted_at=NOW)
        fp(db_session, "p2", "test_b", body, posted_at=NOW + timedelta(days=1))
        fp(db_session, "solo", "test_c", text(words(51)))
        out = post_copy.copy_summaries(db_session, "reddit", ["p1", "p2", "solo", "missing"])
        assert set(out) == {"p1", "p2"}
        assert out["p2"]["kind"] == "ring_suspect" and out["p2"]["author_count"] == 2
        assert out["p2"]["earliest_other_posted_at"] == NOW
        assert out["p1"]["earliest_other_posted_at"] == NOW + timedelta(days=1)

    def test_cluster_detail_lists_what_we_hold(self, db_session, provider):
        body = text(words(52))
        acc = account(db_session, "test_a", status="deleted")
        db_session.add(LeadPost(provider_id="reddit", source_location="r/test",
                                external_post_id="p1", post_url="https://x/p1",
                                author_account_id=acc.id, status="ignored"))
        db_session.add(DoNotContact(provider_id="reddit", external_username="test_b",
                                    reason="scam", status="active"))
        fp(db_session, "p1", "test_a", body, posted_at=NOW)
        out = fp(db_session, "p2", "test_b", body, posted_at=NOW + timedelta(days=60))
        detail = post_copy.cluster_detail(db_session, out.cluster_id)
        a, b = detail["members"]
        assert a["author_username"] == "test_a" and a["remote_status"] == "deleted"
        assert a["lead_status"] == "ignored" and a["lead_id"] is not None
        assert b["ban_status"] == "active"


# =============================================================================
# contact-ban-list against the real tables
# =============================================================================


class TestBanSuggestionsWithTables:
    def test_suggestions_dismiss_and_cluster_usernames(self, db_session, provider):
        body = text(words(60))
        fp(db_session, "p1", "test_a", body, posted_at=NOW)
        fp(db_session, "p2", "test_b", body, posted_at=NOW + timedelta(days=1))
        cid = fp(db_session, "p3", "test_c", body, posted_at=NOW + timedelta(days=2)).cluster_id
        svc = BanListService(db_session)

        (item,) = svc.suggestions()
        assert item["cluster_id"] == cid and item["kind"] == "ring_suspect"
        assert item["suggested_usernames"] == ["test_a", "test_b", "test_c"]
        assert item["authors"][0]["earliest"] is True
        assert sorted(svc.cluster_usernames(cid)) == ["test_a", "test_b", "test_c"]

        assert svc.dismiss_suggestion(cid, "u/Test_B") == 1
        (item,) = svc.suggestions()
        assert item["suggested_usernames"] == ["test_a", "test_c"]

        svc.bulk_ban("reddit", svc.cluster_usernames(cid), reason="copy_ring", cluster_id=cid)
        assert svc.suggestions() == []

    def test_unclassified_cluster_is_not_suggested(self, db_session, provider):
        body = text(words(61))
        account(db_session, "test_old", status="deleted")
        fp(db_session, "p1", "test_old", body, posted_at=NOW)
        fp(db_session, "p2", "test_new", body, posted_at=NOW + timedelta(days=60))
        assert BanListService(db_session).suggestions() == []


# =============================================================================
# BACKFILL
# =============================================================================


class TestBackfill:
    def _seed(self, db):
        from rediska_core.domain.models import ProfileItem, ScoutWatch, ScoutWatchPost

        body = text(words(70))
        a = account(db, "test_a")
        account(db, "test_b")
        db.add(ProfileItem(
            account_id=a.id, item_type="post", external_item_id="p1",
            text_content=f"A title\n\n{body}", link_title="A title",
            item_created_at=NOW, subreddit="test",
        ))
        watch = ScoutWatch(provider_id="reddit", source_location="r/test", search_query="x")
        db.add(watch)
        db.flush()
        db.add(ScoutWatchPost(
            watch_id=watch.id, external_post_id="p2", post_author="test_b", post_body=body,
            first_seen_at=NOW + timedelta(days=1), analysis_status="pending",
        ))
        # Same post id stored twice: the lead wins, no second fingerprint.
        db.add(LeadPost(
            provider_id="reddit", source_location="r/test", external_post_id="p1",
            post_url="https://x/p1", author_account_id=a.id, body_text=body,
            post_created_at=NOW, status="saved",
        ))
        db.add(ScoutWatchPost(
            watch_id=watch.id, external_post_id="p3", post_author="test_c",
            post_body="short", first_seen_at=NOW, analysis_status="pending",
        ))
        db.flush()

    def test_dry_run_reports_and_writes_nothing(self, db_session, provider):
        self._seed(db_session)
        report = post_copy.backfill(db_session, dry_run=True)
        assert report["posts_stored"] == 3
        assert report["would_fingerprint"] == 3 and report["would_sketch"] == 2
        assert report["estimated_clusters"] == 1
        assert report["estimated_authors_in_clusters"] == 2
        assert db_session.query(PostFingerprint).count() == 0
        assert db_session.query(AuditLog).count() == 0

    def test_live_run_builds_clusters_with_one_audit_and_is_idempotent(
        self, db_session, provider
    ):
        self._seed(db_session)
        report = post_copy.backfill(db_session, dry_run=False)
        assert report["fingerprints_created"] == 3
        assert report["clusters"] == 1 and report["clusters_by_kind"] == {"ring_suspect": 1}
        lead_fp = db_session.query(PostFingerprint).filter_by(external_post_id="p1").one()
        assert lead_fp.source == "lead" and lead_fp.posted_at == NOW
        assert db_session.query(AuditLog).filter_by(action_type="copy.backfill").count() == 1
        assert db_session.query(AuditLog).filter(
            AuditLog.action_type.like("copy_cluster.%")
        ).count() == 0

        again = post_copy.backfill(db_session, dry_run=False)
        assert again["fingerprints_created"] == 0 and again["already_fingerprinted"] == 3
        assert db_session.query(CopyCluster).count() == 1
        assert db_session.query(CopyClusterMember).count() == 2

    def test_profile_item_title_is_not_fingerprinted(self):
        assert post_copy._strip_title("A title\n\nbody text", "A title") == "body text"
        assert post_copy._strip_title("body text", None) == "body text"


# =============================================================================
# AUTOMATIC HANDLING OF SPAM RINGS
# =============================================================================


class TestHandled:
    @pytest.mark.parametrize(
        "kind,decision,authors,chars,expected",
        [
            ("ring_suspect", None, 3, 400, True),
            ("ring_suspect", None, 2, 900, False),  # too few authors
            ("ring_suspect", None, 17, 222, False),  # short: maybe a template
            ("returning_author", None, 5, 900, False),
            ("unclassified", "confirmed_ring", 2, 100, True),  # the human decided
            ("ring_suspect", "same_person", 9, 900, False),
            ("ring_suspect", "coincidence", 9, 900, False),
        ],
    )
    def test_predicate(self, kind, decision, authors, chars, expected):
        assert post_copy.is_handled(kind, decision, authors, chars, 3, 400) is expected

    def _ring(self, db, n=3, seed=80):
        body = text(words(seed))
        out = None
        for i in range(n):
            out = fp(db, f"r{seed}_{i}", f"test_r{i}", body, posted_at=NOW + timedelta(hours=i))
        return db.get(CopyCluster, out.cluster_id)

    def test_recompute_sets_average_length_and_flag(self, db_session, provider):
        cluster = self._ring(db_session)
        assert cluster.handled and cluster.avg_char_len > 400
        assert post_copy.is_handled_post(db_session, "reddit", "r80_0")
        summary = post_copy.copy_summaries(db_session, "reddit", ["r80_1"])["r80_1"]
        assert summary["handled"] is True

    def test_same_person_decision_unhandles_and_confirmed_rehandles(self, db_session, provider):
        cluster = self._ring(db_session)
        post_copy.decide(db_session, cluster.id, "same_person")
        assert not cluster.handled
        post_copy.decide(db_session, cluster.id, "confirmed_ring")
        assert cluster.handled

    def test_lead_list_and_needs_review_hide_handled_rings(self, db_session, provider):
        from rediska_core.domain.models import ScoutWatch, ScoutWatchPost
        from rediska_core.domain.services.leads import LeadsService
        from rediska_core.domain.services.scout_watch import ScoutWatchService

        self._ring(db_session)
        for ext in ("r80_0", "solo"):
            db_session.add(LeadPost(provider_id="reddit", source_location="r/test",
                                    external_post_id=ext, post_url=f"https://x/{ext}",
                                    status="saved"))
        watch = ScoutWatch(provider_id="reddit", source_location="r/test", search_query="x")
        db_session.add(watch)
        db_session.flush()
        for ext in ("r80_1", "solo2"):
            db_session.add(ScoutWatchPost(
                watch_id=watch.id, external_post_id=ext, post_author="test_x",
                first_seen_at=NOW, analysis_status="analyzed",
                analysis_recommendation="needs_review",
            ))
        db_session.flush()

        leads = LeadsService(db_session)
        assert [l.external_post_id for l in leads.list_leads()] == ["solo"]
        assert leads.count_leads() == 1
        assert leads.count_leads(include_copies=True) == 2

        scout = ScoutWatchService(db_session)
        posts, _ = scout.list_needs_review()
        assert [p.external_post_id for p in posts] == ["solo2"]
        assert scout.count_needs_review(include_copies=True) == 2
        # Hidden, never changed.
        assert {l.status for l in db_session.query(LeadPost).all()} == {"saved"}

    def test_recompute_all_reports_handled(self, db_session, provider):
        self._ring(db_session)
        self._ring(db_session, n=2, seed=81)
        counts = post_copy.recompute_all(db_session)
        assert counts["ring_suspect"] == 2 and counts["handled"] == 1
