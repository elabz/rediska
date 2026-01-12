"""Unit tests for identity management functionality.

These tests follow TDD - written BEFORE implementation.
Tests cover:
- Identity CRUD operations
- Default identity business rules
- Voice configuration validation
"""

import pytest
from sqlalchemy.orm import Session as DBSession

from tests.factories import create_identity, create_provider


class TestIdentityCreate:
    """Tests for identity creation."""

    def test_create_identity_basic(self, db_session: DBSession):
        """Test creating a basic identity."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        service = IdentityService(db_session)

        identity = service.create_identity(
            provider_id=provider.provider_id,
            external_username="my_reddit_account",
            display_name="My Reddit Account",
        )
        db_session.flush()

        assert identity is not None
        assert identity.id is not None
        assert identity.provider_id == provider.provider_id
        assert identity.external_username == "my_reddit_account"
        assert identity.display_name == "My Reddit Account"
        assert identity.is_active is True

    def test_create_identity_with_external_user_id(self, db_session: DBSession):
        """Test creating identity with external user ID."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        service = IdentityService(db_session)

        identity = service.create_identity(
            provider_id=provider.provider_id,
            external_username="my_account",
            display_name="My Account",
            external_user_id="t2_abc123",
        )
        db_session.flush()

        assert identity.external_user_id == "t2_abc123"

    def test_create_identity_with_voice_config(self, db_session: DBSession):
        """Test creating identity with voice configuration."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        service = IdentityService(db_session)

        voice_config = {
            "system_prompt": "You are a friendly helper.",
            "tone": "casual",
            "guidelines": ["Be helpful", "Be concise"],
        }

        identity = service.create_identity(
            provider_id=provider.provider_id,
            external_username="my_account",
            display_name="My Account",
            voice_config=voice_config,
        )
        db_session.flush()

        assert identity.voice_config_json == voice_config

    def test_create_identity_requires_provider(self, db_session: DBSession):
        """Test that creating identity requires valid provider."""
        from rediska_core.domain.services.identity import IdentityService

        service = IdentityService(db_session)

        with pytest.raises(ValueError, match="provider"):
            service.create_identity(
                provider_id="nonexistent",
                external_username="my_account",
                display_name="My Account",
            )

    def test_create_identity_requires_username(self, db_session: DBSession):
        """Test that creating identity requires username."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        service = IdentityService(db_session)

        with pytest.raises(ValueError, match="username"):
            service.create_identity(
                provider_id=provider.provider_id,
                external_username="",
                display_name="My Account",
            )

    def test_create_identity_requires_display_name(self, db_session: DBSession):
        """Test that creating identity requires display name."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        service = IdentityService(db_session)

        with pytest.raises(ValueError, match="display_name"):
            service.create_identity(
                provider_id=provider.provider_id,
                external_username="my_account",
                display_name="",
            )

    def test_create_identity_unique_username_per_provider(self, db_session: DBSession):
        """Test that username must be unique per provider."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        service = IdentityService(db_session)

        service.create_identity(
            provider_id=provider.provider_id,
            external_username="same_username",
            display_name="First Account",
        )
        db_session.flush()

        with pytest.raises(ValueError, match="already exists"):
            service.create_identity(
                provider_id=provider.provider_id,
                external_username="same_username",
                display_name="Second Account",
            )


class TestIdentityRead:
    """Tests for reading identities."""

    def test_get_identity_by_id(self, db_session: DBSession):
        """Test getting identity by ID."""
        from rediska_core.domain.services.identity import IdentityService

        identity = create_identity(db_session, display_name="Test Identity")
        service = IdentityService(db_session)

        result = service.get_identity(identity.id)

        assert result is not None
        assert result.id == identity.id
        assert result.display_name == "Test Identity"

    def test_get_identity_not_found(self, db_session: DBSession):
        """Test getting nonexistent identity returns None."""
        from rediska_core.domain.services.identity import IdentityService

        service = IdentityService(db_session)

        result = service.get_identity(99999)

        assert result is None

    def test_get_identity_excludes_inactive(self, db_session: DBSession):
        """Test that inactive identities are excluded by default."""
        from rediska_core.domain.services.identity import IdentityService

        identity = create_identity(db_session, is_active=False)
        service = IdentityService(db_session)

        result = service.get_identity(identity.id)

        assert result is None

    def test_get_identity_includes_inactive_when_requested(self, db_session: DBSession):
        """Test that inactive identities can be included."""
        from rediska_core.domain.services.identity import IdentityService

        identity = create_identity(db_session, is_active=False)
        service = IdentityService(db_session)

        result = service.get_identity(identity.id, include_inactive=True)

        assert result is not None
        assert result.id == identity.id

    def test_list_identities_empty(self, db_session: DBSession):
        """Test listing identities when none exist."""
        from rediska_core.domain.services.identity import IdentityService

        service = IdentityService(db_session)

        result = service.list_identities()

        assert result == []

    def test_list_identities_all(self, db_session: DBSession):
        """Test listing all identities."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        create_identity(db_session, provider=provider, external_username="user1")
        create_identity(db_session, provider=provider, external_username="user2")
        service = IdentityService(db_session)

        result = service.list_identities()

        assert len(result) == 2

    def test_list_identities_by_provider(self, db_session: DBSession):
        """Test listing identities filtered by provider."""
        from rediska_core.domain.services.identity import IdentityService

        provider1 = create_provider(db_session, provider_id="reddit")
        provider2 = create_provider(db_session, provider_id="twitter")
        create_identity(db_session, provider=provider1, external_username="reddit_user")
        create_identity(db_session, provider=provider2, external_username="twitter_user")
        service = IdentityService(db_session)

        result = service.list_identities(provider_id="reddit")

        assert len(result) == 1
        assert result[0].provider_id == "reddit"

    def test_list_identities_excludes_inactive(self, db_session: DBSession):
        """Test that inactive identities are excluded by default."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        create_identity(db_session, provider=provider, external_username="active", is_active=True)
        create_identity(db_session, provider=provider, external_username="inactive", is_active=False)
        service = IdentityService(db_session)

        result = service.list_identities()

        assert len(result) == 1
        assert result[0].external_username == "active"

    def test_list_identities_grouped_by_provider(self, db_session: DBSession):
        """Test listing identities grouped by provider."""
        from rediska_core.domain.services.identity import IdentityService

        provider1 = create_provider(db_session, provider_id="reddit")
        provider2 = create_provider(db_session, provider_id="twitter")
        create_identity(db_session, provider=provider1, external_username="reddit1")
        create_identity(db_session, provider=provider1, external_username="reddit2")
        create_identity(db_session, provider=provider2, external_username="twitter1")
        service = IdentityService(db_session)

        result = service.list_identities_grouped()

        assert "reddit" in result
        assert "twitter" in result
        assert len(result["reddit"]) == 2
        assert len(result["twitter"]) == 1


class TestIdentityUpdate:
    """Tests for updating identities."""

    def test_update_identity_display_name(self, db_session: DBSession):
        """Test updating identity display name."""
        from rediska_core.domain.services.identity import IdentityService

        identity = create_identity(db_session, display_name="Original")
        service = IdentityService(db_session)

        updated = service.update_identity(identity.id, display_name="Updated")
        db_session.flush()

        assert updated is not None
        assert updated.display_name == "Updated"

    def test_update_identity_voice_config(self, db_session: DBSession):
        """Test updating identity voice configuration."""
        from rediska_core.domain.services.identity import IdentityService

        identity = create_identity(db_session)
        service = IdentityService(db_session)

        new_voice_config = {"tone": "professional", "style": "formal"}
        updated = service.update_identity(identity.id, voice_config=new_voice_config)
        db_session.flush()

        assert updated.voice_config_json == new_voice_config

    def test_update_identity_is_active(self, db_session: DBSession):
        """Test updating identity active status."""
        from rediska_core.domain.services.identity import IdentityService

        identity = create_identity(db_session, is_active=True)
        service = IdentityService(db_session)

        updated = service.update_identity(identity.id, is_active=False)
        db_session.flush()

        assert updated.is_active is False

    def test_update_identity_not_found(self, db_session: DBSession):
        """Test updating nonexistent identity raises error."""
        from rediska_core.domain.services.identity import IdentityService

        service = IdentityService(db_session)

        with pytest.raises(ValueError, match="not found"):
            service.update_identity(99999, display_name="New Name")

    def test_update_identity_empty_display_name(self, db_session: DBSession):
        """Test that empty display name is rejected."""
        from rediska_core.domain.services.identity import IdentityService

        identity = create_identity(db_session)
        service = IdentityService(db_session)

        with pytest.raises(ValueError, match="display_name"):
            service.update_identity(identity.id, display_name="")


class TestIdentityDelete:
    """Tests for deleting (deactivating) identities."""

    def test_delete_identity_soft_delete(self, db_session: DBSession):
        """Test that delete performs soft delete (deactivate)."""
        from rediska_core.domain.services.identity import IdentityService

        identity = create_identity(db_session, is_active=True)
        service = IdentityService(db_session)

        service.delete_identity(identity.id)
        db_session.flush()
        db_session.refresh(identity)

        assert identity.is_active is False

    def test_delete_identity_not_found(self, db_session: DBSession):
        """Test deleting nonexistent identity raises error."""
        from rediska_core.domain.services.identity import IdentityService

        service = IdentityService(db_session)

        with pytest.raises(ValueError, match="not found"):
            service.delete_identity(99999)

    def test_delete_identity_already_inactive(self, db_session: DBSession):
        """Test deleting already inactive identity is no-op."""
        from rediska_core.domain.services.identity import IdentityService

        identity = create_identity(db_session, is_active=False)
        service = IdentityService(db_session)

        # Should not raise
        service.delete_identity(identity.id)


class TestDefaultIdentity:
    """Tests for default identity business rules."""

    def test_first_identity_becomes_default(self, db_session: DBSession):
        """Test that first identity for a provider becomes default."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        service = IdentityService(db_session)

        identity = service.create_identity(
            provider_id=provider.provider_id,
            external_username="first_user",
            display_name="First User",
        )
        db_session.flush()

        assert identity.is_default is True

    def test_second_identity_not_default(self, db_session: DBSession):
        """Test that second identity for a provider is not default."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        service = IdentityService(db_session)

        service.create_identity(
            provider_id=provider.provider_id,
            external_username="first_user",
            display_name="First User",
        )
        second = service.create_identity(
            provider_id=provider.provider_id,
            external_username="second_user",
            display_name="Second User",
        )
        db_session.flush()

        assert second.is_default is False

    def test_set_default_identity(self, db_session: DBSession):
        """Test setting an identity as default."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        service = IdentityService(db_session)

        first = service.create_identity(
            provider_id=provider.provider_id,
            external_username="first_user",
            display_name="First User",
        )
        second = service.create_identity(
            provider_id=provider.provider_id,
            external_username="second_user",
            display_name="Second User",
        )
        db_session.flush()

        service.set_default_identity(second.id)
        db_session.flush()
        db_session.refresh(first)
        db_session.refresh(second)

        assert first.is_default is False
        assert second.is_default is True

    def test_set_default_clears_previous_default(self, db_session: DBSession):
        """Test that setting new default clears previous default."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        first = create_identity(
            db_session, provider=provider, external_username="first", is_default=True
        )
        second = create_identity(
            db_session, provider=provider, external_username="second", is_default=False
        )
        service = IdentityService(db_session)

        service.set_default_identity(second.id)
        db_session.flush()
        db_session.refresh(first)
        db_session.refresh(second)

        assert first.is_default is False
        assert second.is_default is True

    def test_set_default_only_affects_same_provider(self, db_session: DBSession):
        """Test that setting default only affects identities of same provider."""
        from rediska_core.domain.services.identity import IdentityService

        provider1 = create_provider(db_session, provider_id="reddit")
        provider2 = create_provider(db_session, provider_id="twitter")
        reddit_identity = create_identity(
            db_session, provider=provider1, external_username="reddit_user", is_default=True
        )
        twitter_identity = create_identity(
            db_session, provider=provider2, external_username="twitter_user", is_default=True
        )
        service = IdentityService(db_session)

        # Create new reddit identity and set as default
        new_reddit = service.create_identity(
            provider_id="reddit",
            external_username="new_reddit",
            display_name="New Reddit",
        )
        service.set_default_identity(new_reddit.id)
        db_session.flush()
        db_session.refresh(reddit_identity)
        db_session.refresh(twitter_identity)

        # Twitter default should be unchanged
        assert twitter_identity.is_default is True
        assert reddit_identity.is_default is False
        assert new_reddit.is_default is True

    def test_get_default_identity(self, db_session: DBSession):
        """Test getting default identity for a provider."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        create_identity(
            db_session, provider=provider, external_username="first", is_default=False
        )
        default = create_identity(
            db_session, provider=provider, external_username="second", is_default=True
        )
        service = IdentityService(db_session)

        result = service.get_default_identity(provider.provider_id)

        assert result is not None
        assert result.id == default.id

    def test_get_default_identity_none_exists(self, db_session: DBSession):
        """Test getting default identity when none exists."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        service = IdentityService(db_session)

        result = service.get_default_identity(provider.provider_id)

        assert result is None

    def test_cannot_delete_only_default(self, db_session: DBSession):
        """Test that deleting the only default identity fails."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        identity = create_identity(
            db_session, provider=provider, external_username="only_user", is_default=True
        )
        service = IdentityService(db_session)

        with pytest.raises(ValueError, match="default"):
            service.delete_identity(identity.id)

    def test_deleting_default_with_others_promotes_next(self, db_session: DBSession):
        """Test that deleting default identity promotes another."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        first = create_identity(
            db_session, provider=provider, external_username="first", is_default=True
        )
        second = create_identity(
            db_session, provider=provider, external_username="second", is_default=False
        )
        service = IdentityService(db_session)

        service.delete_identity(first.id)
        db_session.flush()
        db_session.refresh(second)

        assert second.is_default is True


class TestVoiceConfigValidation:
    """Tests for voice configuration validation."""

    def test_voice_config_valid_minimal(self, db_session: DBSession):
        """Test that minimal voice config is valid."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        service = IdentityService(db_session)

        voice_config = {"system_prompt": "You are helpful."}
        identity = service.create_identity(
            provider_id=provider.provider_id,
            external_username="user",
            display_name="User",
            voice_config=voice_config,
        )

        assert identity.voice_config_json == voice_config

    def test_voice_config_valid_full(self, db_session: DBSession):
        """Test that full voice config is valid."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        service = IdentityService(db_session)

        voice_config = {
            "system_prompt": "You are a helpful assistant.",
            "tone": "friendly",
            "style": "casual",
            "guidelines": ["Be helpful", "Be concise", "Be friendly"],
            "prohibited_topics": ["politics", "religion"],
            "example_responses": [
                {"input": "Hello", "output": "Hey there!"},
            ],
        }
        identity = service.create_identity(
            provider_id=provider.provider_id,
            external_username="user",
            display_name="User",
            voice_config=voice_config,
        )

        assert identity.voice_config_json == voice_config

    def test_voice_config_none_is_valid(self, db_session: DBSession):
        """Test that None voice config is valid."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        service = IdentityService(db_session)

        identity = service.create_identity(
            provider_id=provider.provider_id,
            external_username="user",
            display_name="User",
            voice_config=None,
        )

        assert identity.voice_config_json is None or identity.voice_config_json == {}

    def test_voice_config_empty_dict_is_valid(self, db_session: DBSession):
        """Test that empty dict voice config is valid."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        service = IdentityService(db_session)

        identity = service.create_identity(
            provider_id=provider.provider_id,
            external_username="user",
            display_name="User",
            voice_config={},
        )

        assert identity.voice_config_json == {}

    def test_voice_config_system_prompt_too_long(self, db_session: DBSession):
        """Test that overly long system prompt is rejected."""
        from rediska_core.domain.services.identity import IdentityService

        provider = create_provider(db_session)
        service = IdentityService(db_session)

        # System prompt > 10000 chars should be rejected
        voice_config = {"system_prompt": "x" * 10001}

        with pytest.raises(ValueError, match="system_prompt"):
            service.create_identity(
                provider_id=provider.provider_id,
                external_username="user",
                display_name="User",
                voice_config=voice_config,
            )


class TestOnboardingStatus:
    """Tests for onboarding status checking."""

    def test_has_identity_false_when_none(self, db_session: DBSession):
        """Test that has_identity returns False when no identities exist."""
        from rediska_core.domain.services.identity import IdentityService

        service = IdentityService(db_session)

        assert service.has_any_identity() is False

    def test_has_identity_true_when_exists(self, db_session: DBSession):
        """Test that has_identity returns True when identity exists."""
        from rediska_core.domain.services.identity import IdentityService

        create_identity(db_session)
        service = IdentityService(db_session)

        assert service.has_any_identity() is True

    def test_has_identity_false_when_only_inactive(self, db_session: DBSession):
        """Test that has_identity returns False when only inactive identities."""
        from rediska_core.domain.services.identity import IdentityService

        create_identity(db_session, is_active=False)
        service = IdentityService(db_session)

        assert service.has_any_identity() is False

    def test_get_setup_status_not_started(self, db_session: DBSession):
        """Test setup status when no identities exist."""
        from rediska_core.domain.services.identity import IdentityService

        service = IdentityService(db_session)

        status = service.get_setup_status()

        assert status["has_identity"] is False
        assert status["is_complete"] is False

    def test_get_setup_status_complete(self, db_session: DBSession):
        """Test setup status when identity exists."""
        from rediska_core.domain.services.identity import IdentityService

        create_identity(db_session, is_active=True)
        service = IdentityService(db_session)

        status = service.get_setup_status()

        assert status["has_identity"] is True
        assert status["is_complete"] is True
