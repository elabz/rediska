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


class TestTaskRouting:
    """Tests for task routing configuration."""

    def test_ingest_tasks_routed_to_ingest_queue(self, mock_celery_app, resolve_queue):
        """Ingest tasks should be routed to the ingest queue.

        Asserts the LIVE router, not the declared dict. The old version of this
        test checked that `rediska_worker.tasks.ingest.*` was a key in
        task_routes -- which it was, and which proved nothing, because tasks
        register under short names so that pattern matched nothing at dispatch
        time and every ingest task fell through to the default queue.
        """
        assert resolve_queue(mock_celery_app, "ingest.sync_delta") == "ingest"
        assert (
            resolve_queue(mock_celery_app, "ingest.backfill_messages") == "ingest"
        )
