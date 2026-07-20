"""Unit tests for per-dimension agent input assembly.

Covers `BaseAnalysisAgent._build_agent_input`: which sections each dimension
receives, that the lead title/body are always present and never trimmed, that
raw comment dumps never reach any agent, and that the character budget sheds
the oldest posts first.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from rediska_core.config import Settings
from rediska_core.domain.services.agents import (
    DIMENSION_CONTEXT_SPECS,
    BaseAnalysisAgent,
)
from rediska_core.domain.services.agents.demographics import DemographicsAgent

DIMENSIONS = [
    "demographics",
    "preferences",
    "relationship_goals",
    "risk_flags",
    "sexual_preferences",
]

LEAD_TITLE = "35F looking for something real"
LEAD_BODY = "A distinctive lead body sentence that must always survive assembly."
INTERESTS_SUMMARY = "INTERESTS_SUMMARY_MARKER: hiking, pottery, live music."
CHARACTER_SUMMARY = "CHARACTER_SUMMARY_MARKER: warm, direct, a little sardonic."
PROFILE_SUMMARY = "PROFILE_SUMMARY_MARKER: active poster in local subreddits."
COMMENT_TEXT = "COMMENT_DUMP_MARKER: raw comment one. raw comment two."


@pytest.fixture
def agent() -> BaseAnalysisAgent:
    """A concrete agent; the assembly logic under test lives on the base class."""
    return DemographicsAgent(inference_client=None)


def _post(text: str, days_ago: int) -> dict:
    created = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {"text": text, "created_at": created.isoformat()}


@pytest.fixture
def input_context() -> dict:
    """A full context: every section available, so specs decide what is used."""
    return {
        "lead": {"title": LEAD_TITLE, "body": LEAD_BODY},
        "profile": {
            "username": "someone",
            "bio": "BIO_MARKER: pottery studio owner",
            "karma": 4321,
            "created_at": (
                datetime.now(timezone.utc) - timedelta(days=730)
            ).isoformat(),
            "is_verified": True,
            "post_text": "flat post blob",
            "comment_text": COMMENT_TEXT,
        },
        "summaries": {
            "user_interests": INTERESTS_SUMMARY,
            "user_character": CHARACTER_SUMMARY,
        },
        "items_by_type": {
            "post": [
                _post("NEWEST_POST_MARKER", 1),
                _post("MIDDLE_POST_MARKER", 30),
                _post("OLDEST_POST_MARKER", 365),
            ],
            "comment": [{"text": COMMENT_TEXT, "created_at": None}],
        },
    }


def _settings(**overrides) -> Settings:
    base = {
        "mysql_url": "mysql+pymysql://u:p@localhost:3306/rediska",
        "analysis_context_max_chars": 24000,
        "analysis_max_recent_posts": 10,
        "analysis_post_item_chars": 800,
    }
    base.update(overrides)
    return Settings(**base)


# -----------------------------------------------------------------------------
# 5.1 Per-dimension sections; title/body always present; comments never present
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_lead_title_and_body_always_present(agent, input_context, dimension):
    """Every dimension sees the lead post it is being asked to judge."""
    result = agent._build_agent_input(dimension, input_context)

    assert f"<title>{LEAD_TITLE}</title>" in result.prompt
    assert f"<body>{LEAD_BODY}</body>" in result.prompt
    assert "title" in result.sections
    assert "body" in result.sections


@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_raw_comment_dump_never_sent(agent, input_context, dimension):
    """The character summary replaces the raw comment dump for every dimension."""
    result = agent._build_agent_input(dimension, input_context)

    assert "<comments>" not in result.prompt
    assert COMMENT_TEXT not in result.prompt


@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_only_specd_sections_included(agent, input_context, dimension):
    """Sections outside the dimension's spec are absent from its input."""
    result = agent._build_agent_input(dimension, input_context)
    spec = DIMENSION_CONTEXT_SPECS[dimension]

    optional = {s for s in result.sections} - {"title", "body"}
    assert optional <= set(spec.sections)

    for section in set(DIMENSION_CONTEXT_SPECS["risk_flags"].sections) | set(
        DIMENSION_CONTEXT_SPECS["preferences"].sections
    ) | {"profile_summary"}:
        if section not in spec.sections:
            assert f"<{section}>" not in result.prompt


def test_total_chars_matches_prompt_length(agent, input_context):
    """The audit record's size is the real prompt size."""
    result = agent._build_agent_input("preferences", input_context)

    assert result.total_chars == len(result.prompt)
    assert result.audit_record()["total_chars"] == len(result.prompt)
    assert result.audit_record()["sections"] == result.sections
    assert result.audit_record()["prompt_excerpt"] == result.prompt[:2000]


# -----------------------------------------------------------------------------
# 5.3 Summaries and account metadata reach the dimensions that need them
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dimension", ["preferences", "relationship_goals", "sexual_preferences"]
)
def test_interests_summary_reaches_preference_dimensions(
    agent, input_context, dimension
):
    """The generated interests summary is no longer dead data."""
    result = agent._build_agent_input(dimension, input_context)

    assert INTERESTS_SUMMARY in result.prompt
    assert "interests_summary" in result.sections


def test_character_summary_reaches_risk_flags(agent, input_context):
    """The character summary stands in for the raw comments on risk_flags."""
    result = agent._build_agent_input("risk_flags", input_context)

    assert CHARACTER_SUMMARY in result.prompt
    assert "character_summary" in result.sections


def test_risk_flags_receives_account_metadata(agent, input_context):
    """Karma, account age, verification and bio are the strongest scam signals."""
    result = agent._build_agent_input("risk_flags", input_context)

    assert "account_metadata" in result.sections
    assert "karma=4321" in result.prompt
    assert "account_age_days=730" in result.prompt
    assert "verified=True" in result.prompt
    assert "BIO_MARKER" in result.prompt


def test_demographics_receives_profile_summary_only(agent, input_context):
    """Demographics reads the post itself plus the profile summary."""
    result = agent._build_agent_input("demographics", input_context)

    assert PROFILE_SUMMARY not in result.prompt  # not set in this fixture
    assert result.sections == ["title", "body"]

    input_context["profile"]["summary"] = PROFILE_SUMMARY
    result = agent._build_agent_input("demographics", input_context)

    assert PROFILE_SUMMARY in result.prompt
    assert result.sections == ["title", "body", "profile_summary"]


def test_account_metadata_omitted_when_unavailable(agent, input_context):
    """A profile with no fetched metadata renders no empty metadata block."""
    input_context["profile"] = {"post_text": "", "comment_text": ""}

    result = agent._build_agent_input("risk_flags", input_context)

    assert "account_metadata" not in result.sections
    assert "<account_metadata>" not in result.prompt


# -----------------------------------------------------------------------------
# 5.2 Budget trimming
# -----------------------------------------------------------------------------


def test_recent_posts_are_newest_first_and_capped(agent, input_context):
    """Posts arrive newest-first, limited by count and per-item chars."""
    with patch(
        "rediska_core.domain.services.agents.get_settings",
        return_value=_settings(analysis_max_recent_posts=2),
    ):
        result = agent._build_agent_input("preferences", input_context)

    assert "NEWEST_POST_MARKER" in result.prompt
    assert "MIDDLE_POST_MARKER" in result.prompt
    assert "OLDEST_POST_MARKER" not in result.prompt
    assert result.prompt.index("NEWEST_POST_MARKER") < result.prompt.index(
        "MIDDLE_POST_MARKER"
    )


def test_per_item_char_cap_applies(agent, input_context):
    """Each post is truncated individually before assembly."""
    input_context["items_by_type"]["post"] = [_post("x" * 5000, 1)]

    with patch(
        "rediska_core.domain.services.agents.get_settings",
        return_value=_settings(analysis_post_item_chars=100),
    ):
        result = agent._build_agent_input("preferences", input_context)

    assert "x" * 100 in result.prompt
    assert "x" * 101 not in result.prompt


def test_budget_drops_oldest_posts_first(agent, input_context):
    """Over budget, the oldest post goes before the newest."""
    input_context["items_by_type"]["post"] = [
        _post("NEWEST " + "n" * 400, 1),
        _post("MIDDLE " + "m" * 400, 30),
        _post("OLDEST " + "o" * 400, 365),
    ]

    # Room for the lead + roughly one post.
    budget = len(LEAD_TITLE) + len(LEAD_BODY) + len(INTERESTS_SUMMARY) + 700

    with patch(
        "rediska_core.domain.services.agents.get_settings",
        return_value=_settings(analysis_context_max_chars=budget),
    ):
        result = agent._build_agent_input("preferences", input_context)

    assert result.total_chars <= budget
    assert "OLDEST" not in result.prompt
    assert "NEWEST" in result.prompt
    assert LEAD_BODY in result.prompt


def test_budget_preserves_title_and_body_when_severe(agent, input_context):
    """A budget smaller than every optional section still keeps the lead post."""
    with patch(
        "rediska_core.domain.services.agents.get_settings",
        return_value=_settings(analysis_context_max_chars=1),
    ):
        for dimension in DIMENSIONS:
            result = agent._build_agent_input(dimension, input_context)

            assert LEAD_TITLE in result.prompt
            assert LEAD_BODY in result.prompt
            assert result.sections == ["title", "body"]


def test_oversized_lead_body_is_never_trimmed(agent, input_context):
    """The lead body is the one thing the budget may not touch."""
    huge_body = "B" * 50000
    input_context["lead"]["body"] = huge_body

    with patch(
        "rediska_core.domain.services.agents.get_settings",
        return_value=_settings(analysis_context_max_chars=1000),
    ):
        result = agent._build_agent_input("preferences", input_context)

    assert huge_body in result.prompt
    assert result.sections == ["title", "body"]


def test_within_budget_keeps_all_specd_sections(agent, input_context):
    """Nothing is dropped when the assembled input already fits."""
    with patch(
        "rediska_core.domain.services.agents.get_settings",
        return_value=_settings(analysis_context_max_chars=24000),
    ):
        result = agent._build_agent_input("preferences", input_context)

    assert result.sections == ["title", "body", "interests_summary", "recent_posts"]
    assert result.total_chars <= 24000


# -----------------------------------------------------------------------------
# Fallbacks
# -----------------------------------------------------------------------------


def test_recent_posts_fall_back_to_flat_post_text(agent, input_context):
    """Contexts without structured items still supply posts from the blob."""
    del input_context["items_by_type"]

    result = agent._build_agent_input("preferences", input_context)

    assert "flat post blob" in result.prompt
    assert "recent_posts" in result.sections


def test_unknown_dimension_uses_default_spec(agent, input_context):
    """A dimension without a spec entry still gets a bounded, sane input."""
    input_context["profile"]["summary"] = PROFILE_SUMMARY

    result = agent._build_agent_input("some_future_dimension", input_context)

    assert result.sections == ["title", "body", "profile_summary"]
    assert COMMENT_TEXT not in result.prompt


def test_account_age_days_handles_missing_and_malformed(agent):
    """Age parsing degrades to None rather than raising."""
    assert BaseAnalysisAgent._account_age_days(None) is None
    assert BaseAnalysisAgent._account_age_days("not-a-date") is None
    assert BaseAnalysisAgent._account_age_days(
        datetime.now(timezone.utc) - timedelta(days=10)
    ) == 10


def test_build_input_prompt_delegates(agent, input_context):
    """The legacy helper returns the assembled prompt."""
    assert agent._build_input_prompt("preferences", input_context) == (
        agent._build_agent_input("preferences", input_context).prompt
    )
