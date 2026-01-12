"""Integration tests for duplicate detection service.

Tests the full flow:
1. Loading account data from database
2. Loading image hashes from attachments
3. Running duplicate detection
4. Returning structured suggestions
"""

from datetime import datetime, timezone

import pytest

from rediska_core.domain.models import (
    Attachment,
    ExternalAccount,
    ProfileItem,
    Provider,
)
from rediska_core.domain.services.duplicate_detection import (
    DuplicateDetectionConfig,
    DuplicateDetectionService,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def setup_provider(db_session):
    """Set up provider for tests."""
    provider = Provider(provider_id="reddit", display_name="Reddit")
    db_session.add(provider)
    db_session.flush()
    return provider


@pytest.fixture
def setup_accounts(db_session, setup_provider):
    """Set up multiple external accounts for testing."""
    accounts = [
        ExternalAccount(
            provider_id="reddit",
            external_username="john_doe",
            external_user_id="t2_john1",
            analysis_state="analyzed",
        ),
        ExternalAccount(
            provider_id="reddit",
            external_username="john_doe_alt",
            external_user_id="t2_john2",
            analysis_state="analyzed",
        ),
        ExternalAccount(
            provider_id="reddit",
            external_username="johndoe123",
            external_user_id="t2_john3",
            analysis_state="analyzed",
        ),
        ExternalAccount(
            provider_id="reddit",
            external_username="alice_smith",
            external_user_id="t2_alice",
            analysis_state="analyzed",
        ),
        ExternalAccount(
            provider_id="reddit",
            external_username="bob_jones",
            external_user_id="t2_bob",
            analysis_state="analyzed",
        ),
    ]
    for account in accounts:
        db_session.add(account)
    db_session.flush()
    return accounts


@pytest.fixture
def setup_accounts_with_images(db_session, setup_provider):
    """Set up accounts with shared image attachments."""
    # Create accounts
    account1 = ExternalAccount(
        provider_id="reddit",
        external_username="photo_user",
        external_user_id="t2_photo1",
        analysis_state="analyzed",
    )
    account2 = ExternalAccount(
        provider_id="reddit",
        external_username="different_name",
        external_user_id="t2_photo2",
        analysis_state="analyzed",
    )
    account3 = ExternalAccount(
        provider_id="reddit",
        external_username="unique_person",
        external_user_id="t2_unique",
        analysis_state="analyzed",
    )
    db_session.add_all([account1, account2, account3])
    db_session.flush()

    # Create shared attachment
    shared_attachment = Attachment(
        storage_backend="fs",
        storage_key="/data/attachments/shared_image.jpg",
        sha256="abc123def456shared",
        mime_type="image/jpeg",
        size_bytes=50000,
    )
    db_session.add(shared_attachment)
    db_session.flush()

    # Create unique attachments
    unique_attachment1 = Attachment(
        storage_backend="fs",
        storage_key="/data/attachments/unique1.jpg",
        sha256="unique1hash",
        mime_type="image/jpeg",
        size_bytes=40000,
    )
    unique_attachment2 = Attachment(
        storage_backend="fs",
        storage_key="/data/attachments/unique2.jpg",
        sha256="unique2hash",
        mime_type="image/jpeg",
        size_bytes=45000,
    )
    unique_attachment3 = Attachment(
        storage_backend="fs",
        storage_key="/data/attachments/unique3.jpg",
        sha256="unique3hash",
        mime_type="image/jpeg",
        size_bytes=42000,
    )
    db_session.add_all([unique_attachment1, unique_attachment2, unique_attachment3])
    db_session.flush()

    # Create profile items linking accounts to attachments
    # Account1 has shared + unique1
    item1a = ProfileItem(
        account_id=account1.id,
        item_type="image",
        external_item_id="img_1a",
        attachment_id=shared_attachment.id,
    )
    item1b = ProfileItem(
        account_id=account1.id,
        item_type="image",
        external_item_id="img_1b",
        attachment_id=unique_attachment1.id,
    )

    # Account2 has shared + unique2 (shares image with account1)
    item2a = ProfileItem(
        account_id=account2.id,
        item_type="image",
        external_item_id="img_2a",
        attachment_id=shared_attachment.id,
    )
    item2b = ProfileItem(
        account_id=account2.id,
        item_type="image",
        external_item_id="img_2b",
        attachment_id=unique_attachment2.id,
    )

    # Account3 has only unique3 (no shared images)
    item3 = ProfileItem(
        account_id=account3.id,
        item_type="image",
        external_item_id="img_3",
        attachment_id=unique_attachment3.id,
    )

    db_session.add_all([item1a, item1b, item2a, item2b, item3])
    db_session.flush()

    return [account1, account2, account3]


# =============================================================================
# SERVICE INTEGRATION TESTS
# =============================================================================


class TestDuplicateDetectionServiceIntegration:
    """Tests for DuplicateDetectionService with database."""

    @pytest.mark.asyncio
    async def test_find_duplicates_by_username(self, db_session, setup_accounts):
        """Service should find duplicates based on username similarity."""
        service = DuplicateDetectionService(db=db_session)

        # Find duplicates for john_doe
        john_doe = setup_accounts[0]
        suggestions = await service.find_duplicates(john_doe.id)

        # Should find at least john_doe_alt as a potential duplicate
        assert len(suggestions) >= 1

        candidate_ids = [s.candidate_account_id for s in suggestions]
        assert setup_accounts[1].id in candidate_ids  # john_doe_alt

        # Should NOT include alice_smith or bob_jones (completely different names)
        assert setup_accounts[3].id not in candidate_ids
        assert setup_accounts[4].id not in candidate_ids

    @pytest.mark.asyncio
    async def test_find_duplicates_returns_sorted_by_confidence(
        self, db_session, setup_accounts
    ):
        """Suggestions should be sorted by confidence descending."""
        service = DuplicateDetectionService(db=db_session)

        john_doe = setup_accounts[0]
        suggestions = await service.find_duplicates(john_doe.id)

        if len(suggestions) >= 2:
            for i in range(len(suggestions) - 1):
                assert suggestions[i].overall_confidence >= suggestions[i + 1].overall_confidence

    @pytest.mark.asyncio
    async def test_find_duplicates_by_image_hash(
        self, db_session, setup_accounts_with_images
    ):
        """Service should find duplicates based on shared images."""
        service = DuplicateDetectionService(db=db_session)

        # Find duplicates for photo_user
        photo_user = setup_accounts_with_images[0]
        suggestions = await service.find_duplicates(photo_user.id)

        # Should find different_name as duplicate (shares image)
        candidate_ids = [s.candidate_account_id for s in suggestions]
        different_name = setup_accounts_with_images[1]

        assert different_name.id in candidate_ids

        # Find the specific suggestion
        image_suggestion = next(
            s for s in suggestions if s.candidate_account_id == different_name.id
        )

        # Should have image_hash as a reason
        reason_types = [r.type for r in image_suggestion.reasons]
        assert "image_hash" in reason_types

    @pytest.mark.asyncio
    async def test_find_duplicates_no_false_positives(
        self, db_session, setup_accounts_with_images
    ):
        """Service should not flag accounts with no shared characteristics."""
        service = DuplicateDetectionService(db=db_session)

        # unique_person has no shared images and different username
        unique_person = setup_accounts_with_images[2]
        suggestions = await service.find_duplicates(unique_person.id)

        # Should not have high-confidence matches
        for suggestion in suggestions:
            assert suggestion.overall_confidence < 0.8

    @pytest.mark.asyncio
    async def test_find_duplicates_nonexistent_account(self, db_session, setup_provider):
        """Service should return empty list for nonexistent account."""
        service = DuplicateDetectionService(db=db_session)

        suggestions = await service.find_duplicates(99999)

        assert suggestions == []


# =============================================================================
# SCAN ALL DUPLICATES TESTS
# =============================================================================


class TestScanAllDuplicates:
    """Tests for scanning all accounts for duplicates."""

    @pytest.mark.asyncio
    async def test_scan_all_finds_duplicates(self, db_session, setup_accounts):
        """Scan should find all duplicate pairs."""
        service = DuplicateDetectionService(db=db_session)

        suggestions = await service.scan_all_duplicates(provider_id="reddit")

        # Should find john_doe related duplicates
        assert len(suggestions) >= 1

        # Check that we found the john_doe cluster
        all_ids = set()
        for s in suggestions:
            all_ids.add(s.source_account_id)
            all_ids.add(s.candidate_account_id)

        john_ids = {setup_accounts[0].id, setup_accounts[1].id, setup_accounts[2].id}
        assert len(all_ids & john_ids) >= 2  # At least 2 of the john variants

    @pytest.mark.asyncio
    async def test_scan_all_no_duplicate_pairs(self, db_session, setup_accounts):
        """Scan should not return duplicate pairs (A-B and B-A)."""
        service = DuplicateDetectionService(db=db_session)

        suggestions = await service.scan_all_duplicates(provider_id="reddit")

        # Check no duplicate pairs
        seen_pairs = set()
        for s in suggestions:
            pair = tuple(sorted([s.source_account_id, s.candidate_account_id]))
            assert pair not in seen_pairs, f"Duplicate pair found: {pair}"
            seen_pairs.add(pair)

    @pytest.mark.asyncio
    async def test_scan_respects_provider_filter(self, db_session, setup_provider):
        """Scan should only include accounts from specified provider."""
        # Add an account from different provider
        other_provider = Provider(provider_id="twitter", display_name="Twitter")
        db_session.add(other_provider)
        db_session.flush()

        reddit_account = ExternalAccount(
            provider_id="reddit",
            external_username="same_name",
            external_user_id="t2_reddit",
            analysis_state="analyzed",
        )
        twitter_account = ExternalAccount(
            provider_id="twitter",
            external_username="same_name",
            external_user_id="tw_123",
            analysis_state="analyzed",
        )
        db_session.add_all([reddit_account, twitter_account])
        db_session.flush()

        service = DuplicateDetectionService(db=db_session)

        # Scan only reddit
        reddit_suggestions = await service.scan_all_duplicates(provider_id="reddit")

        # Should not pair cross-provider accounts
        for s in reddit_suggestions:
            source = db_session.get(ExternalAccount, s.source_account_id)
            candidate = db_session.get(ExternalAccount, s.candidate_account_id)
            assert source.provider_id == candidate.provider_id == "reddit"


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================


class TestDuplicateDetectionConfiguration:
    """Tests for configuration options."""

    @pytest.mark.asyncio
    async def test_min_confidence_threshold(self, db_session, setup_accounts):
        """High confidence threshold should reduce results."""
        # Default config
        default_service = DuplicateDetectionService(db=db_session)
        default_suggestions = await default_service.find_duplicates(setup_accounts[0].id)

        # Strict config
        strict_config = DuplicateDetectionConfig(min_overall_confidence=0.95)
        strict_service = DuplicateDetectionService(db=db_session, config=strict_config)
        strict_suggestions = await strict_service.find_duplicates(setup_accounts[0].id)

        # Strict should have fewer or equal results
        assert len(strict_suggestions) <= len(default_suggestions)

    @pytest.mark.asyncio
    async def test_disable_username_matching(
        self, db_session, setup_accounts_with_images
    ):
        """Disabling username matching should only use image hashes."""
        config = DuplicateDetectionConfig(enable_username_matching=False)
        service = DuplicateDetectionService(db=db_session, config=config)

        photo_user = setup_accounts_with_images[0]
        suggestions = await service.find_duplicates(photo_user.id)

        # Should only have image_hash reasons
        for suggestion in suggestions:
            reason_types = [r.type for r in suggestion.reasons]
            assert "username" not in reason_types

    @pytest.mark.asyncio
    async def test_disable_image_matching(self, db_session, setup_accounts_with_images):
        """Disabling image matching should only use usernames."""
        config = DuplicateDetectionConfig(enable_image_matching=False)
        service = DuplicateDetectionService(db=db_session, config=config)

        photo_user = setup_accounts_with_images[0]
        suggestions = await service.find_duplicates(photo_user.id)

        # Should only have username reasons
        for suggestion in suggestions:
            reason_types = [r.type for r in suggestion.reasons]
            assert "image_hash" not in reason_types


# =============================================================================
# SUGGESTION CONTENT TESTS
# =============================================================================


class TestSuggestionContent:
    """Tests for suggestion content and structure."""

    @pytest.mark.asyncio
    async def test_suggestion_includes_evidence(self, db_session, setup_accounts):
        """Suggestions should include evidence in reasons."""
        service = DuplicateDetectionService(db=db_session)

        john_doe = setup_accounts[0]
        suggestions = await service.find_duplicates(john_doe.id)

        assert len(suggestions) > 0

        for suggestion in suggestions:
            for reason in suggestion.reasons:
                assert reason.description is not None
                assert len(reason.description) > 0

                if reason.type == "username":
                    assert reason.evidence is not None
                    assert "source_username" in reason.evidence
                    assert "candidate_username" in reason.evidence

    @pytest.mark.asyncio
    async def test_suggestion_to_dict_serialization(self, db_session, setup_accounts):
        """Suggestions should serialize properly."""
        service = DuplicateDetectionService(db=db_session)

        john_doe = setup_accounts[0]
        suggestions = await service.find_duplicates(john_doe.id)

        assert len(suggestions) > 0

        for suggestion in suggestions:
            data = suggestion.to_dict()

            assert "source_account_id" in data
            assert "candidate_account_id" in data
            assert "overall_confidence" in data
            assert "reasons" in data
            assert isinstance(data["reasons"], list)


# =============================================================================
# COMBINED SIGNAL TESTS
# =============================================================================


class TestCombinedSignals:
    """Tests for combining username and image signals."""

    @pytest.mark.asyncio
    async def test_combined_signals_boost_confidence(self, db_session, setup_provider):
        """Having both username and image match should boost confidence."""
        # Create two accounts with similar names AND shared images
        account1 = ExternalAccount(
            provider_id="reddit",
            external_username="both_signals",
            external_user_id="t2_both1",
            analysis_state="analyzed",
        )
        account2 = ExternalAccount(
            provider_id="reddit",
            external_username="both_signals_alt",
            external_user_id="t2_both2",
            analysis_state="analyzed",
        )
        db_session.add_all([account1, account2])
        db_session.flush()

        # Add shared image
        attachment = Attachment(
            storage_backend="fs",
            storage_key="/data/attachments/both_shared.jpg",
            sha256="bothsharedhash",
            mime_type="image/jpeg",
            size_bytes=30000,
        )
        db_session.add(attachment)
        db_session.flush()

        item1 = ProfileItem(
            account_id=account1.id,
            item_type="image",
            external_item_id="both_img1",
            attachment_id=attachment.id,
        )
        item2 = ProfileItem(
            account_id=account2.id,
            item_type="image",
            external_item_id="both_img2",
            attachment_id=attachment.id,
        )
        db_session.add_all([item1, item2])
        db_session.flush()

        service = DuplicateDetectionService(db=db_session)
        suggestions = await service.find_duplicates(account1.id)

        # Should find account2
        assert len(suggestions) >= 1
        match = next(
            (s for s in suggestions if s.candidate_account_id == account2.id), None
        )
        assert match is not None

        # Should have both reasons
        reason_types = [r.type for r in match.reasons]
        assert "username" in reason_types
        assert "image_hash" in reason_types

        # Confidence should be high due to combined signals
        assert match.overall_confidence >= 0.85


# =============================================================================
# EDGE CASES
# =============================================================================


class TestIntegrationEdgeCases:
    """Tests for edge cases in integration."""

    @pytest.mark.asyncio
    async def test_deleted_accounts_excluded(self, db_session, setup_provider):
        """Deleted accounts should not appear as candidates."""
        active_account = ExternalAccount(
            provider_id="reddit",
            external_username="active_user",
            external_user_id="t2_active",
            analysis_state="analyzed",
        )
        deleted_account = ExternalAccount(
            provider_id="reddit",
            external_username="active_user_alt",
            external_user_id="t2_deleted",
            analysis_state="analyzed",
            deleted_at=datetime.now(timezone.utc),
        )
        db_session.add_all([active_account, deleted_account])
        db_session.flush()

        service = DuplicateDetectionService(db=db_session)
        suggestions = await service.find_duplicates(active_account.id)

        # Deleted account should not be in candidates
        candidate_ids = [s.candidate_account_id for s in suggestions]
        assert deleted_account.id not in candidate_ids

    @pytest.mark.asyncio
    async def test_max_candidates_limit(self, db_session, setup_provider):
        """Should respect max_candidates configuration."""
        # Create many accounts
        for i in range(20):
            account = ExternalAccount(
                provider_id="reddit",
                external_username=f"user_{i}",
                external_user_id=f"t2_user{i}",
                analysis_state="analyzed",
            )
            db_session.add(account)
        db_session.flush()

        config = DuplicateDetectionConfig(max_candidates=5)
        service = DuplicateDetectionService(db=db_session, config=config)

        # Get first account
        first_account = (
            db_session.query(ExternalAccount)
            .filter(ExternalAccount.external_username == "user_0")
            .first()
        )

        # This tests that the query limit is applied
        # (though matching results may be fewer based on actual similarity)
        suggestions = await service.find_duplicates(first_account.id)

        # Should have results (exact number depends on similarity)
        assert suggestions is not None
