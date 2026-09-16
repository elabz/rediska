"""Unit tests for external listing resolution inside ScoutWatchService.record_post.

The scout worker task already resolves link-only bodies before calling
record_post (it needs the resolved text for its own empty-body skip and for
the analyze_and_decide payload). These tests cover the *defensive* resolution
inside record_post itself, so that any caller — present or future — persists
resolved content rather than a bare listing link.
"""

import logging
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from rediska_core.domain.models import Provider, ScoutWatch, ScoutWatchRun
from rediska_core.domain.services.scout_watch import ScoutWatchService

LISTING_URL = "https://weheartbdsm.com/listings/8980?from=reddit"
# What the resolver stores today: a details block, then the About text. The
# leading marker is how a pre-resolved body is recognised as a no-op.
RESOLVED_TEXT = (
    "[Listing details from weheartbdsm.com]\nLocation: Testville, Pennsylvania (in person)\n\n"
    "About Me\n\nSynthetic resolved listing text used only by this test."
)

RESOLVE_TARGET = "rediska_core.domain.services.scout_watch.maybe_resolve_post_body"


@pytest.fixture
def setup_provider(db_session):
    provider = Provider(provider_id="reddit", display_name="Reddit", enabled=True)
    db_session.add(provider)
    db_session.flush()
    return provider


@pytest.fixture
def watch(db_session, setup_provider):
    watch = ScoutWatch(
        provider_id="reddit",
        source_location="r/bdsmpersonals",
        sort_by="new",
        time_filter="day",
        auto_analyze=True,
        min_confidence=0.7,
        is_active=True,
    )
    db_session.add(watch)
    db_session.flush()
    return watch


@pytest.fixture
def run(db_session, watch):
    run = ScoutWatchRun(
        watch_id=watch.id,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(run)
    db_session.flush()
    return run


def test_link_only_body_is_resolved_before_persisting(db_session, watch, run):
    """A caller that has not pre-resolved still gets resolved content stored."""
    service = ScoutWatchService(db_session)

    with patch(RESOLVE_TARGET, return_value=RESOLVED_TEXT) as mock_resolve:
        post = service.record_post(
            watch_id=watch.id,
            run_id=run.id,
            external_post_id="lp1",
            post_title="Brat seeking a Confident Wrangler",
            post_body="",
            post_author="listing_author",
            post_url=LISTING_URL,
        )

    mock_resolve.assert_called_once_with("", LISTING_URL)
    assert post.post_body == RESOLVED_TEXT


def test_already_resolved_body_is_a_no_op(db_session, watch, run):
    """The worker pre-resolves; record_post's second call must not re-fetch.

    A body that already starts with the listing details block is recognised
    as resolved, so the real resolver makes no network call — asserted via
    the real function.
    """
    service = ScoutWatchService(db_session)

    with patch(
        "rediska_core.domain.services.external_listing.ExternalListingResolver.resolve"
    ) as mock_fetch:
        post = service.record_post(
            watch_id=watch.id,
            run_id=run.id,
            external_post_id="lp2",
            post_title="Brat seeking a Confident Wrangler",
            post_body=RESOLVED_TEXT,
            post_author="listing_author",
            post_url=LISTING_URL,
        )

    mock_fetch.assert_not_called()
    assert post.post_body == RESOLVED_TEXT


def test_missing_post_url_leaves_body_untouched(db_session, watch, run):
    """Callers that pass no URL keep the old behaviour (no resolution)."""
    service = ScoutWatchService(db_session)

    post = service.record_post(
        watch_id=watch.id,
        run_id=run.id,
        external_post_id="lp3",
        post_title="Ordinary post",
        post_body="Real reddit content",
        post_author="listing_author",
    )

    assert post.post_body == "Real reddit content"


def test_unresolvable_listing_keeps_original_body(db_session, watch, run, caplog):
    """A raising fetch is swallowed by maybe_resolve_post_body itself.

    The REAL resolver wrapper runs here -- only the network fetch is patched to
    raise. record_post has no fallback of its own, so this proves the swallow
    lives in maybe_resolve_post_body and that ingestion is never failed by a
    dead listing host. (Patching the wrapper with `lambda body, url: body`
    raised nothing at all and merely duplicated the no-op test above.)
    """
    service = ScoutWatchService(db_session)

    with caplog.at_level(logging.WARNING), patch(
        "rediska_core.domain.services.external_listing.ExternalListingResolver.resolve",
        side_effect=RuntimeError("listing host is down"),
    ) as mock_resolve:
        post = service.record_post(
            watch_id=watch.id,
            run_id=run.id,
            external_post_id="lp4",
            post_title="Brat seeking a Confident Wrangler",
            post_body="",
            post_author="listing_author",
            post_url=LISTING_URL,
        )

    # The failing path was really entered, not short-circuited earlier.
    mock_resolve.assert_called_once_with(LISTING_URL)
    # Original body preserved, no exception propagated...
    assert post.post_body == ""
    # ...and the failure is visible in the log rather than silent.
    assert any(
        "listing host is down" in record.getMessage() for record in caplog.records
    )
