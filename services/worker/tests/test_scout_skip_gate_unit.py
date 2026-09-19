"""Unit tests for the standing-verdict skip gate in scout.analyze_and_decide.

Verifies the ordering guarantee: an author with a standing verdict (ignored
lead, already contacted/engaged, do-not-contact) short-circuits the pipeline
before any provider fetch or LLM call happens.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# rediska_core is installed alongside the worker in containers; when running
# tests from the host, make the sibling core package importable for patching.
_CORE_PATH = Path(__file__).resolve().parents[2] / "core"
if str(_CORE_PATH) not in sys.path:
    sys.path.insert(0, str(_CORE_PATH))

import pytest

from rediska_core.domain.services.scout_watch import (
    SKIP_ALREADY_CONTACTED,
    SKIP_DO_NOT_CONTACT,
    SKIP_LEAD_IGNORED,
)
from rediska_worker.tasks import scout as scout_module

POST_DATA = {
    "provider_id": "reddit",
    "source_location": "r/watched",
    "external_post_id": "gated_post",
    "post_url": "https://reddit.com/comments/gated_post",
    "title": "A post",
    "body_text": "Some body",
    "author_username": "verdicted_author",
}


def _run_analyze(skip_reason):
    """Run analyze_and_decide with check_author_verdict stubbed."""
    service = MagicMock()
    service.check_author_verdict.return_value = skip_reason

    scout_post = MagicMock()
    scout_post.id = 42

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = scout_post

    with (
        patch.object(scout_module, "_get_db_session", return_value=db),
        patch.object(scout_module, "_get_reddit_adapter") as mock_adapter,
        patch(
            "rediska_core.domain.services.scout_watch.ScoutWatchService",
            return_value=service,
        ),
        patch(
            "rediska_core.domain.services.inference.get_inference_client"
        ) as mock_inference,
    ):
        result = scout_module.analyze_and_decide(
            watch_id=1,
            scout_post_id=42,
            post_data=POST_DATA,
        )

    return result, scout_post, mock_adapter, mock_inference


@pytest.mark.parametrize(
    "skip_reason",
    [SKIP_DO_NOT_CONTACT, SKIP_ALREADY_CONTACTED, SKIP_LEAD_IGNORED],
)
def test_standing_verdict_skips_without_fetch_or_inference(skip_reason):
    """Every standing verdict returns before the profile fetch and the LLM."""
    result, scout_post, mock_adapter, mock_inference = _run_analyze(skip_reason)

    assert result["status"] == "skipped"
    assert result["skip_reason"] == skip_reason
    mock_adapter.assert_not_called()
    mock_inference.assert_not_called()


def test_skipped_post_records_status_and_reason():
    """The sighting stays in watch history with a stored reason."""
    result, scout_post, _, _ = _run_analyze(SKIP_LEAD_IGNORED)

    assert scout_post.analysis_status == "skipped"
    assert "ignored" in scout_post.analysis_reasoning
    assert result["external_post_id"] == "gated_post"


def test_skip_is_audit_logged():
    """The skip writes a scout_watch.skip_author audit entry."""
    service = MagicMock()
    service.check_author_verdict.return_value = SKIP_LEAD_IGNORED

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = MagicMock()

    with (
        patch.object(scout_module, "_get_db_session", return_value=db),
        patch.object(scout_module, "_get_reddit_adapter"),
        patch(
            "rediska_core.domain.services.scout_watch.ScoutWatchService",
            return_value=service,
        ),
    ):
        scout_module.analyze_and_decide(
            watch_id=1,
            scout_post_id=42,
            post_data=POST_DATA,
        )

    audited = [
        call.args[0]
        for call in db.add.call_args_list
        if getattr(call.args[0], "action_type", None) == "scout_watch.skip_author"
    ]
    assert len(audited) == 1
    assert audited[0].response_json == {"skip_reason": SKIP_LEAD_IGNORED}
    assert audited[0].actor == "system"


def test_author_without_verdict_proceeds_past_the_gate():
    """No standing verdict means the pipeline continues to the profile fetch."""
    service = MagicMock()
    service.check_author_verdict.return_value = None

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = MagicMock()

    with (
        patch.object(scout_module, "_get_db_session", return_value=db),
        patch.object(scout_module, "_get_reddit_adapter") as mock_adapter,
        patch(
            "rediska_core.domain.services.scout_watch.ScoutWatchService",
            return_value=service,
        ),
    ):
        result = scout_module.analyze_and_decide(
            watch_id=1,
            scout_post_id=42,
            post_data=POST_DATA,
        )

    assert result["status"] != "skipped"
    mock_adapter.assert_called_once()


# =============================================================================
# ANALYSIS RETENTION
# =============================================================================


def test_cleanup_failed_analyses_deletes_nothing():
    """Analysis results are retained permanently — the task only reports."""
    from rediska_worker.tasks.multi_agent_analysis import cleanup_failed_analyses

    stale = [MagicMock(), MagicMock(), MagicMock()]
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = stale

    with patch(
        "rediska_worker.tasks.multi_agent_analysis._get_db_session", return_value=db
    ):
        result = cleanup_failed_analyses(max_age_hours=72)

    assert result["status"] == "success"
    assert result["cleaned_up"] == 0
    assert result["retained"] is True
    assert result["stale_failed_analyses"] == 3
    db.delete.assert_not_called()


# =============================================================================
# Copy-ring skip (post-fingerprint-dedupe)
# =============================================================================


def _gate_kwargs(manual: bool, is_trial: bool = False) -> dict:
    """kwargs analyze_and_decide passes to check_author_verdict."""
    from rediska_core.domain.services.scout_watch import SKIP_COPY_RING_SUSPECT

    service = MagicMock()
    service.check_author_verdict.return_value = SKIP_COPY_RING_SUSPECT
    watch = MagicMock()
    watch.is_trial = is_trial
    watch.provider_id = "reddit"
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = watch

    with (
        patch.object(scout_module, "_get_db_session", return_value=db),
        patch.object(scout_module, "_get_reddit_adapter") as mock_adapter,
        patch(
            "rediska_core.domain.services.scout_watch.ScoutWatchService",
            return_value=service,
        ),
    ):
        result = scout_module.analyze_and_decide(
            watch_id=1, scout_post_id=42, post_data=dict(POST_DATA), manual=manual,
        )
    assert result["skip_reason"] == SKIP_COPY_RING_SUSPECT
    mock_adapter.assert_not_called()
    return service.check_author_verdict.call_args.kwargs


def test_scout_run_applies_copy_ring_check():
    kwargs = _gate_kwargs(manual=False)
    assert kwargs["external_post_id"] == "gated_post" and kwargs["copy_check"] is True


def test_manual_reanalysis_and_trials_bypass_copy_ring_check():
    assert _gate_kwargs(manual=True)["copy_check"] is False
    assert _gate_kwargs(manual=False, is_trial=True)["copy_check"] is False


def test_copy_ring_post_never_auto_promotes():
    suitable = {"recommendation": "suitable", "score": 0.95}
    assert scout_module._should_promote(suitable, 0.7) is True
    assert scout_module._should_promote(suitable, 0.7, copy_ring=True) is False
