"""Unit tests for ingest tasks.

Most of what used to live here has been removed:

- `test_task_is_registered` / `test_all_ingest_tasks_have_correct_prefix` only
  asserted that `@app.task(name="ingest.sync_delta")` set the name it was
  literally handed. They restate the decorator argument and cannot fail.
- `test_returns_not_implemented` / `test_accepts_cursor_parameter` targeted
  `# TODO` stubs (browse_location, fetch_post, fetch_profile,
  fetch_profile_items) whose entire body is a hardcoded
  `{"status": "not_implemented", ...}` literal.

The implemented ingest tasks (backfill_conversations, backfill_messages,
sync_delta) perform real DB/provider work and are covered by the core
integration tests. Add real coverage here as the stubs get implemented.
"""

import pytest


class TestTaskRouting:
    """Tests for task routing configuration."""

    def test_ingest_tasks_routed_to_ingest_queue(self, mock_celery_app):
        """Ingest tasks should be routed to ingest queue.

        NOTE: this asserts the declared task_routes config. It does NOT prove
        the route is effective -- the registered task names are `ingest.*`, not
        `rediska_worker.tasks.ingest.*`, so this pattern never actually matches
        at dispatch time and these tasks fall through to the default queue.
        See the routing note in the review report.
        """
        routes = mock_celery_app.conf.task_routes

        assert "rediska_worker.tasks.ingest.*" in routes
        assert routes["rediska_worker.tasks.ingest.*"]["queue"] == "ingest"
