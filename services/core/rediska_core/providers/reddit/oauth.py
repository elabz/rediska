"""Reddit OAuth integration.

Handles Reddit's OAuth2 flow:
1. Generate authorization URL with state
2. Exchange authorization code for tokens
3. Store encrypted tokens
4. Refresh access tokens

Usage:
    service = RedditOAuthService(
        db=session,
        client_id="...",
        client_secret="...",
        redirect_uri="https://rediska.local/providers/reddit/oauth/callback",
        user_agent="Rediska/1.0",
        credentials_service=credentials_service,
    )

    # Start OAuth flow
    url, state = service.generate_auth_url()

    # After callback
    identity = await service.complete_oauth_flow(code, state)
"""

import json
import secrets
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from rediska_core.domain.models import AuditLog, Identity
from rediska_core.domain.services.credentials import CredentialsService


class OAuthError(Exception):
    """Raised when OAuth flow fails."""

    pass


class RedditOAuthService:
    """Service for handling Reddit OAuth flow."""

    # Reddit OAuth endpoints
    AUTHORIZE_URL = "https://www.reddit.com/api/v1/authorize"
    TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
    IDENTITY_URL = "https://oauth.reddit.com/api/v1/me"

    # Default scopes for Rediska
    DEFAULT_SCOPES = [
        "identity",        # Access username
        "privatemessages", # Read/send private messages
        "read",            # Read posts and comments
        "history",         # Access user history
    ]

    def __init__(
        self,
        db: Session,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        user_agent: str,
        credentials_service: Optional[CredentialsService] = None,
    ):
        """Initialize the OAuth service.

        Args:
            db: SQLAlchemy session.
            client_id: Reddit app client ID.
            client_secret: Reddit app client secret.
            redirect_uri: OAuth callback URL.
            user_agent: User-Agent for Reddit API requests.
            credentials_service: Service for storing encrypted credentials.
        """
        self.db = db
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.user_agent = user_agent
        self.credentials_service = credentials_service

        # In-memory state storage (in production, use Redis with TTL)
        self._pending_states: dict[str, datetime] = {}

    def generate_auth_url(self, scopes: Optional[list[str]] = None) -> tuple[str, str]:
        """Generate Reddit OAuth authorization URL.

        Args:
            scopes: OAuth scopes to request. Defaults to DEFAULT_SCOPES.

        Returns:
            Tuple of (authorization_url, state).
        """
        if scopes is None:
            scopes = self.DEFAULT_SCOPES

        # Generate secure random state
        state = secrets.token_urlsafe(32)
        self._pending_states[state] = datetime.now(timezone.utc)

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "state": state,
            "redirect_uri": self.redirect_uri,
            "duration": "permanent",  # Get refresh token
            "scope": " ".join(scopes),
        }

        url = f"{self.AUTHORIZE_URL}?{urlencode(params)}"
        return url, state

    def validate_state(self, state: str) -> bool:
        """Validate and consume an OAuth state.

        Args:
            state: The state parameter from callback.

        Returns:
            True if valid, False otherwise.
        """
        if state not in self._pending_states:
            return False

        # Remove state (one-time use)
        del self._pending_states[state]
        return True

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for tokens.

        Args:
            code: The authorization code from callback.

        Returns:
            Token response containing access_token, refresh_token, etc.

        Raises:
            OAuthError: If exchange fails.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                },
                auth=(self.client_id, self.client_secret),
                headers={"User-Agent": self.user_agent},
            )

        if response.status_code != 200:
            error_data = response.json()
            error_msg = error_data.get("error", "Unknown error")
            raise OAuthError(f"Token exchange failed: {error_msg}")

        return response.json()

    async def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh an access token using a refresh token.

        Args:
            refresh_token: The refresh token.

        Returns:
            New token response.

        Raises:
            OAuthError: If refresh fails.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                auth=(self.client_id, self.client_secret),
                headers={"User-Agent": self.user_agent},
            )

        if response.status_code != 200:
            error_data = response.json()
            error_msg = error_data.get("error", "Unknown error")
            raise OAuthError(f"Token refresh failed: {error_msg}")

        return response.json()

    async def get_user_identity(self, access_token: str) -> dict[str, str]:
        """Get the Reddit user's identity.

        Args:
            access_token: OAuth access token.

        Returns:
            Dict with username and user_id.

        Raises:
            OAuthError: If API call fails.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.IDENTITY_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "User-Agent": self.user_agent,
                },
            )

        if response.status_code != 200:
            raise OAuthError(f"Failed to get user identity: {response.text}")

        data = response.json()
        return {
            "username": data["name"],
            "user_id": data["id"],
        }

    async def store_tokens(self, identity_id: int, tokens: dict[str, Any]) -> None:
        """Store OAuth tokens for an identity.

        Args:
            identity_id: The identity ID to store tokens for.
            tokens: Token data to store.
        """
        if self.credentials_service is None:
            raise OAuthError("CredentialsService not configured")

        self.credentials_service.store_credential(
            provider_id="reddit",
            identity_id=identity_id,
            credential_type="oauth_tokens",
            secret=json.dumps(tokens),
        )

    async def get_tokens(self, identity_id: int) -> Optional[dict[str, Any]]:
        """Get stored OAuth tokens for an identity.

        Args:
            identity_id: The identity ID.

        Returns:
            Token data or None if not found.
        """
        if self.credentials_service is None:
            raise OAuthError("CredentialsService not configured")

        secret = self.credentials_service.get_credential_decrypted(
            provider_id="reddit",
            identity_id=identity_id,
            credential_type="oauth_tokens",
        )

        if secret is None:
            return None

        return json.loads(secret)

    async def complete_oauth_flow(self, code: str, state: str) -> Identity:
        """Complete the OAuth flow after callback.

        This method:
        1. Validates the state
        2. Exchanges the code for tokens
        3. Gets the user's identity
        4. Creates or updates the Identity record
        5. Stores the tokens
        6. Writes an audit log entry

        Args:
            code: Authorization code from callback.
            state: State parameter from callback.

        Returns:
            The created or updated Identity.

        Raises:
            OAuthError: If any step fails.
        """
        # Validate state
        if not self.validate_state(state):
            raise OAuthError("Invalid state parameter")

        # Exchange code for tokens
        tokens = await self.exchange_code(code)

        # Get user identity from Reddit
        user_info = await self.get_user_identity(tokens["access_token"])

        # Create or update identity
        identity = self._get_or_create_identity(
            username=user_info["username"],
            user_id=user_info["user_id"],
        )

        # Store tokens
        await self.store_tokens(identity.id, tokens)

        # Write audit log
        self._write_audit_log(identity, "provider.oauth.complete", "ok")

        return identity

    def _get_or_create_identity(self, username: str, user_id: str) -> Identity:
        """Get or create an identity for a Reddit user.

        Args:
            username: Reddit username.
            user_id: Reddit user ID.

        Returns:
            The Identity record.
        """
        # Check for existing identity
        identity = self.db.query(Identity).filter(
            Identity.provider_id == "reddit",
            Identity.external_username == username,
        ).first()

        if identity:
            # Update user ID if changed
            if identity.external_user_id != user_id:
                identity.external_user_id = user_id
                self.db.commit()
            return identity

        # Check if this is the first identity for Reddit
        existing_count = self.db.query(Identity).filter(
            Identity.provider_id == "reddit",
            Identity.is_active == True,
        ).count()
        is_first = existing_count == 0

        # Create new identity
        identity = Identity(
            provider_id="reddit",
            external_username=username,
            external_user_id=user_id,
            display_name=username,
            is_default=is_first,  # First identity is default
            is_active=True,
        )
        self.db.add(identity)
        self.db.commit()
        self.db.refresh(identity)

        return identity

    def _write_audit_log(
        self,
        identity: Identity,
        action_type: str,
        result: str,
        error_detail: Optional[str] = None,
    ) -> None:
        """Write an audit log entry.

        Args:
            identity: The identity involved.
            action_type: The action type.
            result: "ok" or "error".
            error_detail: Optional error details.
        """
        audit = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type=action_type,
            provider_id="reddit",
            identity_id=identity.id,
            entity_type="identity",
            entity_id=identity.id,
            result=result,
            error_detail=error_detail,
        )
        self.db.add(audit)
        self.db.commit()
