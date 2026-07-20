"""Unit tests for scout watch auto-promotion on the computed gate verdict."""

from rediska_worker.tasks.scout import _should_promote


def verdict(recommendation: str, score: float) -> dict:
    return {"recommendation": recommendation, "score": score, "gate_results": []}


class TestShouldPromote:
    """Promotion requires gate verdict `suitable` AND computed score ≥ min_confidence."""

    def test_suitable_at_threshold_promotes(self):
        assert _should_promote(verdict("suitable", 0.7), 0.7) is True

    def test_suitable_above_threshold_promotes(self):
        assert _should_promote(verdict("suitable", 0.95), 0.7) is True

    def test_suitable_below_threshold_does_not_promote(self):
        assert _should_promote(verdict("suitable", 0.65), 0.7) is False

    def test_needs_review_never_promotes_regardless_of_score(self):
        assert _should_promote(verdict("needs_review", 0.99), 0.5) is False

    def test_not_recommended_never_promotes(self):
        assert _should_promote(verdict("not_recommended", 0.99), 0.5) is False

    def test_missing_score_does_not_promote(self):
        assert _should_promote({"recommendation": "suitable"}, 0.5) is False

    def test_missing_recommendation_does_not_promote(self):
        assert _should_promote({"score": 0.9}, 0.5) is False

    def test_suitable_band_floor_clears_default_thresholds(self):
        # Suitable band starts at 0.6, so a 0.5 threshold always passes a
        # suitable verdict, while 0.7 demands genuine margin.
        assert _should_promote(verdict("suitable", 0.6), 0.5) is True
        assert _should_promote(verdict("suitable", 0.6), 0.7) is False
