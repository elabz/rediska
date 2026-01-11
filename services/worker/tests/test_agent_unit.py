"""Unit tests for agent tasks.

Tests cover:
- profile_summary task
- lead_scoring task
- draft_intro task
"""

from unittest.mock import MagicMock, patch

import pytest


class TestProfileSummaryTask:
    """Tests for profile_summary task."""

    def test_task_is_registered(self, mock_celery_app):
        """Task should be registered with Celery."""
        from rediska_worker.tasks.agent import profile_summary

        assert profile_summary.name == "agent.profile_summary"

    def test_returns_not_implemented(self, mock_celery_app):
        """Task should return not_implemented status (stub)."""
        from rediska_worker.tasks.agent import profile_summary

        result = profile_summary(account_id=123)

        assert result["status"] == "not_implemented"
        assert result["account_id"] == 123

    def test_accepts_account_id(self, mock_celery_app):
        """Task should accept account_id parameter."""
        from rediska_worker.tasks.agent import profile_summary

        result = profile_summary(456)

        assert result["account_id"] == 456


class TestLeadScoringTask:
    """Tests for lead_scoring task."""

    def test_task_is_registered(self, mock_celery_app):
        """Task should be registered with Celery."""
        from rediska_worker.tasks.agent import lead_scoring

        assert lead_scoring.name == "agent.lead_scoring"

    def test_returns_not_implemented(self, mock_celery_app):
        """Task should return not_implemented status (stub)."""
        from rediska_worker.tasks.agent import lead_scoring

        result = lead_scoring(lead_post_id=789)

        assert result["status"] == "not_implemented"
        assert result["lead_post_id"] == 789

    def test_accepts_lead_post_id(self, mock_celery_app):
        """Task should accept lead_post_id parameter."""
        from rediska_worker.tasks.agent import lead_scoring

        result = lead_scoring(999)

        assert result["lead_post_id"] == 999


class TestDraftIntroTask:
    """Tests for draft_intro task."""

    def test_task_is_registered(self, mock_celery_app):
        """Task should be registered with Celery."""
        from rediska_worker.tasks.agent import draft_intro

        assert draft_intro.name == "agent.draft_intro"

    def test_returns_not_implemented(self, mock_celery_app):
        """Task should return not_implemented status (stub)."""
        from rediska_worker.tasks.agent import draft_intro

        result = draft_intro(target_account_id=123)

        assert result["status"] == "not_implemented"
        assert result["target_account_id"] == 123

    def test_accepts_optional_context(self, mock_celery_app):
        """Task should accept optional context parameter."""
        from rediska_worker.tasks.agent import draft_intro

        result = draft_intro(123, context="Previous conversation about Python")

        assert result["status"] == "not_implemented"
        assert result["target_account_id"] == 123


class TestAgentTaskRouting:
    """Tests for agent task routing configuration."""

    def test_agent_tasks_routed_to_agent_queue(self, mock_celery_app):
        """Agent tasks should be routed to agent queue."""
        routes = mock_celery_app.conf.task_routes

        assert "rediska_worker.tasks.agent.*" in routes
        assert routes["rediska_worker.tasks.agent.*"]["queue"] == "agent"


class TestAgentTaskNames:
    """Tests for agent task naming conventions."""

    def test_all_agent_tasks_have_correct_prefix(self, mock_celery_app):
        """All agent tasks should have 'agent.' prefix."""
        from rediska_worker.tasks import agent

        tasks = [
            agent.profile_summary,
            agent.lead_scoring,
            agent.draft_intro,
        ]

        for task in tasks:
            assert task.name.startswith("agent."), f"{task.name} should start with 'agent.'"


class TestAgentTaskReturns:
    """Tests for agent task return values."""

    def test_profile_summary_returns_dict(self, mock_celery_app):
        """profile_summary should return a dictionary."""
        from rediska_worker.tasks.agent import profile_summary

        result = profile_summary(1)

        assert isinstance(result, dict)

    def test_lead_scoring_returns_dict(self, mock_celery_app):
        """lead_scoring should return a dictionary."""
        from rediska_worker.tasks.agent import lead_scoring

        result = lead_scoring(1)

        assert isinstance(result, dict)

    def test_draft_intro_returns_dict(self, mock_celery_app):
        """draft_intro should return a dictionary."""
        from rediska_worker.tasks.agent import draft_intro

        result = draft_intro(1)

        assert isinstance(result, dict)
