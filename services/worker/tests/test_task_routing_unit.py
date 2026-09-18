"""Tests that declared queue routing is actually effective.

Every `rediska_worker.tasks.<module>.*` key in `task_routes` used to be dead:
tasks register under short names (`ingest.sync_delta`, `message.send_manual`),
which those module-path globs never matched, so every routed task fell through
to the default `celery` queue. The per-queue isolation the config expressed did
not happen.

The tests here resolve through the live router, and the guards below fail on a
pattern that matches no registered task or a task that matches no pattern --
the properties that would have caught the original bug.
"""

from celery.app.routes import MapRoute


# Task name -> the queue it must be dispatched to. One entry per routing
# pattern so the table doubles as documentation of the intended isolation.
EXPECTED_ROUTES = [
    ("ingest.sync_delta", "ingest"),
    ("ingest.sync_inbox_fast", "ingest"),
    ("ingest.sync_sent", "ingest"),
    ("ingest.backfill_conversations", "ingest"),
    ("index.upsert_content", "index"),
    ("index.delete_content", "index"),
    ("embed.generate", "embed"),
    ("embed.generate_batch", "embed"),
    ("agent.profile_summary", "agent"),
    ("agent.lead_scoring", "agent"),
    ("agent.draft_intro", "agent"),
    ("maintenance.mysql_dump_local", "maintenance"),
    ("maintenance.cleanup_scout_watch_history", "maintenance"),
    ("maintenance.expire_stale_leads", "maintenance"),
    ("maintenance.generate_calibration_report", "maintenance"),
    ("message.send_manual", "messages"),
    ("multi_agent_analysis.analyze_lead", "multi_agent_analysis"),
    ("multi_agent_analysis.batch_analyze", "multi_agent_analysis"),
    # Prompt replay shares the analysis queue so it sits behind the inference gate.
    ("evaluation.replay_prompt", "multi_agent_analysis"),
    ("scout.run_all_watches", "scout"),
    ("scout.analyze_and_decide", "scout"),
    ("inbox.export", "transfer"),
    ("inbox.import", "transfer"),
    ("inbox.clear", "transfer"),
]


def _registered_task_names(app) -> list[str]:
    """Rediska's own registered tasks, excluding Celery's built-ins.

    Importing the app's `include` modules first is not optional: the registry
    is populated lazily, so without this it holds only the task modules some
    earlier test happened to import. The guards below would then report dead
    patterns for whole modules purely because of test ordering -- a test that
    lies in both directions, which is the failure mode this file exists to
    prevent.
    """
    app.loader.import_default_modules()
    return [name for name in app.tasks if not name.startswith("celery.")]


class TestLiveRouting:
    """Routes are resolved through the router, not read from the config dict."""

    def test_every_declared_route_reaches_its_queue(
        self, mock_celery_app, resolve_queue
    ):
        """Each task lands on its declared queue, not the default."""
        mismatched = {
            name: resolve_queue(mock_celery_app, name)
            for name, expected in EXPECTED_ROUTES
            if resolve_queue(mock_celery_app, name) != expected
        }

        assert mismatched == {}

    def test_no_registered_task_falls_through_to_the_default_queue(
        self, mock_celery_app, resolve_queue
    ):
        """The exact symptom of the bug: everything landing on `celery`.

        Covers tasks added later too, so a new task without a matching route
        fails here rather than quietly sharing the default queue.
        """
        default_queue = mock_celery_app.conf.task_default_queue or "celery"

        on_default = [
            name
            for name in _registered_task_names(mock_celery_app)
            if resolve_queue(mock_celery_app, name) == default_queue
        ]

        assert on_default == []


class TestNoDeadRoutingPatterns:
    """Guard against a routing pattern that matches nothing."""

    def test_every_routing_pattern_matches_a_registered_task(self, mock_celery_app):
        """A pattern matching no task expresses isolation that does not exist.

        This is the guard that would have caught the original defect: all seven
        `rediska_worker.tasks.<module>.*` patterns matched zero registered task
        names while looking perfectly reasonable in the config.

        Uses Celery's own MapRoute matcher, which returns None on no match --
        unlike the full Router, which falls back to the default queue and so
        can never reveal a dead pattern.
        """
        registered = _registered_task_names(mock_celery_app)
        routes = mock_celery_app.conf.task_routes

        dead = [
            pattern
            for pattern, destination in routes.items()
            if not any(
                MapRoute({pattern: destination})(name) for name in registered
            )
        ]

        assert dead == []
