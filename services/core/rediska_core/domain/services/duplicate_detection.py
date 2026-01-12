"""Duplicate detection service for identifying possible duplicate accounts.

Detects potential duplicates based on:
1. Username similarity (exact, case-insensitive, variations, edit distance)
2. Image hash overlap (shared profile images)

Usage:
    service = DuplicateDetectionService(db=session)

    # Find duplicates for a specific account
    suggestions = await service.find_duplicates(account_id=123)

    # Find all potential duplicates in the system
    all_suggestions = await service.scan_all_duplicates()

    for suggestion in suggestions:
        print(f"Possible duplicate: {suggestion.candidate_account_id}")
        print(f"Confidence: {suggestion.overall_confidence}")
        for reason in suggestion.reasons:
            print(f"  - {reason.type}: {reason.description}")
"""

import re
from dataclasses import dataclass, field
from typing import Any, Optional


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class MatchReason:
    """A reason explaining why two accounts might be duplicates.

    Captures the type of match, confidence level, and supporting evidence.
    """

    type: str  # "username", "image_hash", etc.
    confidence: float  # 0.0 to 1.0
    description: str
    evidence: Optional[dict] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        result = {
            "type": self.type,
            "confidence": self.confidence,
            "description": self.description,
        }
        if self.evidence:
            result["evidence"] = self.evidence
        return result


@dataclass
class DuplicateSuggestion:
    """A suggestion that two accounts might be duplicates.

    Contains the source account, candidate account, overall confidence,
    and the reasons for the match.
    """

    source_account_id: int
    candidate_account_id: int
    overall_confidence: float
    reasons: list[MatchReason] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "source_account_id": self.source_account_id,
            "candidate_account_id": self.candidate_account_id,
            "overall_confidence": self.overall_confidence,
            "reasons": [r.to_dict() for r in self.reasons],
        }


@dataclass
class DuplicateCandidate:
    """A candidate account for duplicate comparison.

    Contains the account info and any preloaded data needed for comparison.
    """

    account_id: int
    username: str
    provider_id: str
    image_hashes: list[str] = field(default_factory=list)


@dataclass
class DuplicateDetectionConfig:
    """Configuration for duplicate detection thresholds.

    Controls minimum confidence levels and limits.
    """

    min_username_confidence: float = 0.6
    min_image_confidence: float = 0.7
    min_overall_confidence: float = 0.6
    max_candidates: int = 100
    enable_username_matching: bool = True
    enable_image_matching: bool = True


# =============================================================================
# MATCH RESULT STRUCTURES
# =============================================================================


@dataclass
class UsernameMatchResult:
    """Result of username comparison."""

    is_match: bool
    confidence: float
    reason: str


@dataclass
class ImageMatchResult:
    """Result of image hash comparison."""

    is_match: bool
    confidence: float
    matching_hashes: list[str] = field(default_factory=list)


# =============================================================================
# USERNAME MATCHER
# =============================================================================


class UsernameMatcher:
    """Matches usernames using various similarity heuristics.

    Supports:
    - Exact match
    - Case-insensitive match
    - Common variations (underscores, hyphens, numbers)
    - Levenshtein distance for near-matches
    """

    # Common alt-account suffixes
    ALT_SUFFIXES = ["_alt", "_backup", "_2", "_new", "_old", "_main", "_throwaway"]

    # Patterns for year suffixes
    YEAR_PATTERN = re.compile(r"_?(19|20)\d{2}$")

    # Patterns for number suffixes
    NUMBER_SUFFIX_PATTERN = re.compile(r"\d+$")

    def __init__(self, min_length_for_fuzzy: int = 4):
        """Initialize the username matcher.

        Args:
            min_length_for_fuzzy: Minimum username length for fuzzy matching
        """
        self.min_length_for_fuzzy = min_length_for_fuzzy

    def normalize(self, username: str) -> str:
        """Normalize a username for comparison.

        Converts to lowercase and standardizes separators.

        Args:
            username: The username to normalize

        Returns:
            Normalized username string
        """
        # Lowercase
        normalized = username.lower()

        # Replace common separators with underscore
        normalized = re.sub(r"[-.]", "_", normalized)

        return normalized

    def strip_decorations(self, username: str) -> str:
        """Strip common decorations from username.

        Removes number suffixes, year suffixes, and alt patterns.

        Args:
            username: The username to strip

        Returns:
            Stripped username string
        """
        stripped = username

        # Remove year suffix
        stripped = self.YEAR_PATTERN.sub("", stripped)

        # Remove alt suffixes
        for suffix in self.ALT_SUFFIXES:
            if stripped.endswith(suffix):
                stripped = stripped[: -len(suffix)]
                break

        # Remove trailing numbers (but keep if it's most of the username)
        number_match = self.NUMBER_SUFFIX_PATTERN.search(stripped)
        if number_match:
            num_start = number_match.start()
            # Only strip if numbers are less than half the username
            if num_start > len(stripped) // 2:
                stripped = stripped[:num_start]

        return stripped

    def levenshtein_distance(self, s1: str, s2: str) -> int:
        """Calculate Levenshtein edit distance between two strings.

        Args:
            s1: First string
            s2: Second string

        Returns:
            Edit distance (number of operations to transform s1 to s2)
        """
        if len(s1) < len(s2):
            return self.levenshtein_distance(s2, s1)

        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                # Cost is 0 if characters match, 1 otherwise
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    def compare(self, username_a: str, username_b: str) -> UsernameMatchResult:
        """Compare two usernames for similarity.

        Args:
            username_a: First username
            username_b: Second username

        Returns:
            UsernameMatchResult with match status and confidence
        """
        # Exact match
        if username_a == username_b:
            return UsernameMatchResult(
                is_match=True,
                confidence=1.0,
                reason="exact_match",
            )

        # Normalize for comparison
        norm_a = self.normalize(username_a)
        norm_b = self.normalize(username_b)

        # Case-insensitive exact match
        if norm_a == norm_b:
            return UsernameMatchResult(
                is_match=True,
                confidence=0.95,
                reason="case_insensitive_match",
            )

        # Strip decorations and compare
        stripped_a = self.strip_decorations(norm_a)
        stripped_b = self.strip_decorations(norm_b)

        if stripped_a == stripped_b and len(stripped_a) >= self.min_length_for_fuzzy:
            return UsernameMatchResult(
                is_match=True,
                confidence=0.85,
                reason="variation_match",
            )

        # Remove underscores and compare
        no_sep_a = norm_a.replace("_", "")
        no_sep_b = norm_b.replace("_", "")

        if no_sep_a == no_sep_b and len(no_sep_a) >= self.min_length_for_fuzzy:
            return UsernameMatchResult(
                is_match=True,
                confidence=0.8,
                reason="separator_variation",
            )

        # Check if one is prefix/suffix of the other
        if len(norm_a) >= self.min_length_for_fuzzy and len(norm_b) >= self.min_length_for_fuzzy:
            if norm_a.startswith(norm_b) or norm_b.startswith(norm_a):
                longer = max(len(norm_a), len(norm_b))
                shorter = min(len(norm_a), len(norm_b))
                # Confidence based on how much of the longer name is covered
                conf = shorter / longer * 0.9
                if conf >= 0.6:
                    return UsernameMatchResult(
                        is_match=True,
                        confidence=conf,
                        reason="prefix_suffix_match",
                    )

        # Levenshtein distance for fuzzy matching
        if len(norm_a) >= self.min_length_for_fuzzy and len(norm_b) >= self.min_length_for_fuzzy:
            distance = self.levenshtein_distance(norm_a, norm_b)
            max_len = max(len(norm_a), len(norm_b))

            # Calculate similarity ratio
            similarity = 1 - (distance / max_len)

            if similarity >= 0.8:
                return UsernameMatchResult(
                    is_match=True,
                    confidence=similarity * 0.85,  # Scale down for fuzzy match
                    reason="fuzzy_match",
                )

            if similarity >= 0.7:
                return UsernameMatchResult(
                    is_match=True,
                    confidence=similarity * 0.75,
                    reason="fuzzy_match",
                )

        # No match
        return UsernameMatchResult(
            is_match=False,
            confidence=0.0,
            reason="no_match",
        )


# =============================================================================
# IMAGE HASH MATCHER
# =============================================================================


class ImageHashMatcher:
    """Matches accounts based on shared image hashes.

    Supports:
    - Exact hash matching (SHA256)
    - Perceptual hash similarity (optional)
    """

    def __init__(self, perceptual_threshold: float = 0.9):
        """Initialize the image hash matcher.

        Args:
            perceptual_threshold: Similarity threshold for perceptual hashes
        """
        self.perceptual_threshold = perceptual_threshold

    def compare(
        self, hashes_a: Optional[list[str]], hashes_b: Optional[list[str]]
    ) -> ImageMatchResult:
        """Compare two sets of image hashes for overlap.

        Args:
            hashes_a: Image hashes from first account
            hashes_b: Image hashes from second account

        Returns:
            ImageMatchResult with match status and overlapping hashes
        """
        # Handle None/empty cases
        if not hashes_a or not hashes_b:
            return ImageMatchResult(
                is_match=False,
                confidence=0.0,
                matching_hashes=[],
            )

        # Find overlapping hashes
        set_a = set(hashes_a)
        set_b = set(hashes_b)
        overlap = set_a & set_b

        if not overlap:
            return ImageMatchResult(
                is_match=False,
                confidence=0.0,
                matching_hashes=[],
            )

        # Calculate confidence based on overlap ratio
        # Use Jaccard similarity as base
        union_size = len(set_a | set_b)
        overlap_size = len(overlap)

        jaccard = overlap_size / union_size if union_size > 0 else 0

        # Boost confidence for multiple matches
        # Single match = base confidence, multiple = higher
        if overlap_size >= 3:
            confidence = min(0.98, 0.85 + (overlap_size - 1) * 0.05)
        elif overlap_size == 2:
            confidence = 0.92
        else:
            # Single match - confidence depends on total images
            # More images = less significant single match
            min_total = min(len(hashes_a), len(hashes_b))
            if min_total <= 2:
                confidence = 0.85
            elif min_total <= 5:
                confidence = 0.75
            else:
                confidence = 0.65

        return ImageMatchResult(
            is_match=True,
            confidence=confidence,
            matching_hashes=list(overlap),
        )

    def compare_perceptual(
        self, hashes_a: Optional[list[str]], hashes_b: Optional[list[str]]
    ) -> ImageMatchResult:
        """Compare using perceptual hash similarity.

        Perceptual hashes allow for near-duplicate detection even when
        images have been slightly modified (resized, compressed, etc.).

        Args:
            hashes_a: Perceptual hashes from first account
            hashes_b: Perceptual hashes from second account

        Returns:
            ImageMatchResult with match status
        """
        if not hashes_a or not hashes_b:
            return ImageMatchResult(
                is_match=False,
                confidence=0.0,
                matching_hashes=[],
            )

        # For perceptual hashes, we need to compare each pair
        matching_pairs = []

        for hash_a in hashes_a:
            for hash_b in hashes_b:
                similarity = self._perceptual_similarity(hash_a, hash_b)
                if similarity >= self.perceptual_threshold:
                    matching_pairs.append((hash_a, hash_b, similarity))

        if not matching_pairs:
            return ImageMatchResult(
                is_match=False,
                confidence=0.0,
                matching_hashes=[],
            )

        # Calculate overall confidence from best matches
        best_similarity = max(pair[2] for pair in matching_pairs)
        matching_hashes = list(set(pair[0] for pair in matching_pairs))

        return ImageMatchResult(
            is_match=True,
            confidence=best_similarity,
            matching_hashes=matching_hashes,
        )

    def _perceptual_similarity(self, hash_a: str, hash_b: str) -> float:
        """Calculate similarity between two perceptual hashes.

        Uses Hamming distance for binary hashes.

        Args:
            hash_a: First perceptual hash
            hash_b: Second perceptual hash

        Returns:
            Similarity score (0.0 to 1.0)
        """
        if len(hash_a) != len(hash_b):
            return 0.0

        if not hash_a or not hash_b:
            return 0.0

        # Count differing characters (Hamming distance)
        differences = sum(c1 != c2 for c1, c2 in zip(hash_a, hash_b))

        # Convert to similarity
        similarity = 1 - (differences / len(hash_a))

        return similarity


# =============================================================================
# DUPLICATE DETECTION SERVICE
# =============================================================================


class DuplicateDetectionService:
    """Service for detecting possible duplicate accounts.

    Coordinates username and image hash matching to identify
    potential duplicates for manual review.
    """

    def __init__(
        self,
        db,
        config: Optional[DuplicateDetectionConfig] = None,
    ):
        """Initialize the duplicate detection service.

        Args:
            db: Database session
            config: Configuration options
        """
        self.db = db
        self.config = config or DuplicateDetectionConfig()
        self.username_matcher = UsernameMatcher()
        self.image_matcher = ImageHashMatcher()

    def build_candidate(
        self, account_data: dict, image_hashes: Optional[list[str]] = None
    ) -> DuplicateCandidate:
        """Build a candidate from account data.

        Args:
            account_data: Dictionary with account info
            image_hashes: Optional list of image hashes

        Returns:
            DuplicateCandidate instance
        """
        return DuplicateCandidate(
            account_id=account_data["id"],
            username=account_data["external_username"],
            provider_id=account_data["provider_id"],
            image_hashes=image_hashes or [],
        )

    def combine_confidences(self, confidences: list[float]) -> float:
        """Combine multiple confidence scores into overall confidence.

        Uses a formula that boosts confidence when multiple signals agree.

        Args:
            confidences: List of individual confidence scores

        Returns:
            Combined confidence score
        """
        if not confidences:
            return 0.0

        if len(confidences) == 1:
            return confidences[0]

        # Sort descending
        sorted_conf = sorted(confidences, reverse=True)

        # Start with highest confidence
        combined = sorted_conf[0]

        # Add diminishing contributions from additional signals
        for i, conf in enumerate(sorted_conf[1:], start=1):
            # Each additional signal adds a portion of its confidence
            # weighted by how many signals we already have
            contribution = conf * (1 - combined) * (1 / (i + 1))
            combined += contribution

        return min(combined, 0.99)  # Cap at 0.99

    def compare_candidates(
        self, source: DuplicateCandidate, candidate: DuplicateCandidate
    ) -> Optional[DuplicateSuggestion]:
        """Compare two candidates for potential duplication.

        Args:
            source: The source account candidate
            candidate: The candidate to compare against

        Returns:
            DuplicateSuggestion if match found, None otherwise
        """
        if source.account_id == candidate.account_id:
            return None

        reasons = []
        confidences = []

        # Username comparison
        if self.config.enable_username_matching:
            username_result = self.username_matcher.compare(
                source.username, candidate.username
            )

            if (
                username_result.is_match
                and username_result.confidence >= self.config.min_username_confidence
            ):
                reasons.append(
                    MatchReason(
                        type="username",
                        confidence=username_result.confidence,
                        description=f"Username similarity: {username_result.reason}",
                        evidence={
                            "source_username": source.username,
                            "candidate_username": candidate.username,
                        },
                    )
                )
                confidences.append(username_result.confidence)

        # Image hash comparison
        if self.config.enable_image_matching:
            image_result = self.image_matcher.compare(
                source.image_hashes, candidate.image_hashes
            )

            if (
                image_result.is_match
                and image_result.confidence >= self.config.min_image_confidence
            ):
                reasons.append(
                    MatchReason(
                        type="image_hash",
                        confidence=image_result.confidence,
                        description=f"{len(image_result.matching_hashes)} matching image(s)",
                        evidence={
                            "matching_hashes": image_result.matching_hashes,
                            "matching_count": len(image_result.matching_hashes),
                        },
                    )
                )
                confidences.append(image_result.confidence)

        # No matches found
        if not reasons:
            return None

        # Calculate overall confidence
        overall_confidence = self.combine_confidences(confidences)

        if overall_confidence < self.config.min_overall_confidence:
            return None

        return DuplicateSuggestion(
            source_account_id=source.account_id,
            candidate_account_id=candidate.account_id,
            overall_confidence=overall_confidence,
            reasons=reasons,
        )

    async def find_duplicates(
        self, account_id: int, same_provider_only: bool = True
    ) -> list[DuplicateSuggestion]:
        """Find potential duplicates for a specific account.

        Args:
            account_id: ID of the account to check
            same_provider_only: Only check accounts from same provider

        Returns:
            List of DuplicateSuggestion objects
        """
        from rediska_core.domain.models import Attachment, ExternalAccount, ProfileItem

        # Load source account
        account = self.db.get(ExternalAccount, account_id)
        if not account:
            return []

        # Load image hashes for source account
        source_hashes = await self._get_account_image_hashes(account_id)

        source_candidate = DuplicateCandidate(
            account_id=account.id,
            username=account.external_username,
            provider_id=account.provider_id,
            image_hashes=source_hashes,
        )

        # Query potential candidates
        query = self.db.query(ExternalAccount).filter(
            ExternalAccount.id != account_id,
            ExternalAccount.deleted_at.is_(None),
        )

        if same_provider_only:
            query = query.filter(ExternalAccount.provider_id == account.provider_id)

        # Limit to max candidates
        candidates_data = query.limit(self.config.max_candidates).all()

        suggestions = []

        for candidate_account in candidates_data:
            # Load image hashes for candidate
            candidate_hashes = await self._get_account_image_hashes(candidate_account.id)

            candidate = DuplicateCandidate(
                account_id=candidate_account.id,
                username=candidate_account.external_username,
                provider_id=candidate_account.provider_id,
                image_hashes=candidate_hashes,
            )

            suggestion = self.compare_candidates(source_candidate, candidate)
            if suggestion:
                suggestions.append(suggestion)

        # Sort by confidence descending
        suggestions.sort(key=lambda s: s.overall_confidence, reverse=True)

        return suggestions

    async def _get_account_image_hashes(self, account_id: int) -> list[str]:
        """Get all image hashes for an account.

        Args:
            account_id: ID of the account

        Returns:
            List of SHA256 hashes
        """
        from rediska_core.domain.models import Attachment, ProfileItem

        # Query profile items with attachments
        items_with_attachments = (
            self.db.query(ProfileItem)
            .filter(
                ProfileItem.account_id == account_id,
                ProfileItem.attachment_id.isnot(None),
                ProfileItem.deleted_at.is_(None),
            )
            .all()
        )

        attachment_ids = [item.attachment_id for item in items_with_attachments]

        if not attachment_ids:
            return []

        # Get attachment hashes
        attachments = (
            self.db.query(Attachment)
            .filter(
                Attachment.id.in_(attachment_ids),
                Attachment.deleted_at.is_(None),
            )
            .all()
        )

        return [att.sha256 for att in attachments]

    async def scan_all_duplicates(
        self, provider_id: Optional[str] = None
    ) -> list[DuplicateSuggestion]:
        """Scan for all potential duplicates in the system.

        This is a more expensive operation that compares all accounts.

        Args:
            provider_id: Optional provider to limit scan to

        Returns:
            List of DuplicateSuggestion objects
        """
        from rediska_core.domain.models import ExternalAccount

        # Query all accounts
        query = self.db.query(ExternalAccount).filter(
            ExternalAccount.deleted_at.is_(None),
        )

        if provider_id:
            query = query.filter(ExternalAccount.provider_id == provider_id)

        accounts = query.all()

        # Build candidates
        candidates = []
        for account in accounts:
            hashes = await self._get_account_image_hashes(account.id)
            candidates.append(
                DuplicateCandidate(
                    account_id=account.id,
                    username=account.external_username,
                    provider_id=account.provider_id,
                    image_hashes=hashes,
                )
            )

        # Compare all pairs
        suggestions = []
        seen_pairs = set()

        for i, source in enumerate(candidates):
            for candidate in candidates[i + 1 :]:
                # Skip if different providers
                if source.provider_id != candidate.provider_id:
                    continue

                # Skip if already seen
                pair_key = tuple(sorted([source.account_id, candidate.account_id]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                suggestion = self.compare_candidates(source, candidate)
                if suggestion:
                    suggestions.append(suggestion)

        # Sort by confidence descending
        suggestions.sort(key=lambda s: s.overall_confidence, reverse=True)

        return suggestions


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "DuplicateCandidate",
    "DuplicateDetectionConfig",
    "DuplicateDetectionService",
    "DuplicateSuggestion",
    "ImageHashMatcher",
    "ImageMatchResult",
    "MatchReason",
    "UsernameMatcher",
    "UsernameMatchResult",
]
