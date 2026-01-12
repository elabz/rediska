"""Unit tests for Reddit OAuth service."""

import json
import secrets
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from rediska_core.domain.models import AuditLog, Identity, Provider, ProviderCredential
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
    """Create a test Reddit provider."""
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


@pytest.fixture
def reddit_config() -> dict:
    """Reddit OAuth configuration."""
    return {
        "client_id": "test_client_id",
        "client_secret": "test_client_secret",
        "redirect_uri": "https://rediska.local/providers/reddit/oauth/callback",
        "user_agent": "Rediska/1.0 test",
    }


class TestRedditOAuthService:
    """Tests for RedditOAuthService."""

    def test_generate_auth_url_returns_valid_url(self, db_session, reddit_config):
        """generate_auth_url should return a valid Reddit authorization URL."""
        from rediska_core.providers.reddit.oauth import RedditOAuthService

        service = RedditOAuthService(
            db=db_session,
            client_id=reddit_config["client_id"],
            client_secret=reddit_config["client_secret"],
            redirect_uri=reddit_config["redirect_uri"],
            user_agent=reddit_config["user_agent"],
        )

        url, state = service.generate_auth_url()

        assert "https://www.reddit.com/api/v1/authorize" in url
        assert reddit_config["client_id"] in url
        assert "response_type=code" in url
        assert "duration=permanent" in url
        assert state in url
        assert len(state) >= 32

    def test_generate_auth_url_includes_required_scopes(self, db_session, reddit_config):
        """Authorization URL should include required OAuth scopes."""
        from rediska_core.providers.reddit.oauth import RedditOAuthService

        service = RedditOAuthService(
            db=db_session,
            client_id=reddit_config["client_id"],
            client_secret=reddit_config["client_secret"],
            redirect_uri=reddit_config["redirect_uri"],
            user_agent=reddit_config["user_agent"],
        )

        url, _ = service.generate_auth_url()

        # Required scopes for Rediska functionality
        assert "identity" in url
        assert "privatemessages" in url
        assert "read" in url
        assert "history" in url

    def test_generate_auth_url_creates_unique_states(self, db_session, reddit_config):
        """Each call should generate a unique state."""
        from rediska_core.providers.reddit.oauth import RedditOAuthService

        service = RedditOAuthService(
            db=db_session,
            client_id=reddit_config["client_id"],
            client_secret=reddit_config["client_secret"],
            redirect_uri=reddit_config["redirect_uri"],
            user_agent=reddit_config["user_agent"],
        )

        _, state1 = service.generate_auth_url()
        _, state2 = service.generate_auth_url()

        assert state1 != state2

    def test_generate_auth_url_stores_state(self, db_session, reddit_config):
        """State should be stored for later validation."""
        from rediska_core.providers.reddit.oauth import RedditOAuthService

        service = RedditOAuthService(
            db=db_session,
            client_id=reddit_config["client_id"],
            client_secret=reddit_config["client_secret"],
            redirect_uri=reddit_config["redirect_uri"],
            user_agent=reddit_config["user_agent"],
        )

        _, state = service.generate_auth_url()

        # Should be able to validate the state
        assert service.validate_state(state) is True

    def test_validate_state_returns_false_for_invalid(self, db_session, reddit_config):
        """validate_state should return False for unknown states."""
        from rediska_core.providers.reddit.oauth import RedditOAuthService

        service = RedditOAuthService(
            db=db_session,
            client_id=reddit_config["client_id"],
            client_secret=reddit_config["client_secret"],
            redirect_uri=reddit_config["redirect_uri"],
            user_agent=reddit_config["user_agent"],
        )

        assert service.validate_state("invalid-state-123") is False

    def test_validate_state_consumes_state(self, db_session, reddit_config):
        """State should be consumed after validation (one-time use)."""
        from rediska_core.providers.reddit.oauth import RedditOAuthService

        service = RedditOAuthService(
            db=db_session,
            client_id=reddit_config["client_id"],
            client_secret=reddit_config["client_secret"],
            redirect_uri=reddit_config["redirect_uri"],
            user_agent=reddit_config["user_agent"],
        )

        _, state = service.generate_auth_url()

        # First validation should succeed
        assert service.validate_state(state) is True
        # Second validation should fail (consumed)
        assert service.validate_state(state) is False

    @pytest.mark.asyncio
    async def test_exchange_code_returns_tokens(self, db_session, reddit_config):
        """exchange_code should return access and refresh tokens."""
        from rediska_core.providers.reddit.oauth import RedditOAuthService

        service = RedditOAuthService(
            db=db_session,
            client_id=reddit_config["client_id"],
            client_secret=reddit_config["client_secret"],
            redirect_uri=reddit_config["redirect_uri"],
            user_agent=reddit_config["user_agent"],
        )

        # Mock the HTTP client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "token_type": "bearer",
            "expires_in": 3600,
            "scope": "identity privatemessages read history",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_client_instance

            tokens = await service.exchange_code("test_auth_code")

        assert tokens["access_token"] == "test_access_token"
        assert tokens["refresh_token"] == "test_refresh_token"
        assert tokens["token_type"] == "bearer"
        assert tokens["expires_in"] == 3600

    @pytest.mark.asyncio
    async def test_exchange_code_raises_on_error(self, db_session, reddit_config):
        """exchange_code should raise exception on API error."""
        from rediska_core.providers.reddit.oauth import RedditOAuthService, OAuthError

        service = RedditOAuthService(
            db=db_session,
            client_id=reddit_config["client_id"],
            client_secret=reddit_config["client_secret"],
            redirect_uri=reddit_config["redirect_uri"],
            user_agent=reddit_config["user_agent"],
        )

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": "invalid_grant"}
        mock_response.text = "Invalid grant"

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_client_instance

            with pytest.raises(OAuthError) as exc_info:
                await service.exchange_code("invalid_code")

            assert "invalid_grant" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_user_identity_returns_username(self, db_session, reddit_config):
        """get_user_identity should return the Reddit username."""
        from rediska_core.providers.reddit.oauth import RedditOAuthService

        service = RedditOAuthService(
            db=db_session,
            client_id=reddit_config["client_id"],
            client_secret=reddit_config["client_secret"],
            redirect_uri=reddit_config["redirect_uri"],
            user_agent=reddit_config["user_agent"],
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "name": "testuser123",
            "id": "t2_abc123",
            "icon_img": "https://reddit.com/icon.png",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_client_instance

            identity = await service.get_user_identity("test_access_token")

        assert identity["username"] == "testuser123"
        assert identity["user_id"] == "t2_abc123"

    @pytest.mark.asyncio
    async def test_refresh_token_returns_new_access_token(self, db_session, reddit_config):
        """refresh_token should return a new access token."""
        from rediska_core.providers.reddit.oauth import RedditOAuthService

        service = RedditOAuthService(
            db=db_session,
            client_id=reddit_config["client_id"],
            client_secret=reddit_config["client_secret"],
            redirect_uri=reddit_config["redirect_uri"],
            user_agent=reddit_config["user_agent"],
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access_token",
            "token_type": "bearer",
            "expires_in": 3600,
            "scope": "identity privatemessages read history",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_client_instance

            tokens = await service.refresh_access_token("old_refresh_token")

        assert tokens["access_token"] == "new_access_token"


class TestStoreOAuthCredentials:
    """Tests for storing OAuth credentials."""

    @pytest.mark.asyncio
    async def test_store_credentials_encrypts_tokens(
        self,
        db_session: Session,
        credentials_service: CredentialsService,
        provider: Provider,
        identity: Identity,
    ):
        """Tokens should be stored encrypted."""
        from rediska_core.providers.reddit.oauth import RedditOAuthService

        service = RedditOAuthService(
            db=db_session,
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="http://test/callback",
            user_agent="Test/1.0",
            credentials_service=credentials_service,
        )

        tokens = {
            "access_token": "secret_access_token",
            "refresh_token": "secret_refresh_token",
            "token_type": "bearer",
            "expires_in": 3600,
        }

        await service.store_tokens(identity.id, tokens)

        # Check that tokens are stored encrypted
        cred = db_session.query(ProviderCredential).filter_by(
            provider_id="reddit",
            identity_id=identity.id,
            credential_type="oauth_tokens",
        ).first()

        assert cred is not None
        # Encrypted value should not contain plaintext tokens
        assert "secret_access_token" not in cred.secret_encrypted
        assert "secret_refresh_token" not in cred.secret_encrypted

        # But should be decryptable
        decrypted = credentials_service.crypto.decrypt(cred.secret_encrypted)
        token_data = json.loads(decrypted)
        assert token_data["access_token"] == "secret_access_token"

    @pytest.mark.asyncio
    async def test_store_credentials_can_be_retrieved(
        self,
        db_session: Session,
        credentials_service: CredentialsService,
        provider: Provider,
        identity: Identity,
    ):
        """Stored tokens should be retrievable."""
        from rediska_core.providers.reddit.oauth import RedditOAuthService

        service = RedditOAuthService(
            db=db_session,
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="http://test/callback",
            user_agent="Test/1.0",
            credentials_service=credentials_service,
        )

        tokens = {
            "access_token": "my_access_token",
            "refresh_token": "my_refresh_token",
            "token_type": "bearer",
            "expires_in": 3600,
        }

        await service.store_tokens(identity.id, tokens)
        retrieved = await service.get_tokens(identity.id)

        assert retrieved is not None
        assert retrieved["access_token"] == "my_access_token"
        assert retrieved["refresh_token"] == "my_refresh_token"

    @pytest.mark.asyncio
    async def test_store_credentials_rotates_on_update(
        self,
        db_session: Session,
        credentials_service: CredentialsService,
        provider: Provider,
        identity: Identity,
    ):
        """Storing new tokens should update existing and set rotated_at."""
        from rediska_core.providers.reddit.oauth import RedditOAuthService

        service = RedditOAuthService(
            db=db_session,
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="http://test/callback",
            user_agent="Test/1.0",
            credentials_service=credentials_service,
        )

        first_tokens = {"access_token": "first", "refresh_token": "first_refresh"}
        await service.store_tokens(identity.id, first_tokens)

        second_tokens = {"access_token": "second", "refresh_token": "second_refresh"}
        await service.store_tokens(identity.id, second_tokens)

        # Only one credential should exist
        creds = db_session.query(ProviderCredential).filter_by(
            provider_id="reddit",
            identity_id=identity.id,
        ).all()
        assert len(creds) == 1

        # Should have rotated_at set
        assert creds[0].rotated_at is not None

        # Should have new tokens
        retrieved = await service.get_tokens(identity.id)
        assert retrieved["access_token"] == "second"


class TestOAuthCallbackFlow:
    """Tests for the complete OAuth callback flow."""

    @pytest.mark.asyncio
    async def test_complete_oauth_flow_creates_identity(
        self,
        db_session: Session,
        credentials_service: CredentialsService,
        provider: Provider,
    ):
        """Complete OAuth flow should create or update identity."""
        from rediska_core.providers.reddit.oauth import RedditOAuthService

        service = RedditOAuthService(
            db=db_session,
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="http://test/callback",
            user_agent="Test/1.0",
            credentials_service=credentials_service,
        )

        # Mock exchange_code response
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "access_token",
            "refresh_token": "refresh_token",
            "token_type": "bearer",
            "expires_in": 3600,
        }

        # Mock get_user_identity response
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {
            "name": "newuser",
            "id": "t2_newuser",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = token_response
            mock_client_instance.get.return_value = user_response
            mock_client.return_value.__aenter__.return_value = mock_client_instance

            # Generate state first
            _, state = service.generate_auth_url()

            # Complete the flow
            identity = await service.complete_oauth_flow(
                code="auth_code",
                state=state,
            )

        assert identity is not None
        assert identity.external_username == "newuser"
        assert identity.external_user_id == "t2_newuser"
        assert identity.provider_id == "reddit"

    @pytest.mark.asyncio
    async def test_complete_oauth_flow_rejects_invalid_state(
        self,
        db_session: Session,
        credentials_service: CredentialsService,
        provider: Provider,
    ):
        """OAuth flow should reject requests with invalid state."""
        from rediska_core.providers.reddit.oauth import RedditOAuthService, OAuthError

        service = RedditOAuthService(
            db=db_session,
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="http://test/callback",
            user_agent="Test/1.0",
            credentials_service=credentials_service,
        )

        with pytest.raises(OAuthError) as exc_info:
            await service.complete_oauth_flow(
                code="auth_code",
                state="invalid-state",
            )

        assert "Invalid state" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_complete_oauth_flow_stores_tokens(
        self,
        db_session: Session,
        credentials_service: CredentialsService,
        provider: Provider,
    ):
        """OAuth flow should store tokens for the identity."""
        from rediska_core.providers.reddit.oauth import RedditOAuthService

        service = RedditOAuthService(
            db=db_session,
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="http://test/callback",
            user_agent="Test/1.0",
            credentials_service=credentials_service,
        )

        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "stored_access",
            "refresh_token": "stored_refresh",
            "token_type": "bearer",
            "expires_in": 3600,
        }

        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {
            "name": "tokenuser",
            "id": "t2_token",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = token_response
            mock_client_instance.get.return_value = user_response
            mock_client.return_value.__aenter__.return_value = mock_client_instance

            _, state = service.generate_auth_url()
            identity = await service.complete_oauth_flow(code="code", state=state)

        # Verify tokens are stored
        tokens = await service.get_tokens(identity.id)
        assert tokens["access_token"] == "stored_access"
        assert tokens["refresh_token"] == "stored_refresh"

    @pytest.mark.asyncio
    async def test_complete_oauth_flow_writes_audit_log(
        self,
        db_session: Session,
        credentials_service: CredentialsService,
        provider: Provider,
    ):
        """OAuth flow should write to audit log."""
        from rediska_core.providers.reddit.oauth import RedditOAuthService

        service = RedditOAuthService(
            db=db_session,
            client_id="test_id",
            client_secret="test_secret",
            redirect_uri="http://test/callback",
            user_agent="Test/1.0",
            credentials_service=credentials_service,
        )

        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "access",
            "refresh_token": "refresh",
            "token_type": "bearer",
            "expires_in": 3600,
        }

        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {
            "name": "audituser",
            "id": "t2_audit",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = token_response
            mock_client_instance.get.return_value = user_response
            mock_client.return_value.__aenter__.return_value = mock_client_instance

            _, state = service.generate_auth_url()
            await service.complete_oauth_flow(code="code", state=state)

        # Check audit log
        audit = db_session.query(AuditLog).filter_by(
            action_type="provider.oauth.complete"
        ).first()
        assert audit is not None
        assert audit.provider_id == "reddit"
        assert audit.result == "ok"
