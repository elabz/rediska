"""Unit tests for deterministic lead priority tiering (lead-triage-and-feedback)."""

import pytest

from rediska_core.domain.services.lead_gates import GateResult, GateVerdict
from rediska_core.domain.services.lead_priority import (
    derive_priority,
    priority_for_analysis,
    priority_from_stored_results,
)


def _verdict(*statuses: str) -> GateVerdict:
    results = [GateResult(f"g{i}", s, "r") for i, s in enumerate(statuses)]
    rec = (
        "not_recommended" if "fail" in statuses
        else "needs_review" if "unclear" in statuses
        else "suitable"
    )
    return GateVerdict(recommendation=rec, score=0.5, gate_results=results)


class TestDerivePriority:
    @pytest.mark.parametrize("level", ["high", "medium", "low"])
    def test_high_compatibility_with_clean_gates_promotes(self, level):
        assert derive_priority(level, 0.7, all_gates_passed=True) == "high"

    def test_high_compatibility_without_clean_gates_keeps_base(self):
        assert derive_priority("low", 0.9, all_gates_passed=False) == "low"

    @pytest.mark.parametrize(
        "level,expected", [("high", "medium"), ("medium", "low"), ("low", "low")]
    )
    def test_low_compatibility_demotes_one_tier(self, level, expected):
        assert derive_priority(level, 0.49, all_gates_passed=True) == expected

    def test_mid_compatibility_keeps_base(self):
        assert derive_priority("low", 0.5, all_gates_passed=True) == "low"
        assert derive_priority("high", 0.69, all_gates_passed=False) == "high"

    @pytest.mark.parametrize("level", [None, "", "urgent", 3])
    def test_missing_or_unknown_level_starts_medium(self, level):
        assert derive_priority(level, None, all_gates_passed=True) == "medium"

    def test_missing_compatibility_neither_promotes_nor_demotes(self):
        assert derive_priority("LOW ", None, all_gates_passed=True) == "low"


class TestPriorityForAnalysis:
    def test_wrapped_results_and_gate_verdict(self):
        dims = {"preferences": {"success": True, "parsed_output": {"compatibility_score": 0.9}}}
        meta = {"priority_level": "low"}
        priority, compat = priority_for_analysis(dims, meta, _verdict("pass", "pass"))
        assert (priority, compat) == ("high", 0.9)

    def test_unclear_gate_blocks_promotion(self):
        dims = {"preferences": {"success": True, "parsed_output": {"compatibility_score": 0.9}}}
        priority, _ = priority_for_analysis(
            dims, {"priority_level": "medium"}, _verdict("pass", "unclear")
        )
        assert priority == "medium"

    def test_failed_preferences_dimension_has_no_compatibility(self):
        dims = {"preferences": {"success": False, "parsed_output": None}}
        priority, compat = priority_for_analysis(dims, None, _verdict("pass"))
        assert (priority, compat) == ("medium", None)

    def test_compatibility_is_clamped(self):
        dims = {"preferences": {"compatibility_score": "1.4"}}
        _, compat = priority_for_analysis(dims, None, None)
        assert compat == 1.0

    def test_stored_flat_results(self):
        stored = {
            "preferences": {"compatibility_score": 0.2},
            "meta_analysis": {"priority_level": "high"},
            "gate_verdict": {
                "recommendation": "needs_review",
                "gate_results": [{"gate": "location", "status": "unclear"}],
            },
        }
        assert priority_from_stored_results(stored) == ("medium", 0.2)

    def test_stored_results_empty(self):
        assert priority_from_stored_results({}) == (None, None)
        assert priority_from_stored_results(None) == (None, None)
