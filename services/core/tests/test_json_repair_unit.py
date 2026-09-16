"""Unit tests for the tolerant JSON repair applied to model output.

All samples are synthetic reproductions of failure shapes seen in analysis_dimensions.
"""

import json

import pytest

from rediska_core.domain.services.chat_templates import _repair_json, get_chat_template


def parse(text: str) -> dict:
    return json.loads(_repair_json(text))


class TestRepairJson:
    def test_valid_json_untouched(self):
        raw = '{"a": 1, "b": ["x", "y"]}'
        assert _repair_json(raw) == raw

    def test_trailing_commas(self):
        assert parse('{"a": [1, 2,], "b": 3,}') == {"a": [1, 2], "b": 3}

    def test_bare_strings_inside_object_become_true_members(self):
        # relationship_goals.partner_criteria emitted as {} with list items inside
        raw = '''{
  "relationship_intent": "serious",
  "partner_criteria": {
    "age": "35-55",
    "athletic/average/dad bod",
    "glasses",
    "open-minded"
  },
  "deal_breakers": ["smoking"]
}'''
        data = parse(raw)
        assert data["relationship_intent"] == "serious"
        assert data["partner_criteria"]["age"] == "35-55"
        assert data["partner_criteria"]["glasses"] is True
        assert data["deal_breakers"] == ["smoking"]

    def test_unescaped_inner_quotes(self):
        raw = '{"evidence": ["He wrote "hi there" twice", "plain"], "n": 1}'
        data = parse(raw)
        assert data["evidence"][0] == 'He wrote "hi there" twice'
        assert data["n"] == 1

    def test_literal_newlines_inside_strings(self):
        raw = '{"summary": "line one\nline two", "k": 2}'
        assert parse(raw)["summary"] == "line one\nline two"

    def test_truncated_output_closes_containers(self):
        raw = '{"hobbies": ["hiking", "reading"], "kinks": ["a", "b"], "lifestyle": "active, outdoorsy and'
        data = parse(raw)
        assert data["hobbies"] == ["hiking", "reading"]
        assert data["lifestyle"].startswith("active")

    def test_truncated_after_key(self):
        raw = '{"hobbies": ["hiking"], "compatibility_score":'
        assert parse(raw) == {"hobbies": ["hiking"]}

    def test_hopeless_input_returns_original(self):
        raw = 'not json at all'
        assert _repair_json(raw) == raw

    def test_template_extract_json_repairs(self):
        template = get_chat_template("llama3")
        raw = 'Here you go:\n{"a": {"x": "1", "loose"}, "b": [1,],}\nDone.'
        assert json.loads(template.extract_json(raw)) == {"a": {"x": "1", "loose": True}, "b": [1]}

    def test_truncated_inside_bare_object_member(self):
        # Log-truncated output cut inside a bare string sitting in key position
        raw = '{"relationship_intent": "serious", "partner_criteria": {"age": "35-55", "glasses", "self-ass'
        data = parse(raw)
        assert data["relationship_intent"] == "serious"
        assert data["partner_criteria"]["age"] == "35-55"
        assert data["partner_criteria"]["glasses"] is True
