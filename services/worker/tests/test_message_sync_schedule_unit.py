"""Tests for how Reddit message polling is scheduled and reported."""

from types import SimpleNamespace

from rediska_worker.celery_app import app
from rediska_worker.tasks import ingest


def scheduled_tasks() -> dict[str, float]:
    return {entry["task"]: entry["schedule"] for entry in app.conf.beat_schedule.values()}


def sync_result(**overrides) -> SimpleNamespace:
    fields = dict(
        skipped=False,
        aborted=False,
        conversations_synced=0,
        messages_synced=0,
        new_conversations=0,
        new_messages=0,
        pages_fetched=1,
        errors=[],
    )
    return SimpleNamespace(**{**fields, **overrides})


class TestBeatSchedule:
    def test_inbox_is_polled_every_minute_and_sent_folder_every_five(self):
        schedule = scheduled_tasks()

        assert schedule["ingest.sync_inbox_fast"] == 60.0
        assert schedule["ingest.sync_sent"] == 300.0

    def test_combined_inbox_and_sent_sync_is_not_scheduled(self):
        # It re-read the inbox the fast sync already covers; it stays on-demand only
        assert "ingest.sync_delta" not in scheduled_tasks()

    def test_scheduled_sync_tasks_are_registered(self):
        assert "ingest.sync_inbox_fast" in app.tasks
        assert "ingest.sync_sent" in app.tasks


class TestSyncResponse:
    def test_skipped_run_reports_skipped_and_queues_no_indexing(self, monkeypatch):
        queued: list[str] = []
        monkeypatch.setattr(ingest.app, "send_task", lambda name, **kw: queued.append(name))

        response = ingest._sync_response(sync_result(skipped=True, new_messages=3), "inbox_fast")

        assert response["status"] == "skipped"
        assert queued == []

    def test_aborted_run_reports_error_and_keeps_what_it_committed(self, monkeypatch):
        """An aborted run still keeps (and has already indexed) its pages."""
        queued: list[str] = []
        monkeypatch.setattr(
            ingest.app,
            "send_task",
            lambda name, **kw: queued.append(name) or SimpleNamespace(id="task-1"),
        )

        response = ingest._sync_response(
            sync_result(aborted=True, new_messages=2, errors=["Database error"]), "sent"
        )

        assert response["status"] == "error"
        assert response["errors"] == ["Database error"]
        assert queued == []

    def test_a_sync_never_reindexes_the_whole_corpus(self, monkeypatch):
        """New messages are indexed one by one as they are stored.

        Queuing `index.bulk_index_all_messages` here re-wrote all 55k message
        documents to catch the few that were new, and a bulk write replaces the
        document — dropping its `embedding`. Since inbox sync runs every 60
        seconds, every message vector was destroyed roughly that often, and the
        sweeper needs ~46 hours to rebuild them. Semantic coverage for messages
        could never converge.
        """
        queued: list[str] = []
        monkeypatch.setattr(
            ingest.app,
            "send_task",
            lambda name, **kw: queued.append(name) or SimpleNamespace(id="task-1"),
        )

        response = ingest._sync_response(sync_result(new_messages=25), "inbox_fast")

        assert response["status"] == "success"
        assert response["new_messages"] == 25
        assert queued == []
