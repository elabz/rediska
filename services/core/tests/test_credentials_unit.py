"""Unit tests for CredentialsService."""

import json
import pytest
from datetime import datetime

from sqlalchemy.orm import Session

from rediska_core.domain.models import Provider, Identity, ProviderCredential
from rediska_core.domain.services.credentials import CredentialsService
from rediska_core.infrastructure.crypto import CryptoService


@pytest.fixture
def crypto_key() -> str:
    """Generate a test encryption key."""
    return CryptoService.generate_key()


@pytest.fixture
def crypto_service(crypto_key: str) -> CryptoService:
    """Create a CryptoService instance."""
    return CryptoService(crypto_key)


@pytest.fixture
def credentials_service(db_session: Session, crypto_service: CryptoService) -> CredentialsService:
    """Create a CredentialsService instance."""
    return CredentialsService(db_session, crypto_service)


@pytest.fixture
def provider(db_session: Session) -> Provider:
    """Create a test provider."""
    provider = Provider(
        provider_id="reddit",
        display_name="Reddit",
        enabled=True,
    )
    db_session.add(provider)
    db_session.commit()
    return provider


@pytest.fixture
def identity(db_session: Session, provider: Provider) -> Identity:
    """Create a test identity."""
    identity = Identity(
        provider_id=provider.provider_id,
        external_username="test_user",
        external_user_id="t2_abc123",
        display_name="Test User",
        is_default=True,
        is_active=True,
    )
    db_session.add(identity)
    db_session.commit()
    return identity


class TestCredentialsServiceStoreCredential:
    """Tests for store_credential method."""

    def test_store_credential_creates_new_record(
        self,
        credentials_service: CredentialsService,
        db_session: Session,
        provider: Provider,
        identity: Identity,
    ):
        """store_credential should create a new credential record."""
        credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            secret="my-secret-token",
        )

        cred = db_session.query(ProviderCredential).first()
        assert cred is not None
        assert cred.provider_id == provider.provider_id
        assert cred.identity_id == identity.id
        assert cred.credential_type == "oauth_refresh_token"

    def test_store_credential_encrypts_secret(
        self,
        credentials_service: CredentialsService,
        db_session: Session,
        provider: Provider,
        identity: Identity,
    ):
        """Stored secret should be encrypted."""
        secret = "my-secret-token"
        credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            secret=secret,
        )

        cred = db_session.query(ProviderCredential).first()
        # Encrypted value should be different from plaintext
        assert cred.secret_encrypted != secret
        # Should be able to decrypt
        decrypted = credentials_service.crypto.decrypt(cred.secret_encrypted)
        assert decrypted == secret

    def test_store_credential_without_identity(
        self,
        credentials_service: CredentialsService,
        db_session: Session,
        provider: Provider,
    ):
        """Should be able to store app-level credentials without identity."""
        credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=None,
            credential_type="api_key",
            secret="app-api-key",
        )

        cred = db_session.query(ProviderCredential).first()
        assert cred is not None
        assert cred.identity_id is None

    def test_store_credential_returns_credential(
        self,
        credentials_service: CredentialsService,
        provider: Provider,
        identity: Identity,
    ):
        """store_credential should return the created credential."""
        result = credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            secret="my-secret-token",
        )

        assert isinstance(result, ProviderCredential)
        assert result.id is not None

    def test_store_credential_sets_created_at(
        self,
        credentials_service: CredentialsService,
        provider: Provider,
        identity: Identity,
    ):
        """store_credential should set created_at timestamp."""
        result = credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            secret="my-secret-token",
        )

        assert result.created_at is not None
        assert isinstance(result.created_at, datetime)

    def test_store_credential_updates_existing(
        self,
        credentials_service: CredentialsService,
        db_session: Session,
        provider: Provider,
        identity: Identity,
    ):
        """Storing same credential type should update existing."""
        credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            secret="first-token",
        )

        credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            secret="second-token",
        )

        creds = db_session.query(ProviderCredential).all()
        assert len(creds) == 1

        decrypted = credentials_service.crypto.decrypt(creds[0].secret_encrypted)
        assert decrypted == "second-token"

    def test_store_credential_updates_rotated_at_on_update(
        self,
        credentials_service: CredentialsService,
        provider: Provider,
        identity: Identity,
    ):
        """Updating credential should set rotated_at."""
        first = credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            secret="first-token",
        )
        assert first.rotated_at is None

        second = credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            secret="second-token",
        )
        assert second.rotated_at is not None


class TestCredentialsServiceGetCredential:
    """Tests for get_credential method."""

    def test_get_credential_returns_encrypted(
        self,
        credentials_service: CredentialsService,
        provider: Provider,
        identity: Identity,
    ):
        """get_credential should return credential with encrypted secret."""
        credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            secret="my-secret-token",
        )

        result = credentials_service.get_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
        )

        assert result is not None
        assert result.secret_encrypted != "my-secret-token"

    def test_get_credential_returns_none_if_not_found(
        self,
        credentials_service: CredentialsService,
        provider: Provider,
        identity: Identity,
    ):
        """get_credential should return None if credential doesn't exist."""
        result = credentials_service.get_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="nonexistent",
        )

        assert result is None

    def test_get_credential_matches_exact_identity(
        self,
        credentials_service: CredentialsService,
        db_session: Session,
        provider: Provider,
        identity: Identity,
    ):
        """get_credential should match exact identity_id."""
        # Create another identity
        identity2 = Identity(
            provider_id=provider.provider_id,
            external_username="other_user",
            display_name="Other User",
            is_default=False,
            is_active=True,
        )
        db_session.add(identity2)
        db_session.commit()

        credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            secret="token-for-identity-1",
        )

        # Should find for identity
        result = credentials_service.get_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
        )
        assert result is not None

        # Should not find for identity2
        result2 = credentials_service.get_credential(
            provider_id=provider.provider_id,
            identity_id=identity2.id,
            credential_type="oauth_refresh_token",
        )
        assert result2 is None


class TestCredentialsServiceGetCredentialDecrypted:
    """Tests for get_credential_decrypted method."""

    def test_get_credential_decrypted_returns_plaintext(
        self,
        credentials_service: CredentialsService,
        provider: Provider,
        identity: Identity,
    ):
        """get_credential_decrypted should return plaintext secret."""
        credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            secret="my-secret-token",
        )

        result = credentials_service.get_credential_decrypted(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
        )

        assert result == "my-secret-token"

    def test_get_credential_decrypted_returns_none_if_not_found(
        self,
        credentials_service: CredentialsService,
        provider: Provider,
        identity: Identity,
    ):
        """get_credential_decrypted should return None if not found."""
        result = credentials_service.get_credential_decrypted(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="nonexistent",
        )

        assert result is None

    def test_get_credential_decrypted_with_json_data(
        self,
        credentials_service: CredentialsService,
        provider: Provider,
        identity: Identity,
    ):
        """Should be able to store and retrieve JSON data."""
        token_data = {
            "access_token": "abc123",
            "refresh_token": "xyz789",
            "expires_in": 3600,
            "token_type": "bearer",
        }
        credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_tokens",
            secret=json.dumps(token_data),
        )

        result = credentials_service.get_credential_decrypted(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_tokens",
        )

        assert json.loads(result) == token_data


class TestCredentialsServiceRotateCredential:
    """Tests for rotate_credential method."""

    def test_rotate_credential_updates_secret(
        self,
        credentials_service: CredentialsService,
        provider: Provider,
        identity: Identity,
    ):
        """rotate_credential should update the secret."""
        credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            secret="old-token",
        )

        credentials_service.rotate_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            new_secret="new-token",
        )

        result = credentials_service.get_credential_decrypted(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
        )

        assert result == "new-token"

    def test_rotate_credential_sets_rotated_at(
        self,
        credentials_service: CredentialsService,
        provider: Provider,
        identity: Identity,
    ):
        """rotate_credential should set rotated_at timestamp."""
        credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            secret="old-token",
        )

        result = credentials_service.rotate_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            new_secret="new-token",
        )

        assert result.rotated_at is not None

    def test_rotate_credential_returns_none_if_not_found(
        self,
        credentials_service: CredentialsService,
        provider: Provider,
        identity: Identity,
    ):
        """rotate_credential should return None if credential doesn't exist."""
        result = credentials_service.rotate_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="nonexistent",
            new_secret="new-token",
        )

        assert result is None


class TestCredentialsServiceDeleteCredential:
    """Tests for delete_credential method."""

    def test_delete_credential_removes_record(
        self,
        credentials_service: CredentialsService,
        db_session: Session,
        provider: Provider,
        identity: Identity,
    ):
        """delete_credential should remove the credential record."""
        credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            secret="my-token",
        )

        assert db_session.query(ProviderCredential).count() == 1

        result = credentials_service.delete_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
        )

        assert result is True
        assert db_session.query(ProviderCredential).count() == 0

    def test_delete_credential_returns_false_if_not_found(
        self,
        credentials_service: CredentialsService,
        provider: Provider,
        identity: Identity,
    ):
        """delete_credential should return False if credential doesn't exist."""
        result = credentials_service.delete_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="nonexistent",
        )

        assert result is False


class TestCredentialsServiceListCredentials:
    """Tests for list_credentials method."""

    def test_list_credentials_by_provider(
        self,
        credentials_service: CredentialsService,
        provider: Provider,
        identity: Identity,
    ):
        """list_credentials should return all credentials for a provider."""
        credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            secret="token1",
        )
        credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_access_token",
            secret="token2",
        )

        result = credentials_service.list_credentials(provider_id=provider.provider_id)

        assert len(result) == 2

    def test_list_credentials_by_identity(
        self,
        credentials_service: CredentialsService,
        db_session: Session,
        provider: Provider,
        identity: Identity,
    ):
        """list_credentials should filter by identity_id."""
        identity2 = Identity(
            provider_id=provider.provider_id,
            external_username="other_user",
            display_name="Other User",
            is_default=False,
            is_active=True,
        )
        db_session.add(identity2)
        db_session.commit()

        credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            secret="token1",
        )
        credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity2.id,
            credential_type="oauth_refresh_token",
            secret="token2",
        )

        result = credentials_service.list_credentials(
            provider_id=provider.provider_id,
            identity_id=identity.id,
        )

        assert len(result) == 1
        assert result[0].identity_id == identity.id

    def test_list_credentials_empty(
        self,
        credentials_service: CredentialsService,
        provider: Provider,
    ):
        """list_credentials should return empty list if no credentials."""
        result = credentials_service.list_credentials(provider_id=provider.provider_id)
        assert result == []


class TestCredentialsServiceHasValidCredential:
    """Tests for has_valid_credential method."""

    def test_has_valid_credential_returns_true(
        self,
        credentials_service: CredentialsService,
        provider: Provider,
        identity: Identity,
    ):
        """has_valid_credential should return True if credential exists."""
        credentials_service.store_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
            secret="my-token",
        )

        result = credentials_service.has_valid_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
        )

        assert result is True

    def test_has_valid_credential_returns_false(
        self,
        credentials_service: CredentialsService,
        provider: Provider,
        identity: Identity,
    ):
        """has_valid_credential should return False if no credential."""
        result = credentials_service.has_valid_credential(
            provider_id=provider.provider_id,
            identity_id=identity.id,
            credential_type="oauth_refresh_token",
        )

        assert result is False
