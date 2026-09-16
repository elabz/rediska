"""List-typed agent output fields must tolerate null and comma-separated strings."""

from rediska_core.domain.schemas.multi_agent_analysis import (
    PreferencesOutput,
    RelationshipGoalsOutput,
    _coerce_evidence_items,
)
from rediska_core.domain.services.character_summary import CharacterSummaryOutput


def test_helper_shapes():
    assert _coerce_evidence_items(None) == []
    assert _coerce_evidence_items("helpful, supportive") == ["helpful", "supportive"]
    assert _coerce_evidence_items("a; b\nc,, ") == ["a", "b", "c"]
    assert _coerce_evidence_items({"quote": "q"}) == ["q"]
    assert _coerce_evidence_items(["x", {"quote": "y"}]) == ["x", "y"]
    assert _coerce_evidence_items(7) == ["7"]


def test_relationship_goals_null_history_validates():
    out = RelationshipGoalsOutput.model_validate({
        "relationship_intent": "serious",
        "intent_confidence": 0.8,
        "relationship_history": None,
        "deal_breakers": "smokers, liars",
    })
    assert out.relationship_history == []
    assert out.deal_breakers == ["smokers", "liars"]


def test_preferences_string_hobbies_validate():
    out = PreferencesOutput.model_validate({"hobbies": "hiking, cooking", "kinks": None})
    assert out.hobbies == ["hiking", "cooking"]
    assert out.kinks == []


def test_character_summary_camelcase_string_traits():
    out = CharacterSummaryOutput.model_validate({
        "communicationStyle": "casual",
        "personalityTraits": "helpful, supportive",
        "redFlags": None,
    })
    assert out.personality_traits == ["helpful", "supportive"]
    assert out.red_flags == []
