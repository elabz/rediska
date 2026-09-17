"""Deterministic lead priority tiering from analysis signals.

Pure functions — no DB or LLM access. The tier starts from the advisory meta
agent's ``priority_level`` and is adjusted in code by the preferences
``compatibility_score`` and the gate verdict:

- promote to ``high`` when compatibility >= PROMOTE_THRESHOLD and every hard
  gate passed;
- otherwise demote one tier when compatibility < DEMOTE_THRESHOLD.

A missing or unrecognised meta level starts at ``medium``; a missing
compatibility score neither promotes nor demotes.
"""

from typing import Any, Optional

from rediska_core.domain.services.lead_gates import GateVerdict

PRIORITY_HIGH = "high"
PRIORITY_MEDIUM = "medium"
PRIORITY_LOW = "low"

# Ascending order; demotion moves one step left.
TIERS = [PRIORITY_LOW, PRIORITY_MEDIUM, PRIORITY_HIGH]

# Thresholds from the preferences compatibility rubric (0.2 / 0.5 / 0.7 / 0.9);
# revisit against the calibration report.
PROMOTE_THRESHOLD = 0.7
DEMOTE_THRESHOLD = 0.5


def _normalize_level(level: Any) -> str:
    if isinstance(level, str) and level.strip().lower() in TIERS:
        return level.strip().lower()
    return PRIORITY_MEDIUM


def _as_score(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return min(max(score, 0.0), 1.0)


def derive_priority(
    meta_priority_level: Any,
    compatibility_score: Optional[float],
    all_gates_passed: bool,
) -> str:
    """Derive a priority tier (high / medium / low)."""
    tier = _normalize_level(meta_priority_level)
    if compatibility_score is None:
        return tier
    if compatibility_score >= PROMOTE_THRESHOLD and all_gates_passed:
        return PRIORITY_HIGH
    if compatibility_score < DEMOTE_THRESHOLD:
        return TIERS[max(TIERS.index(tier) - 1, 0)]
    return tier


def _gates_passed(verdict: GateVerdict | dict[str, Any] | None) -> bool:
    if verdict is None:
        return False
    if isinstance(verdict, GateVerdict):
        verdict = verdict.to_dict()
    gate_results = verdict.get("gate_results")
    if isinstance(gate_results, list) and gate_results:
        return all(
            isinstance(g, dict) and g.get("status") == "pass" for g in gate_results
        )
    return verdict.get("recommendation") == "suitable"


def _unwrap(result: Any) -> Optional[dict[str, Any]]:
    """Accept a dimension result wrapper ({success, parsed_output}) or a bare output."""
    if not isinstance(result, dict):
        return None
    if "parsed_output" in result or "success" in result:
        if not result.get("success", True):
            return None
        output = result.get("parsed_output")
        return output if isinstance(output, dict) else None
    return result


def priority_for_analysis(
    dimension_results: dict[str, Any] | None,
    meta_output: dict[str, Any] | None,
    verdict: GateVerdict | dict[str, Any] | None,
) -> tuple[str, Optional[float]]:
    """Return ``(priority, compatibility_score)`` for one analysis.

    ``dimension_results`` may hold result wrappers (live pipeline) or bare
    parsed outputs (``scout_watch_posts.dimension_results_json``).
    """
    results = dimension_results or {}
    prefs = _unwrap(results.get("preferences"))
    compatibility = _as_score(prefs.get("compatibility_score")) if prefs else None
    meta = _unwrap(meta_output) if meta_output is not None else None
    level = meta.get("priority_level") if meta else None
    return derive_priority(level, compatibility, _gates_passed(verdict)), compatibility


def priority_from_stored_results(
    stored: dict[str, Any] | None,
) -> tuple[Optional[str], Optional[float]]:
    """Priority from a scout post's stored ``dimension_results_json``.

    Returns ``(None, None)`` when the post has no stored analysis output.
    """
    if not isinstance(stored, dict) or not stored:
        return None, None
    return priority_for_analysis(
        stored, stored.get("meta_analysis"), stored.get("gate_verdict")
    )


__all__ = [
    "PRIORITY_HIGH",
    "PRIORITY_MEDIUM",
    "PRIORITY_LOW",
    "PROMOTE_THRESHOLD",
    "DEMOTE_THRESHOLD",
    "derive_priority",
    "priority_for_analysis",
    "priority_from_stored_results",
]
