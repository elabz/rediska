"""Reddit OAuth API routes."""

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from rediska_core.api.deps import CurrentUser, DBSession
from rediska_core.config import Settings, get_settings
from rediska_core.domain.models import Provider
from rediska_core.domain.services.credentials import CredentialsService
from rediska_core.infrastructure.crypto import CryptoService
from rediska_core.providers.reddit.oauth import OAuthError, RedditOAuthService


router = APIRouter(prefix="/providers/reddit/oauth", tags=["reddit", "oauth"])


# Store OAuth service instances per request (in-memory state)
# In production, use Redis with TTL for state storage
_oauth_services: dict[str, RedditOAuthService] = {}


def get_app_settings(request: Request) -> Settings:
    """Get settings from app state or default."""
    if hasattr(request.app.state, "settings"):
        return request.app.state.settings
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_app_settings)]


class OAuthStartResponse(BaseModel):
    """Response from OAuth start endpoint."""

    authorization_url: str
    state: str


class IdentityResponse(BaseModel):
    """Identity data in response."""

    id: int
    provider_id: str
    external_username: str
    external_user_id: Optional[str]
    display_name: str
    is_default: bool
    is_active: bool

    model_config = {"from_attributes": True}


class OAuthCallbackResponse(BaseModel):
    """Response from OAuth callback endpoint."""

    success: bool
    identity: IdentityResponse


def get_oauth_service(db: DBSession, settings: Settings) -> RedditOAuthService:
    """Get or create OAuth service instance."""
    # Create credentials service
    if not settings.encryption_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Encryption key not configured",
        )

    crypto = CryptoService(settings.encryption_key)
    credentials_service = CredentialsService(db, crypto)

    # Create OAuth service
    service = RedditOAuthService(
        db=db,
        client_id=settings.provider_reddit_client_id or "",
        client_secret=settings.provider_reddit_client_secret or "",
        redirect_uri=settings.provider_reddit_redirect_uri or f"{settings.base_url}/providers/reddit/oauth/callback",
        user_agent=settings.provider_reddit_user_agent,
        credentials_service=credentials_service,
    )

    return service


def check_reddit_enabled(db: DBSession, settings: Settings) -> None:
    """Check if Reddit provider is enabled."""
    # Check settings
    if not settings.provider_reddit_client_id or not settings.provider_reddit_client_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reddit provider is not configured (missing client credentials)",
        )

    # Check database
    provider = db.query(Provider).filter_by(provider_id="reddit").first()
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reddit provider is not registered",
        )

    if not provider.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reddit provider is not enabled",
        )


@router.get("/start", response_model=OAuthStartResponse)
async def oauth_start(
    current_user: CurrentUser,
    db: DBSession,
    settings: SettingsDep,
) -> OAuthStartResponse:
    """Start Reddit OAuth flow.

    Returns an authorization URL that the user should be redirected to.
    The state parameter is used to validate the callback.
    """
    check_reddit_enabled(db, settings)

    service = get_oauth_service(db, settings)

    # Store service for callback (using session-based key in production)
    url, state = service.generate_auth_url()

    # Store service instance for callback to access state
    _oauth_services[state] = service

    return OAuthStartResponse(
        authorization_url=url,
        state=state,
    )


@router.get("/callback", response_model=OAuthCallbackResponse)
async def oauth_callback(
    db: DBSession,
    settings: SettingsDep,
    current_user: CurrentUser,
    state: str = Query(..., description="State parameter for CSRF protection"),
    code: Optional[str] = Query(None, description="Authorization code from Reddit"),
    error: Optional[str] = Query(None, description="Error from Reddit (if any)"),
) -> OAuthCallbackResponse:
    """Handle Reddit OAuth callback.

    Exchanges the authorization code for tokens and creates/updates
    the user's identity.
    """
    check_reddit_enabled(db, settings)

    # Handle error from Reddit
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth error from Reddit: {error}",
        )

    # Ensure code is provided
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authorization code is required",
        )

    # Get the OAuth service that generated this state
    service = _oauth_services.pop(state, None)

    if service is None:
        # State not found in memory - could be expired or invalid
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid state parameter - OAuth flow may have expired",
        )

    try:
        # Re-add state so complete_oauth_flow can validate and consume it
        service._pending_states[state] = datetime.now(timezone.utc)
        identity = await service.complete_oauth_flow(code=code, state=state)
    except OAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return OAuthCallbackResponse(
        success=True,
        identity=IdentityResponse.model_validate(identity),
    )
