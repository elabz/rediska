"""Setup and onboarding API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from rediska_core.api.deps import CurrentUser, DBSession
from rediska_core.api.schemas.auth import (
    BootstrapRequest,
    BootstrapResponse,
    UserInfo,
)
from rediska_core.api.schemas.identity import SetupStatusResponse
from rediska_core.domain.services.auth import AuthService
from rediska_core.domain.services.identity import IdentityService

router = APIRouter(prefix="/setup", tags=["setup"])


def get_identity_service(db: DBSession) -> IdentityService:
    """Get the identity service."""
    return IdentityService(db)


IdentityServiceDep = Annotated[IdentityService, Depends(get_identity_service)]


def get_auth_service(db: DBSession) -> AuthService:
    """Get the auth service."""
    return AuthService(db)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


@router.post("/bootstrap", response_model=BootstrapResponse)
async def bootstrap_admin(
    request: BootstrapRequest,
    db: DBSession,
    auth_service: AuthServiceDep,
):
    """Bootstrap the admin user (first-time setup only).

    This endpoint only works when no users exist in the system.
    Once an admin user is created, this endpoint will return 403.
    """
    from rediska_core.domain.models import LocalUser

    # Check if any user already exists
    existing_user = db.query(LocalUser).first()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin user already exists. Use /auth/login instead.",
        )

    try:
        user = auth_service.bootstrap_admin(request.username, request.password)
        db.commit()
        return BootstrapResponse(user=UserInfo.model_validate(user))
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/status", response_model=SetupStatusResponse)
async def get_setup_status(
    current_user: CurrentUser,
    identity_service: IdentityServiceDep,
):
    """Get the current onboarding setup status.

    Returns information about whether the user has completed
    the initial setup (created at least one identity).
    """
    status = identity_service.get_setup_status()
    return SetupStatusResponse(**status)
