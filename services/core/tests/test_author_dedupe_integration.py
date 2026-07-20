"""End-to-end integration tests for author-level lead dedupe.

Drives the real service + worker code paths against a real (sqlite) session:
1. Two watches surfacing different posts by one author yield a single lead
2. An ignored author's new post is skipped without any inference call
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# The worker imports core; when running core's suite from the host, make the
# sibling worker package importable so the scout task can be driven directly.
_WORKER_PATH = Path(__file__).resolve().parents[2] / "worker"
if str(_WORKER_PATH) not in sys.path:
    sys.path.insert(0, str(_WORKER_PATH))

from rediska_core.domain.models import (
    ExternalAccount,
    LeadPost,
    Provider,
    ScoutWatch,
    ScoutWatchPost,
)

from datetime import datetime, timezone


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
    """Set up the cross-posting author."""
    account = ExternalAccount(
        provider_id="reddit",
        external_username="cross_poster",
        remote_status="active",
    )
    db_session.add(account)
    db_session.flush()
    return account


def _watch(db_session, source_location):
    """Create an active watch on a subreddit."""
    watch = ScoutWatch(
        provider_id="reddit",
        source_location=source_location,
        sort_by="new",
        time_filter="day",
        auto_analyze=True,
        min_confidence=0.7,
        is_active=True,
    )
    db_session.add(watch)
    db_session.flush()
    return watch


def _scout_post(db_session, watch, external_post_id):
    """Record a sighting of a post by the cross-posting author."""
    post = ScoutWatchPost(
        watch_id=watch.id,
        external_post_id=external_post_id,
        post_title=f"Title {external_post_id}",
        post_author="cross_poster",
        first_seen_at=datetime.now(timezone.utc),
        analysis_status="pending",
    )
    db_session.add(post)
    db_session.flush()
    return post


def _post_data(watch, external_post_id):
    """Normalized post data as the scout pipeline builds it."""
    return {
        "provider_id": "reddit",
        "source_location": watch.source_location,
        "external_post_id": external_post_id,
        "post_url": f"https://reddit.com/comments/{external_post_id}",
        "title": f"Title {external_post_id}",
        "body_text": f"Body {external_post_id}",
        "author_username": "cross_poster",
    }


# =============================================================================
# 5.1 — ONE AUTHOR ACROSS TWO WATCHES
# =============================================================================


def test_one_author_across_two_watches_yields_a_single_lead(
    db_session, setup_provider, author
):
    """Two watches, two posts, one author → one lead, both scout posts linked."""
    from rediska_core.domain.services.scout_watch import ScoutWatchService

    service = ScoutWatchService(db_session)

    watch_a = _watch(db_session, "r/alpha")
    watch_b = _watch(db_session, "r/beta")
    post_a = _scout_post(db_session, watch_a, "cross_a")
    post_b = _scout_post(db_session, watch_b, "cross_b")

    # Each watch promotes its post, as analyze_and_decide STEP 8/9 does.
    lead_a = service.save_lead_from_watch(watch_a, _post_data(watch_a, "cross_a"))
    service.update_post_analysis(
        watch_id=watch_a.id,
        external_post_id="cross_a",
        recommendation="suitable",
        confidence=0.9,
        lead_id=lead_a.id,
    )

    lead_b = service.save_lead_from_watch(watch_b, _post_data(watch_b, "cross_b"))
    service.update_post_analysis(
        watch_id=watch_b.id,
        external_post_id="cross_b",
        recommendation="suitable",
        confidence=0.9,
        lead_id=lead_b.id,
    )

    # One active lead for the author...
    active = (
        db_session.query(LeadPost)
        .filter(
            LeadPost.author_account_id == author.id,
            LeadPost.deleted_at.is_(None),
            LeadPost.status != "ignored",
        )
        .all()
    )
    assert len(active) == 1

    # ...and both sightings point at it.
    db_session.refresh(post_a)
    db_session.refresh(post_b)
    assert post_a.lead_id == active[0].id
    assert post_b.lead_id == active[0].id


# =============================================================================
# 5.2 — IGNORED AUTHOR SKIPS THE PIPELINE (FOR CONTENT ALREADY ANALYSED)
# =============================================================================


def _ignored_author_lead(db_session, title, body):
    """Give the author a standing negative verdict on the given content."""
    from rediska_core.domain.services.leads import LeadsService

    leads_service = LeadsService(db_session)
    lead = leads_service.save_lead(
        provider_id="reddit",
        source_location="r/alpha",
        external_post_id="old_post",
        post_url="https://reddit.com/comments/old_post",
        title=title,
        body_text=body,
        author_username="cross_poster",
    )
    leads_service.update_status(lead.id, "ignored")
    return lead


def test_ignored_author_repost_is_skipped_with_zero_inference_calls(
    db_session, setup_provider, author
):
    """Re-surfacing content we already judged never reaches the provider or LLM."""
    from rediska_worker.tasks import scout as scout_module

    _ignored_author_lead(db_session, "Same title", "Same body")

    author_id = author.id
    watch = _watch(db_session, "r/alpha")
    scout_post = _scout_post(db_session, watch, "new_post")
    scout_post_id = scout_post.id
    watch_id = watch.id
    # Identical content, surfacing under a different post id (a crosspost).
    post_data = _post_data(watch, "new_post")
    post_data["title"] = "Same title"
    post_data["body_text"] = "Same body"
    db_session.commit()

    with (
        patch.object(scout_module, "_get_db_session", return_value=db_session),
        patch.object(scout_module, "_get_reddit_adapter") as mock_adapter,
        patch(
            "rediska_core.domain.services.inference.get_inference_client"
        ) as mock_inference,
    ):
        result = scout_module.analyze_and_decide(
            watch_id=watch_id,
            scout_post_id=scout_post_id,
            post_data=post_data,
        )

    assert result["status"] == "skipped"
    assert result["skip_reason"] == "lead_ignored"

    # No provider fetch, no inference.
    mock_adapter.assert_not_called()
    mock_inference.assert_not_called()

    # The sighting stays in history with a stored reason. The task closes the
    # session it was handed, so re-read the row rather than refreshing.
    stored = (
        db_session.query(ScoutWatchPost)
        .filter(ScoutWatchPost.id == scout_post_id)
        .one()
    )
    assert stored.analysis_status == "skipped"
    assert "ignored" in (stored.analysis_reasoning or "")

    # No new lead was created for the ignored author.
    assert (
        db_session.query(LeadPost)
        .filter(LeadPost.author_account_id == author_id)
        .count()
        == 1
    )


def test_ignored_author_with_new_content_is_analysed_again(
    db_session, setup_provider, author
):
    """A rejected author who posts something genuinely new gets another look.

    An `ignored` verdict suppresses content we already judged — not the person
    forever. If what they are posting has changed, so might the assessment.
    """
    from rediska_worker.tasks import scout as scout_module

    _ignored_author_lead(db_session, "Old title", "What I wanted back then")

    watch = _watch(db_session, "r/alpha")
    scout_post = _scout_post(db_session, watch, "changed_post")
    scout_post_id = scout_post.id
    watch_id = watch.id
    post_data = _post_data(watch, "changed_post")
    post_data["title"] = "Completely different ask now"
    post_data["body_text"] = "My situation changed and so did what I am looking for"
    db_session.commit()

    with (
        patch.object(scout_module, "_get_db_session", return_value=db_session),
        patch.object(scout_module, "_get_reddit_adapter") as mock_adapter,
    ):
        result = scout_module.analyze_and_decide(
            watch_id=watch_id,
            scout_post_id=scout_post_id,
            post_data=post_data,
        )

    # Not skipped — the pipeline proceeded to the profile fetch.
    assert result.get("skip_reason") is None
    assert result["status"] != "skipped"
    mock_adapter.assert_called_once()
