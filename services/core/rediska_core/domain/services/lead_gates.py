"""Deterministic hard-gate evaluation for lead analysis.

Pure functions over structured dimension outputs — no DB or LLM access.
The five hard gates (gender, location, D/s compatibility, partner max age,
authenticity) are evaluated here, fail-closed: a missing, failed, or
unparseable gate input yields ``unclear``, never ``pass``.

Verdict rule: any gate ``fail`` → ``not_recommended``; otherwise any gate
``unclear`` → ``needs_review``; otherwise ``suitable``.

The confidence score is computed deterministically, banded by recommendation,
with weighted margins from the preferences compatibility score and
per-dimension self-reported confidences. Model-reported confidence is never
used for gating and no default substitutes for a missing value.
"""

from dataclasses import dataclass, field
from typing import Any

from rediska_core.config import get_settings

# Gate names
GATE_GENDER = "gender"
GATE_LOCATION = "location"
GATE_DS = "ds_compatibility"
GATE_AGE = "age_acceptance"
GATE_AUTHENTICITY = "authenticity"

GATES = [GATE_GENDER, GATE_LOCATION, GATE_DS, GATE_AGE, GATE_AUTHENTICITY]

# Score bands per recommendation: (low, high). The computed score always
# lands inside its recommendation's band, so bands are directly comparable
# against scout `min_confidence` thresholds (a gate-passing lead starts at 0.6).
SCORE_BANDS: dict[str, tuple[float, float]] = {
    "not_recommended": (0.0, 0.3),
    "needs_review": (0.3, 0.6),
    "suitable": (0.6, 1.0),
}

# Margin weights (calibration starting point — tune via feedback-loop work)
WEIGHT_COMPATIBILITY = 0.15  # preferences.compatibility_score
WEIGHT_GATE_CONFIDENCE = 0.05  # per gate, dimension self-reported confidence
WEIGHT_AUTHENTICITY_CLEAN = 0.10  # no red flags and no scam indicators
_MAX_MARGIN = (
    WEIGHT_COMPATIBILITY
    + WEIGHT_GATE_CONFIDENCE * len(GATES)
    + WEIGHT_AUTHENTICITY_CLEAN
)


@dataclass(frozen=True)
class UserConstraints:
    """The user's own constraints consumed by the gates.

    Sourced from settings (``USER_AGE`` / ``USER_DS_ORIENTATION`` env vars),
    not from prompt text.
    """

    age: int = 45
    ds_orientation: str = "dominant"

    @classmethod
    def from_settings(cls) -> "UserConstraints":
        settings = get_settings()
        return cls(
            age=settings.user_age,
            ds_orientation=settings.user_ds_orientation,
        )


@dataclass
class GateResult:
    gate: str
    status: str  # pass | fail | unclear
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"gate": self.gate, "status": self.status, "reason": self.reason}


@dataclass
class GateVerdict:
    recommendation: str  # suitable | not_recommended | needs_review
    score: float
    gate_results: list[GateResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation": self.recommendation,
            "score": self.score,
            "gate_results": [g.to_dict() for g in self.gate_results],
        }

    def failed_gates(self) -> list[GateResult]:
        return [g for g in self.gate_results if g.status == "fail"]

    def unclear_gates(self) -> list[GateResult]:
        return [g for g in self.gate_results if g.status == "unclear"]

    def summary(self) -> str:
        """Human-readable one-line summary of non-passing gates."""
        problems = [
            f"{g.gate} {g.status}: {g.reason}"
            for g in self.gate_results
            if g.status != "pass"
        ]
        if not problems:
            return "All gates passed"
        return "; ".join(problems)


def _dimension_output(
    dimension_results: dict[str, Any], dimension: str
) -> dict[str, Any] | None:
    """Return a dimension's parsed output, or None if failed/missing/unparseable."""
    result = dimension_results.get(dimension)
    if not isinstance(result, dict):
        return None
    if not result.get("success"):
        return None
    output = result.get("parsed_output")
    if not isinstance(output, dict):
        return None
    return output


def _confidence(output: dict[str, Any] | None, key: str) -> float:
    """A dimension's self-reported confidence in [0, 1]; 0.0 when missing (no default)."""
    if not output:
        return 0.0
    try:
        value = float(output[key])
    except (KeyError, TypeError, ValueError):
        return 0.0
    return min(max(value, 0.0), 1.0)


def _gate_gender(demo: dict[str, Any] | None) -> GateResult:
    if demo is None:
        return GateResult(GATE_GENDER, "unclear", "demographics dimension missing or failed")
    gender = demo.get("gender")
    if not isinstance(gender, str) or not gender.strip():
        return GateResult(GATE_GENDER, "unclear", "gender field missing")
    value = gender.strip().lower()
    if value in ("female", "non-binary", "nonbinary", "non binary"):
        return GateResult(GATE_GENDER, "pass", f"gender is {value}")
    if value == "male":
        return GateResult(GATE_GENDER, "fail", "post author is male")
    return GateResult(GATE_GENDER, "unclear", f"gender is unrecognized: {value!r}")


def _gate_location(demo: dict[str, Any] | None) -> GateResult:
    if demo is None:
        return GateResult(GATE_LOCATION, "unclear", "demographics dimension missing or failed")
    state = demo.get("location_state")
    if not isinstance(state, str) or not state.strip():
        return GateResult(GATE_LOCATION, "unclear", "location_state field missing")
    value = state.strip().lower()
    if value == "near":
        return GateResult(GATE_LOCATION, "pass", "location is near")
    if value == "far":
        return GateResult(GATE_LOCATION, "fail", "location is far")
    return GateResult(GATE_LOCATION, "unclear", f"location is {value}")


def _gate_ds(sexual: dict[str, Any] | None, constraints: UserConstraints) -> GateResult:
    if sexual is None:
        return GateResult(GATE_DS, "unclear", "sexual_preferences dimension missing or failed")
    orientation = sexual.get("ds_orientation")
    if not isinstance(orientation, str) or not orientation.strip():
        return GateResult(GATE_DS, "unclear", "ds_orientation field missing")
    value = orientation.strip().lower()
    user = constraints.ds_orientation.strip().lower()
    compatible = {
        "dominant": {"submissive", "switch"},
        "submissive": {"dominant", "switch"},
        "switch": {"dominant", "submissive", "switch"},
    }.get(user, set())
    known = {"dominant", "submissive", "switch"}
    if value not in known:
        return GateResult(GATE_DS, "unclear", f"ds_orientation is unrecognized: {value!r}")
    if value in compatible:
        return GateResult(GATE_DS, "pass", f"author is {value}, user is {user}")
    return GateResult(
        GATE_DS, "fail", f"author is {value}, incompatible with {user} user"
    )


def _gate_age(goals: dict[str, Any] | None, constraints: UserConstraints) -> GateResult:
    if goals is None:
        return GateResult(GATE_AGE, "unclear", "relationship_goals dimension missing or failed")
    raw = goals.get("partner_max_age")
    if raw is None:
        return GateResult(GATE_AGE, "unclear", "partner_max_age field missing")
    if isinstance(raw, str) and raw.strip().lower() in ("no_max_age", "no max age"):
        return GateResult(GATE_AGE, "pass", "no maximum partner age stated")
    try:
        max_age = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return GateResult(
            GATE_AGE, "unclear", f"partner_max_age is unparseable: {raw!r}"
        )
    if max_age <= 0:
        return GateResult(
            GATE_AGE, "unclear", f"partner_max_age is implausible: {raw!r}"
        )
    if max_age >= constraints.age:
        return GateResult(
            GATE_AGE, "pass", f"accepts partners up to {max_age} (user is {constraints.age})"
        )
    return GateResult(
        GATE_AGE,
        "fail",
        f"wants partner no older than {max_age}, user is {constraints.age}",
    )


def _red_flag_list(risk: dict[str, Any], key: str) -> list[Any]:
    value = risk.get(key)
    if isinstance(value, list):
        return value
    if value:
        return [value]
    return []


def _gate_authenticity(risk: dict[str, Any] | None) -> GateResult:
    if risk is None:
        return GateResult(GATE_AUTHENTICITY, "unclear", "risk_flags dimension missing or failed")
    is_authentic = risk.get("is_authentic")
    if not isinstance(is_authentic, bool):
        return GateResult(GATE_AUTHENTICITY, "unclear", "is_authentic field missing")
    if is_authentic is False:
        return GateResult(GATE_AUTHENTICITY, "fail", "assessed as not authentic")
    red_flags = _red_flag_list(risk, "red_flags")
    if red_flags:
        return GateResult(
            GATE_AUTHENTICITY,
            "fail",
            f"red flags present: {', '.join(str(f) for f in red_flags[:5])}",
        )
    return GateResult(GATE_AUTHENTICITY, "pass", "authentic, no red flags")


def compute_score(
    recommendation: str,
    dimension_results: dict[str, Any],
) -> float:
    """Compute the deterministic confidence score for a recommendation.

    The score is banded by recommendation (see SCORE_BANDS); within the band,
    weighted margins from the preferences compatibility score, per-gate
    dimension confidences, and authenticity cleanliness move the score up.
    Missing inputs contribute 0 — no defaults.
    """
    low, high = SCORE_BANDS.get(recommendation, SCORE_BANDS["needs_review"])

    demo = _dimension_output(dimension_results, "demographics")
    prefs = _dimension_output(dimension_results, "preferences")
    goals = _dimension_output(dimension_results, "relationship_goals")
    risk = _dimension_output(dimension_results, "risk_flags")
    sexual = _dimension_output(dimension_results, "sexual_preferences")

    margin = 0.0
    margin += WEIGHT_COMPATIBILITY * _confidence(prefs, "compatibility_score")
    margin += WEIGHT_GATE_CONFIDENCE * _confidence(demo, "gender_confidence")
    margin += WEIGHT_GATE_CONFIDENCE * _confidence(demo, "location_confidence")
    margin += WEIGHT_GATE_CONFIDENCE * _confidence(sexual, "ds_orientation_confidence")
    margin += WEIGHT_GATE_CONFIDENCE * _confidence(goals, "intent_confidence")
    # Fifth gate (authenticity) has no self-reported confidence field; its
    # cleanliness contribution stands in for it.
    if risk is not None and not _red_flag_list(risk, "red_flags") and not _red_flag_list(
        risk, "scam_indicators"
    ):
        margin += WEIGHT_GATE_CONFIDENCE  # authenticity gate confidence proxy
        margin += WEIGHT_AUTHENTICITY_CLEAN

    fraction = min(margin / _MAX_MARGIN, 1.0)
    return round(low + fraction * (high - low), 3)


def evaluate_gates(
    dimension_results: dict[str, Any],
    constraints: UserConstraints | None = None,
) -> GateVerdict:
    """Evaluate the five hard gates over structured dimension outputs.

    Args:
        dimension_results: Results keyed by dimension name, each a dict with
            ``success`` and ``parsed_output`` (as produced by
            ``MultiAgentAnalysisService._run_dimension_agents``).
        constraints: The user's own constraints; defaults to settings values.

    Returns:
        GateVerdict with recommendation, computed score, and per-gate results.
    """
    if constraints is None:
        constraints = UserConstraints.from_settings()

    demo = _dimension_output(dimension_results, "demographics")
    goals = _dimension_output(dimension_results, "relationship_goals")
    risk = _dimension_output(dimension_results, "risk_flags")
    sexual = _dimension_output(dimension_results, "sexual_preferences")

    gate_results = [
        _gate_gender(demo),
        _gate_location(demo),
        _gate_ds(sexual, constraints),
        _gate_age(goals, constraints),
        _gate_authenticity(risk),
    ]

    if any(g.status == "fail" for g in gate_results):
        recommendation = "not_recommended"
    elif any(g.status == "unclear" for g in gate_results):
        recommendation = "needs_review"
    else:
        recommendation = "suitable"

    score = compute_score(recommendation, dimension_results)
    return GateVerdict(
        recommendation=recommendation, score=score, gate_results=gate_results
    )
