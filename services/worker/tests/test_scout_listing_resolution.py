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

    # record_post persisted the RESOLVED body (not the empty link-only one),
    # and receives the URL so its own defensive resolution can run for callers
    # that did not pre-resolve.
    record_kwargs = service.record_post.call_args.kwargs
    assert record_kwargs["post_body"] == RESOLVED_TEXT
    assert record_kwargs["post_url"] == LISTING_URL

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


def test_analyze_and_decide_enriches_body_from_listing(monkeypatch):
    """Re-analysis rebuilds post_data from Reddit; the task must resolve itself."""
    import rediska_worker.tasks.scout as scout_module

    seen = {}

    def fake_resolve(body, url):
        seen["args"] = (body, url)
        return "[Listing details from weheartbdsm.com]\nLocation: Testville, PA (in person)\n\n" + (body or "")

    monkeypatch.setattr(
        "rediska_core.domain.services.external_listing.maybe_resolve_post_body", fake_resolve
    )

    class FakePost:
        post_body = "pasted on reddit"

    class FakeQuery:
        def __init__(self, obj): self.obj = obj
        def filter(self, *a, **k): return self
        def first(self): return self.obj

    class FakeDB:
        def __init__(self): self.commits = 0; self.post = FakePost()
        def query(self, model): return FakeQuery(self.post)
        def commit(self): self.commits += 1
        def close(self): pass

    db = FakeDB()
    monkeypatch.setattr(scout_module, "_get_db_session", lambda: db)

    class StopHere(Exception):
        pass

    # Stop right after enrichment: the first provider/LLM-side call is the
    # standing-verdict gate, which we make raise.
    monkeypatch.setattr(
        "rediska_core.domain.services.scout_watch.ScoutWatchService.check_author_verdict",
        lambda *a, **k: (_ for _ in ()).throw(StopHere()),
    )

    post_data = {
        "external_post_id": "abc", "author_username": "test_user",
        "post_url": "https://weheartbdsm.com/listings/1?from=reddit",
        "body_text": "pasted on reddit",
    }
    try:
        scout_module.analyze_and_decide.run(watch_id=1, scout_post_id=1, post_data=post_data)
    except StopHere:
        pass
    except Exception:
        pass  # any later failure is fine; we only assert the enrichment step

    assert seen["args"] == ("pasted on reddit", "https://weheartbdsm.com/listings/1?from=reddit")
    assert post_data["body_text"].startswith("[Listing details from weheartbdsm.com]")
    assert db.post.post_body == post_data["body_text"]
    assert db.commits >= 1
