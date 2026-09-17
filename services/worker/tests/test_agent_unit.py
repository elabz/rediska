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

import pytest


class TestAgentTaskRouting:
    """Tests for agent task routing configuration."""

    def test_agent_tasks_routed_to_agent_queue(self, mock_celery_app):
        """Agent tasks should be routed to agent queue.

        NOTE: this asserts the declared task_routes config. It does NOT prove
        the route is effective -- the registered task names are `agent.*`, not
        `rediska_worker.tasks.agent.*`, so this pattern never actually matches
        at dispatch time and these tasks fall through to the default queue.
        See the routing note in the review report.
        """
        routes = mock_celery_app.conf.task_routes

        assert "rediska_worker.tasks.agent.*" in routes
        assert routes["rediska_worker.tasks.agent.*"]["queue"] == "agent"
