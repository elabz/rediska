"""Unit tests for external listing resolution in the scout watch task.

Verifies the ordering guarantee: a link-only post from a supported listing
host is resolved BEFORE the empty-body skip check and BEFORE the
analyze_and_decide task is enqueued, so record_post and the analysis pipeline
both receive the resolved About text.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# rediska_core is installed alongside the worker in containers; when running
# tests from the host, make the sibling core package importable for patching.
_CORE_PATH = Path(__file__).resolve().parents[2] / "core"
if str(_CORE_PATH) not in sys.path:
    sys.path.insert(0, str(_CORE_PATH))

from rediska_worker.tasks import scout as scout_module

LISTING_URL = "https://weheartbdsm.com/listings/8980?from=reddit"
RESOLVED_TEXT = "About Me\n\nResolved listing content."


def _make_post(body_text="", url=LISTING_URL):
    post = MagicMock()
    post.external_id = "lp1"
    post.body_text = body_text
    post.url = url
    post.title = "Brat seeking a Confident Wrangler"
    post.author_username = "listing_author"
    post.author_id = "t2_abc"
    post.created_at = None
    return post


def _make_service():
    service = MagicMock()
    watch = MagicMock()
    watch.is_active = True
    watch.auto_analyze = True
    watch.source_location = "r/bdsmpersonals"
    watch.sort_by = "new"
    watch.time_filter = "week"
    watch.search_query = None
    watch.identity_id = 1
    service.get_watch_or_raise.return_value = watch
    run = MagicMock()
    run.id = 7
    service.create_run.return_value = run
    service.is_post_seen.return_value = False
    scout_post = MagicMock()
    scout_post.id = 42
    service.record_post.return_value = scout_post
    return service


def _make_adapter(post):
    adapter = MagicMock()
    result = MagicMock()
    result.items = [post]
    result.metadata = {}

    async def browse_location(**kwargs):
        return result

    adapter.browse_location = browse_location
    return adapter


def _run_watch(post, resolver):
    service = _make_service()
    with (
        patch.object(scout_module, "_get_db_session", return_value=MagicMock()),
        patch.object(scout_module, "_get_reddit_adapter", return_value=_make_adapter(post)),
        patch(
            "rediska_core.domain.services.scout_watch.ScoutWatchService",
            return_value=service,
        ),
        patch(
            "rediska_core.domain.services.external_listing.maybe_resolve_post_body",
            side_effect=resolver,
        ) as mock_resolve,
        patch.object(scout_module.analyze_and_decide, "delay") as mock_delay,
    ):
        result = scout_module.run_single_watch(1)
    return result, service, mock_resolve, mock_delay


def test_link_only_post_is_resolved_before_record_and_analysis():
    post = _make_post(body_text="")
    result, service, mock_resolve, mock_delay = _run_watch(
        post, resolver=lambda body, url: RESOLVED_TEXT
    )

    assert result["status"] == "success"
    mock_resolve.assert_called_once_with("", LISTING_URL)

    # record_post persisted the RESOLVED body (not the empty link-only one)
    record_kwargs = service.record_post.call_args.kwargs
    assert record_kwargs["post_body"] == RESOLVED_TEXT

    # analyze_and_decide was enqueued with the resolved body in post_data
    assert mock_delay.call_count == 1
    post_data = mock_delay.call_args.kwargs["post_data"]
    assert post_data["body_text"] == RESOLVED_TEXT
    assert result["posts_skipped_empty"] == 0


def test_unresolvable_link_only_post_is_still_skipped():
    post = _make_post(body_text="")
    result, service, mock_resolve, mock_delay = _run_watch(
        post, resolver=lambda body, url: body  # resolution failed → original body
    )

    assert result["status"] == "success"
    assert result["posts_skipped_empty"] == 1
    service.record_post.assert_not_called()
    mock_delay.assert_not_called()


def test_post_with_real_body_is_not_altered():
    post = _make_post(body_text="Real reddit content", url="https://reddit.com/r/x/1")
    result, service, mock_resolve, mock_delay = _run_watch(
        post, resolver=lambda body, url: body
    )

    assert result["status"] == "success"
    record_kwargs = service.record_post.call_args.kwargs
    assert record_kwargs["post_body"] == "Real reddit content"
