"""Unit tests for source discovery mining and qualification (source-discovery).

All accounts, communities, and URLs are synthetic.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from rediska_core.domain.models import (
    AnalysisEvaluation,
    DoNotContact,
    ExternalAccount,
    LeadAnalysis,
    LeadPost,
    ProfileItem,
    Provider,
    ScoutWatch,
    ScoutWatchPost,
    SourceCandidate,
    SourceLinkSighting,
)
from rediska_core.domain.services.source_discovery import (
    SourceDiscoveryService,
    compute_lift,
    host_of,
    normalize_location,
    qualified_account_ids,
    record_link_sighting,
)

NOW = datetime.utcnow()


# =============================================================================
# FIXTURE HELPERS
# =============================================================================


@pytest.fixture
def provider(db_session):
    db_session.add(Provider(provider_id="reddit", display_name="Reddit", enabled=True))
    db_session.flush()


class World:
    """Builds synthetic authors, their stored history, and verdicts."""

    def __init__(self, db):
        self.db = db
        self.n = 0

    def author(self, *, qualified=False, analysed=True, contacted=False, engaged=False,
               communities=(), items_age_days=1):
        self.n += 1
        account = ExternalAccount(
            provider_id="reddit",
            external_username=f"test_author_{self.n}",
            analysis_state="analyzed" if analysed else "not_analyzed",
            contact_state="contacted" if contacted else "not_contacted",
            engagement_state="engaged" if engaged else "not_engaged",
        )
        self.db.add(account)
        self.db.flush()
        for i, community in enumerate(communities):
            self.db.add(ProfileItem(
                account_id=account.id,
                item_type="post",
                external_item_id=f"test_item_{self.n}_{i}",
                item_created_at=NOW - timedelta(days=items_age_days),
                text_content="synthetic post",
                subreddit=community,
                remote_visibility="visible",
            ))
        if qualified:
            self.lead(account, "suitable")
        self.db.flush()
        return account

    def lead(self, account, recommendation, deleted=False, post_url=None):
        self.n += 1
        lead = LeadPost(
            provider_id="reddit",
            source_location="r/test_watched",
            external_post_id=f"test_post_{self.n}",
            post_url=post_url or f"https://reddit.com/r/test_watched/comments/{self.n}",
            author_account_id=account.id,
            status="new",
            analysis_recommendation=recommendation,
            deleted_at=NOW if deleted else None,
        )
        self.db.add(lead)
        self.db.flush()
        return lead


@pytest.fixture
def world(db_session, provider):
    return World(db_session)


def service(db, **kw):
    kw.setdefault("min_qualified_authors", 3)
    kw.setdefault("window_days", 180)
    return SourceDiscoveryService(db, **kw)


def candidate(db, name, kind="location"):
    return (
        db.query(SourceCandidate)
        .filter(SourceCandidate.name == name, SourceCandidate.kind == kind)
        .first()
    )


# =============================================================================
# PURE HELPERS
# =============================================================================


class TestHelpers:
    def test_normalize_location(self):
        assert normalize_location("r/Test_Sub") == "r/test_sub"
        assert normalize_location("test_sub") == "r/test_sub"
        assert normalize_location("/r/test_sub/") == "r/test_sub"
        assert normalize_location("") is None

    def test_host_of(self):
        assert host_of("https://www.Example.test/listings/1?utm=x") == "example.test"
        assert host_of("/r/test/comments/1") is None
        assert host_of("ftp://example.test/x") is None

    def test_lift_is_one_for_equal_shares(self):
        assert compute_lift(8, 8, 38, 38) == pytest.approx(1.0)

    def test_lift_above_one_when_over_represented(self):
        assert compute_lift(6, 8, 9, 38) > 1

    def test_lift_below_one_when_under_represented(self):
        assert compute_lift(8, 1400, 78, 4850) < 1

    def test_small_all_qualified_community_ranks_below_stronger_evidence(self):
        """3 of 3 authors qualified must not outrank 20 of 30 (production noise)."""
        tiny = compute_lift(3, 1407, 3, 4850)
        strong = compute_lift(20, 1407, 30, 4850)

        assert strong > tiny > 1
        assert tiny < 2  # unshrunk, 3 of 3 hit the ~3.45 ceiling

    def test_lift_grows_with_evidence_at_the_same_rate(self):
        rates = [compute_lift(k, 1407, k, 4850) for k in (3, 10, 30)]

        assert rates == sorted(rates)

    def test_lift_defaults_without_population(self):
        assert compute_lift(0, 0, 0, 0) == 1.0


# =============================================================================
# QUALIFICATION
# =============================================================================


class TestQualifiedAuthors:
    def test_signals(self, db_session, world):
        suitable = world.author(qualified=True)
        contacted = world.author(contacted=True)
        engaged = world.author(engaged=True)
        needs_review = world.author()
        world.lead(needs_review, "needs_review")

        ids = qualified_account_ids(db_session)

        assert {suitable.id, contacted.id, engaged.id} <= ids
        assert needs_review.id not in ids

    def test_do_not_contact_never_qualifies(self, db_session, world):
        blocked = world.author(qualified=True, contacted=True)
        db_session.add(DoNotContact(provider_id="reddit", external_username=blocked.external_username))
        db_session.flush()

        assert blocked.id not in qualified_account_ids(db_session)

    def test_soft_deleted_lead_does_not_qualify(self, db_session, world):
        author = world.author()
        world.lead(author, "suitable", deleted=True)

        assert author.id not in qualified_account_ids(db_session)

    def test_human_agree_on_suitable_scout_post_qualifies(self, db_session, world):
        author = world.author()
        db_session.add(AnalysisEvaluation(
            subject_type="scout_post", subject_id=999, account_id=author.id, dimension=None,
            human_verdict="agree", reason_tags_json=[],
            agent_snapshot_json={"recommendation": "suitable"}, prompt_versions_json={},
        ))
        db_session.flush()

        assert author.id in qualified_account_ids(db_session)

    def test_human_disagree_on_suitable_lead_removes_it(self, db_session, world):
        author = world.author()
        lead = world.lead(author, "suitable")
        analysis = LeadAnalysis(
            lead_id=lead.id, account_id=author.id, status="completed",
            started_at=NOW, final_recommendation="suitable", prompt_versions_json={},
        )
        db_session.add(analysis)
        db_session.flush()
        lead.latest_analysis_id = analysis.id
        db_session.add(AnalysisEvaluation(
            subject_type="lead_analysis", subject_id=analysis.id, account_id=author.id,
            dimension=None, human_verdict="disagree", reason_tags_json=[],
            agent_snapshot_json={"recommendation": "suitable"}, prompt_versions_json={},
        ))
        db_session.flush()

        assert author.id not in qualified_account_ids(db_session)


# =============================================================================
# LOCATION MINING
# =============================================================================


@pytest.fixture
def populated(db_session, world):
    """8 qualified + 30 other analysed authors.

    r/test_kinky:   6 qualified, 3 other  -> over-represented
    r/test_popular: everyone              -> lift ~ 1
    r/test_thin:    1 qualified           -> below floor
    r/test_watched: 4 qualified           -> already watched
    """
    for i in range(8):
        communities = ["r/test_popular"]
        if i < 6:
            communities.append("r/test_kinky")
        if i == 0:
            communities.append("r/test_thin")
        if i < 4:
            communities.append("test_Watched")  # un-prefixed, mixed case
        world.author(qualified=True, communities=communities)
    for i in range(30):
        communities = ["r/test_popular"]
        if i < 3:
            communities.append("r/test_kinky")
        world.author(communities=communities)
    db_session.add(ScoutWatch(provider_id="reddit", source_location="r/test_watched"))
    db_session.flush()


class TestLocationMining:
    def test_over_represented_community_becomes_candidate(self, db_session, populated):
        summary = service(db_session).mine()

        kinky = candidate(db_session, "r/test_kinky")
        assert kinky is not None
        assert kinky.origin == "mined" and kinky.status == "new"
        assert kinky.evidence_json["qualified_authors"] == 6
        assert kinky.evidence_json["analysed_authors"] == 9
        assert kinky.lift > 1
        assert kinky.evidence_count == 6
        assert summary.qualified_authors == 8

    def test_thin_evidence_not_surfaced(self, db_session, populated):
        service(db_session).mine()

        assert candidate(db_session, "r/test_thin") is None

    def test_watched_community_excluded(self, db_session, populated):
        service(db_session).mine()

        assert candidate(db_session, "r/test_watched") is None

    def test_trial_watch_does_not_count_as_watched(self, db_session, populated):
        db_session.query(ScoutWatch).delete()
        db_session.add(ScoutWatch(
            provider_id="reddit", source_location="r/test_watched",
            is_trial=True, is_active=False,
        ))
        db_session.flush()

        service(db_session).mine()

        assert candidate(db_session, "r/test_watched") is not None

    def test_popular_community_ranks_low(self, db_session, populated):
        svc = service(db_session)
        svc.mine()

        popular = candidate(db_session, "r/test_popular")
        assert popular.lift == pytest.approx(1.0, abs=0.05)
        listed, _ = svc.list_candidates(kind="location")
        names = [c.name for c in listed]
        assert names.index("r/test_kinky") < names.index("r/test_popular")

    def test_window_excludes_old_history(self, db_session, world):
        for _ in range(3):
            world.author(qualified=True, communities=["r/test_old"], items_age_days=400)

        service(db_session, window_days=180).mine()

        assert candidate(db_session, "r/test_old") is None

    def test_nothing_is_watched_automatically(self, db_session, populated):
        watches_before = db_session.query(ScoutWatch).count()

        service(db_session).mine()

        assert db_session.query(ScoutWatch).count() == watches_before


class TestUpsert:
    def test_dismissed_stays_dismissed_with_updated_evidence(self, db_session, populated, world):
        svc = service(db_session)
        svc.mine()
        kinky = candidate(db_session, "r/test_kinky")
        svc.dismiss(kinky)

        world.author(qualified=True, communities=["r/test_kinky"])
        svc.mine()

        kinky = candidate(db_session, "r/test_kinky")
        assert kinky.status == "dismissed"
        assert kinky.evidence_json["qualified_authors"] == 7
        listed, _ = svc.list_candidates()
        assert "r/test_kinky" not in [c.name for c in listed]

    def test_snooze_lifts_when_date_passes(self, db_session, populated):
        svc = service(db_session)
        svc.mine()
        kinky = candidate(db_session, "r/test_kinky")
        svc.snooze(kinky, NOW + timedelta(days=1))
        assert "r/test_kinky" not in [c.name for c in svc.list_candidates()[0]]

        svc.mine(now=NOW + timedelta(days=2))

        assert candidate(db_session, "r/test_kinky").status == "new"

    def test_stale_mined_candidate_removed_when_below_floor(self, db_session, populated):
        svc = service(db_session)
        svc.mine()
        assert candidate(db_session, "r/test_kinky") is not None

        service(db_session, min_qualified_authors=7).mine()

        assert candidate(db_session, "r/test_kinky") is None

    def test_manual_candidate_survives_below_floor(self, db_session, populated):
        svc = service(db_session)
        svc.add_manual("r/test_manual")

        svc.mine()

        manual = candidate(db_session, "r/test_manual")
        assert manual is not None and manual.origin == "manual"


# =============================================================================
# EXTERNAL HOSTS
# =============================================================================


def sighting(db, n, url, source="scout"):
    db.add(SourceLinkSighting(
        provider_id="reddit", external_post_id=f"test_link_{n}", host=host_of(url),
        url=url, source=source, seen_at=NOW - timedelta(days=1),
    ))


class TestExternalHosts:
    def test_recurring_unknown_host_becomes_candidate(self, db_session, world):
        for i in range(12):
            sighting(db_session, i, f"https://listings.example.test/ad/{i}")
        db_session.flush()

        service(db_session).mine()

        host = candidate(db_session, "listings.example.test", kind="external_host")
        assert host is not None
        assert host.lift is None
        assert host.evidence_json["occurrences"] == 12
        assert len(host.evidence_json["example_urls"]) == 5

    def test_registered_host_is_not_a_candidate(self, db_session, world):
        for i in range(12):
            sighting(db_session, i, f"https://weheartbdsm.com/listings/{i}")
        db_session.flush()

        service(db_session).mine()

        assert db_session.query(SourceCandidate).filter_by(kind="external_host").count() == 0

    def test_record_link_sighting_skips_registered_and_provider_hosts(self, db_session, provider):
        assert not record_link_sighting(db_session, "reddit", "p1", "https://weheartbdsm.com/listings/1", "scout")
        assert not record_link_sighting(db_session, "reddit", "p2", "https://i.redd.it/x.jpg", "scout")
        assert record_link_sighting(db_session, "reddit", "p3", "https://listings.example.test/a?utm_source=x", "scout")
        assert not record_link_sighting(db_session, "reddit", "p3", "https://listings.example.test/a", "scout")

        stored = db_session.query(SourceLinkSighting).one()
        assert stored.url == "https://listings.example.test/a"  # tracking params stripped

    def test_urls_from_leads_and_qualified_items_count(self, db_session, world):
        author = world.author(qualified=True)
        for i in range(2):
            world.lead(author, "needs_review", post_url=f"https://listings.example.test/lead/{i}")
        db_session.add(ProfileItem(
            account_id=author.id, item_type="comment", external_item_id="test_c1",
            item_created_at=NOW, text_content="see https://listings.example.test/item/1.",
            remote_visibility="visible",
        ))
        db_session.flush()

        service(db_session).mine()

        host = candidate(db_session, "listings.example.test", kind="external_host")
        assert host.evidence_json["occurrences"] == 3
        assert host.evidence_json["by_source"] == {"lead": 2, "qualified_item": 1}


class TestNoNetwork:
    def test_mining_issues_no_http_request(self, db_session, populated):
        for i in range(12):
            sighting(db_session, i, f"https://listings.example.test/ad/{i}")
        db_session.flush()

        def boom(*args, **kwargs):
            raise AssertionError("mining must not make HTTP requests")

        with (
            patch("httpx.Client.send", side_effect=boom),
            patch("httpx.AsyncClient.send", side_effect=boom),
            patch("socket.socket.connect", side_effect=boom),
        ):
            summary = service(db_session).mine()

        assert summary.host_candidates == 1
        assert summary.location_candidates >= 1


# =============================================================================
# TRIAL-WATCH INVISIBILITY IN THE WATCH SERVICE
# =============================================================================


class TestTrialWatchFilter:
    def test_watch_list_and_duplicate_check_ignore_trial_watches(self, db_session, provider):
        from rediska_core.domain.services.scout_watch import ScoutWatchService

        trial = ScoutWatch(provider_id="reddit", source_location="r/test_trial",
                           is_trial=True, is_active=False)
        db_session.add(trial)
        db_session.flush()
        svc = ScoutWatchService(db_session)

        assert trial not in svc.list_watches()
        assert trial not in svc.list_watches(is_active=False)
        # A real watch on the trialled location is not a duplicate of the trial.
        real = svc.create_watch(source_location="r/test_trial")
        assert real.id != trial.id

    def test_needs_review_queue_excludes_trial_posts(self, db_session, provider):
        from rediska_core.domain.services.scout_watch import ScoutWatchService

        real = ScoutWatch(provider_id="reddit", source_location="r/test_real")
        trial = ScoutWatch(provider_id="reddit", source_location="r/test_trial",
                           is_trial=True, is_active=False)
        db_session.add_all([real, trial])
        db_session.flush()
        for watch in (real, trial):
            db_session.add(ScoutWatchPost(
                watch_id=watch.id, external_post_id=f"test_nr_{watch.id}",
                first_seen_at=NOW, analysis_status="analyzed",
                analysis_recommendation="needs_review",
            ))
        db_session.flush()

        posts, _ = ScoutWatchService(db_session).list_needs_review()

        assert [p.watch_id for p in posts] == [real.id]
        assert ScoutWatchService(db_session).count_needs_review() == 1
