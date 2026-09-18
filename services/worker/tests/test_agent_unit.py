"""Unit tests for agent tasks.

Most of what used to live here has been removed:

- `test_task_is_registered` / `test_all_agent_tasks_have_correct_prefix` only
  asserted that `@app.task(name="agent.profile_summary")` set the name it was
  literally handed. They restate the decorator argument and cannot fail.
- `test_returns_not_implemented` / `test_accepts_*` / `test_*_returns_dict`
  targeted `# TODO` stubs whose entire body is a hardcoded
  `{"status": "not_implemented", ...}` literal. They pin placeholder text, so
  they pass while the feature does not exist and will have to be deleted the
  moment it is implemented.

Add real coverage here when these tasks are implemented.
"""


class TestAgentTaskRouting:
    """Tests for agent task routing configuration."""

    def test_agent_tasks_routed_to_agent_queue(self, mock_celery_app, resolve_queue):
        """Agent tasks should be routed to the agent queue.

        Asserts the LIVE router, not the declared dict -- the old version
        checked that a `rediska_worker.tasks.agent.*` key existed, which it did
        while matching no registered task at dispatch time.
        """
        assert resolve_queue(mock_celery_app, "agent.profile_summary") == "agent"
        assert resolve_queue(mock_celery_app, "agent.lead_scoring") == "agent"
        assert resolve_queue(mock_celery_app, "agent.draft_intro") == "agent"
