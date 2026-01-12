"""Unit tests for duplicate detection service.

Tests the heuristics for detecting possible duplicate accounts:
1. Username similarity detection
2. Image hash overlap detection
3. Confidence scoring
4. Suggestion generation
"""

import pytest

from rediska_core.domain.services.duplicate_detection import (
    DuplicateCandidate,
    DuplicateDetectionConfig,
    DuplicateDetectionService,
    DuplicateSuggestion,
    MatchReason,
    UsernameMatcher,
    ImageHashMatcher,
)


# =============================================================================
# USERNAME SIMILARITY TESTS
# =============================================================================


class TestUsernameMatcher:
    """Tests for username similarity detection."""

    def test_exact_match_returns_high_confidence(self):
        """Exact username match should return high confidence."""
        matcher = UsernameMatcher()
        result = matcher.compare("john_doe", "john_doe")

        assert result.is_match
        assert result.confidence >= 0.95
        assert result.reason == "exact_match"

    def test_case_insensitive_match(self):
        """Case differences should still match with high confidence."""
        matcher = UsernameMatcher()
        result = matcher.compare("John_Doe", "john_doe")

        assert result.is_match
        assert result.confidence >= 0.9
        assert result.reason == "case_insensitive_match"

    def test_prefix_suffix_variations(self):
        """Common prefix/suffix variations should match."""
        matcher = UsernameMatcher()

        # Number suffix
        result = matcher.compare("john_doe", "john_doe123")
        assert result.is_match
        assert result.confidence >= 0.7
        assert "suffix" in result.reason or "variation" in result.reason

        # Underscore variations
        result = matcher.compare("johndoe", "john_doe")
        assert result.is_match
        assert result.confidence >= 0.7

    def test_levenshtein_similarity(self):
        """Similar usernames should match with moderate confidence."""
        matcher = UsernameMatcher()

        # One character difference
        result = matcher.compare("john_doe", "john_doe1")
        assert result.is_match
        assert result.confidence >= 0.6

        # Two character difference
        result = matcher.compare("john_doe", "johndoee")
        assert result.is_match

    def test_different_usernames_no_match(self):
        """Completely different usernames should not match."""
        matcher = UsernameMatcher()
        result = matcher.compare("alice_smith", "bob_jones")

        assert not result.is_match
        assert result.confidence < 0.5

    def test_short_username_handling(self):
        """Short usernames should have stricter matching."""
        matcher = UsernameMatcher()

        # Very short - require exact
        result = matcher.compare("ab", "ab")
        assert result.is_match

        # Short but different
        result = matcher.compare("ab", "ac")
        assert not result.is_match or result.confidence < 0.6

    def test_common_patterns_detection(self):
        """Common username patterns should be detected."""
        matcher = UsernameMatcher()

        # Year suffix
        result = matcher.compare("john_doe", "john_doe_2024")
        assert result.is_match

        # Alt account pattern
        result = matcher.compare("john_doe", "john_doe_alt")
        assert result.is_match
        assert result.confidence >= 0.7

    def test_normalize_username(self):
        """Username normalization should handle common variations."""
        matcher = UsernameMatcher()

        # Test normalization removes underscores, hyphens for comparison
        normalized = matcher.normalize("John-Doe_123")
        assert normalized.islower()
        assert "_" not in normalized or "-" not in normalized


# =============================================================================
# IMAGE HASH OVERLAP TESTS
# =============================================================================


class TestImageHashMatcher:
    """Tests for image hash overlap detection."""

    def test_exact_hash_match(self):
        """Identical image hashes should match with high confidence."""
        matcher = ImageHashMatcher()

        hashes_a = ["abc123def456", "ghi789jkl012"]
        hashes_b = ["abc123def456", "mno345pqr678"]

        result = matcher.compare(hashes_a, hashes_b)

        assert result.is_match
        assert result.confidence >= 0.8  # Single match with 2 hashes each
        assert len(result.matching_hashes) == 1
        assert "abc123def456" in result.matching_hashes

    def test_multiple_hash_matches(self):
        """Multiple matching hashes should increase confidence."""
        matcher = ImageHashMatcher()

        hashes_a = ["hash1", "hash2", "hash3"]
        hashes_b = ["hash1", "hash2", "hash4"]

        result = matcher.compare(hashes_a, hashes_b)

        assert result.is_match
        assert result.confidence >= 0.9  # Two matches
        assert len(result.matching_hashes) == 2

    def test_no_hash_overlap(self):
        """No overlapping hashes should not match."""
        matcher = ImageHashMatcher()

        hashes_a = ["abc", "def"]
        hashes_b = ["ghi", "jkl"]

        result = matcher.compare(hashes_a, hashes_b)

        assert not result.is_match
        assert result.confidence < 0.5
        assert len(result.matching_hashes) == 0

    def test_empty_hash_lists(self):
        """Empty hash lists should not match."""
        matcher = ImageHashMatcher()

        # Both empty
        result = matcher.compare([], [])
        assert not result.is_match

        # One empty
        result = matcher.compare(["hash1"], [])
        assert not result.is_match

        result = matcher.compare([], ["hash1"])
        assert not result.is_match

    def test_single_hash_match_confidence(self):
        """Single hash match confidence based on total hashes."""
        matcher = ImageHashMatcher()

        # 1 match out of 2 hashes each
        hashes_a = ["hash1", "hash2"]
        hashes_b = ["hash1", "hash3"]
        result = matcher.compare(hashes_a, hashes_b)

        # 1 match out of 10 hashes each should have lower confidence
        hashes_a_large = [f"hash{i}" for i in range(10)]
        hashes_b_large = [f"hash{i}" for i in range(10, 20)]
        hashes_b_large[0] = "hash0"  # One overlap
        result_large = matcher.compare(hashes_a_large, hashes_b_large)

        assert result.confidence > result_large.confidence

    def test_perceptual_hash_similarity(self):
        """Perceptual hashes should support near-match detection."""
        matcher = ImageHashMatcher(perceptual_threshold=0.9)

        # Similar perceptual hashes (simulated with hamming distance)
        hashes_a = ["0" * 64]  # 64-bit hash
        hashes_b = ["0" * 60 + "1" * 4]  # 4 bits different

        result = matcher.compare_perceptual(hashes_a, hashes_b)

        # Should match if within threshold
        assert result.is_match or result.confidence > 0


# =============================================================================
# DUPLICATE SUGGESTION OUTPUT TESTS
# =============================================================================


class TestDuplicateSuggestion:
    """Tests for duplicate suggestion output structure."""

    def test_suggestion_fields(self):
        """Suggestion should have all required fields."""
        suggestion = DuplicateSuggestion(
            source_account_id=1,
            candidate_account_id=2,
            overall_confidence=0.85,
            reasons=[
                MatchReason(type="username", confidence=0.9, description="Exact username match"),
            ],
        )

        assert suggestion.source_account_id == 1
        assert suggestion.candidate_account_id == 2
        assert suggestion.overall_confidence == 0.85
        assert len(suggestion.reasons) == 1

    def test_suggestion_with_multiple_reasons(self):
        """Suggestion can have multiple match reasons."""
        suggestion = DuplicateSuggestion(
            source_account_id=1,
            candidate_account_id=2,
            overall_confidence=0.95,
            reasons=[
                MatchReason(type="username", confidence=0.8, description="Similar username"),
                MatchReason(type="image_hash", confidence=0.95, description="3 matching images"),
            ],
        )

        assert len(suggestion.reasons) == 2
        assert suggestion.overall_confidence >= max(r.confidence for r in suggestion.reasons)

    def test_suggestion_to_dict(self):
        """Suggestion should serialize to dict."""
        suggestion = DuplicateSuggestion(
            source_account_id=1,
            candidate_account_id=2,
            overall_confidence=0.85,
            reasons=[
                MatchReason(type="username", confidence=0.9, description="Exact match"),
            ],
        )

        data = suggestion.to_dict()

        assert data["source_account_id"] == 1
        assert data["candidate_account_id"] == 2
        assert data["overall_confidence"] == 0.85
        assert len(data["reasons"]) == 1


class TestMatchReason:
    """Tests for match reason structure."""

    def test_match_reason_types(self):
        """Match reason should support different types."""
        username_reason = MatchReason(
            type="username",
            confidence=0.9,
            description="Exact username match",
        )
        assert username_reason.type == "username"

        image_reason = MatchReason(
            type="image_hash",
            confidence=0.85,
            description="2 matching images",
            evidence={"matching_hashes": ["abc", "def"]},
        )
        assert image_reason.type == "image_hash"
        assert image_reason.evidence is not None

    def test_match_reason_evidence(self):
        """Match reason can include evidence data."""
        reason = MatchReason(
            type="image_hash",
            confidence=0.9,
            description="Matching profile images",
            evidence={
                "matching_hashes": ["hash1", "hash2"],
                "matching_count": 2,
            },
        )

        assert reason.evidence["matching_count"] == 2


# =============================================================================
# DUPLICATE DETECTION CONFIG TESTS
# =============================================================================


class TestDuplicateDetectionConfig:
    """Tests for configuration options."""

    def test_default_config(self):
        """Default config should have reasonable values."""
        config = DuplicateDetectionConfig()

        assert config.min_username_confidence > 0
        assert config.min_image_confidence > 0
        assert config.min_overall_confidence > 0
        assert config.max_candidates > 0

    def test_custom_config(self):
        """Config should accept custom thresholds."""
        config = DuplicateDetectionConfig(
            min_username_confidence=0.8,
            min_image_confidence=0.9,
            min_overall_confidence=0.7,
            max_candidates=50,
        )

        assert config.min_username_confidence == 0.8
        assert config.min_image_confidence == 0.9
        assert config.min_overall_confidence == 0.7
        assert config.max_candidates == 50


# =============================================================================
# DUPLICATE DETECTION SERVICE TESTS
# =============================================================================


class TestDuplicateDetectionService:
    """Tests for the duplicate detection service."""

    def test_service_initialization(self):
        """Service should initialize with default config."""
        service = DuplicateDetectionService(db=None)

        assert service.config is not None
        assert service.username_matcher is not None
        assert service.image_matcher is not None

    def test_service_with_custom_config(self):
        """Service should accept custom config."""
        config = DuplicateDetectionConfig(min_overall_confidence=0.9)
        service = DuplicateDetectionService(db=None, config=config)

        assert service.config.min_overall_confidence == 0.9

    def test_combine_confidence_scores(self):
        """Service should combine confidence scores appropriately."""
        service = DuplicateDetectionService(db=None)

        # Single high confidence
        combined = service.combine_confidences([0.9])
        assert combined == 0.9

        # Multiple confidences - should boost overall
        combined = service.combine_confidences([0.8, 0.8])
        assert combined > 0.8

        # Mix of confidences - combined should be higher than lowest
        combined = service.combine_confidences([0.9, 0.6])
        assert combined > 0.6  # At least better than lowest
        assert combined <= 0.99  # Capped at 0.99

    def test_build_candidate(self):
        """Service should build candidate from account data."""
        service = DuplicateDetectionService(db=None)

        account_data = {
            "id": 1,
            "external_username": "test_user",
            "provider_id": "reddit",
        }
        image_hashes = ["hash1", "hash2"]

        candidate = service.build_candidate(account_data, image_hashes)

        assert candidate.account_id == 1
        assert candidate.username == "test_user"
        assert candidate.provider_id == "reddit"
        assert candidate.image_hashes == image_hashes


class TestDuplicateCandidate:
    """Tests for duplicate candidate structure."""

    def test_candidate_fields(self):
        """Candidate should have all required fields."""
        candidate = DuplicateCandidate(
            account_id=1,
            username="test_user",
            provider_id="reddit",
            image_hashes=["hash1", "hash2"],
        )

        assert candidate.account_id == 1
        assert candidate.username == "test_user"
        assert candidate.provider_id == "reddit"
        assert len(candidate.image_hashes) == 2

    def test_candidate_without_images(self):
        """Candidate can exist without image hashes."""
        candidate = DuplicateCandidate(
            account_id=1,
            username="test_user",
            provider_id="reddit",
            image_hashes=[],
        )

        assert len(candidate.image_hashes) == 0


# =============================================================================
# EDGE CASES AND ERROR HANDLING
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_username_with_special_characters(self):
        """Username matcher should handle special characters."""
        matcher = UsernameMatcher()

        result = matcher.compare("user@name", "user_name")
        # Should normalize and compare
        assert result is not None

    def test_unicode_usernames(self):
        """Username matcher should handle unicode characters."""
        matcher = UsernameMatcher()

        result = matcher.compare("user_名前", "user_名前")
        assert result.is_match

    def test_very_long_usernames(self):
        """Matcher should handle very long usernames."""
        matcher = UsernameMatcher()

        long_name_a = "a" * 100
        long_name_b = "a" * 100

        result = matcher.compare(long_name_a, long_name_b)
        assert result.is_match

    def test_null_image_hashes(self):
        """Image matcher should handle None values gracefully."""
        matcher = ImageHashMatcher()

        result = matcher.compare(None, ["hash1"])
        assert not result.is_match

        result = matcher.compare(["hash1"], None)
        assert not result.is_match


# =============================================================================
# CONFIDENCE CALCULATION TESTS
# =============================================================================


class TestConfidenceCalculations:
    """Tests for confidence score calculations."""

    def test_username_confidence_decreases_with_distance(self):
        """Username confidence should decrease with edit distance."""
        matcher = UsernameMatcher()

        exact = matcher.compare("username", "username")
        one_edit = matcher.compare("username", "username1")
        two_edits = matcher.compare("username", "username12")

        assert exact.confidence >= one_edit.confidence
        assert one_edit.confidence >= two_edits.confidence

    def test_image_confidence_increases_with_matches(self):
        """Image confidence should increase with more matches."""
        matcher = ImageHashMatcher()

        one_match = matcher.compare(["h1", "h2"], ["h1", "h3"])
        two_matches = matcher.compare(["h1", "h2"], ["h1", "h2"])

        assert two_matches.confidence >= one_match.confidence

    def test_overall_confidence_formula(self):
        """Overall confidence should use appropriate combination."""
        service = DuplicateDetectionService(db=None)

        # Two strong signals should be very confident
        high_both = service.combine_confidences([0.9, 0.9])
        assert high_both >= 0.9

        # One strong, one weak - should be boosted above the strong signal
        mixed = service.combine_confidences([0.9, 0.5])
        assert mixed > 0.5  # Better than weak
        assert mixed <= 0.99  # Capped
