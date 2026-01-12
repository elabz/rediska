"""Identity management API routes."""

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from rediska_core.api.deps import CurrentUser, DBSession, get_db
from rediska_core.api.schemas.identity import (
    DeleteResponse,
    IdentityCreate,
    IdentityGroupedResponse,
    IdentityListResponse,
    IdentityResponse,
    IdentityUpdate,
)
from rediska_core.domain.models import AuditLog
from rediska_core.domain.services.identity import IdentityService

router = APIRouter(prefix="/identities", tags=["identities"])


def get_identity_service(db: DBSession) -> IdentityService:
    """Get the identity service."""
    return IdentityService(db)


IdentityServiceDep = Annotated[IdentityService, Depends(get_identity_service)]


@router.get("", response_model=IdentityListResponse | IdentityGroupedResponse)
async def list_identities(
    current_user: CurrentUser,
    identity_service: IdentityServiceDep,
    provider_id: Optional[str] = Query(None, description="Filter by provider ID"),
    grouped: bool = Query(False, description="Group by provider"),
):
    """List all identities, optionally filtered by provider."""
    if grouped:
        grouped_identities = identity_service.list_identities_grouped()
        by_provider = {
            provider: [IdentityResponse.from_model(i) for i in identities]
            for provider, identities in grouped_identities.items()
        }
        total = sum(len(ids) for ids in grouped_identities.values())
        return IdentityGroupedResponse(by_provider=by_provider, total=total)

    identities = identity_service.list_identities(provider_id=provider_id)
    return IdentityListResponse(
        identities=[IdentityResponse.from_model(i) for i in identities],
        total=len(identities),
    )


@router.post("", response_model=IdentityResponse, status_code=status.HTTP_201_CREATED)
async def create_identity(
    request: IdentityCreate,
    current_user: CurrentUser,
    identity_service: IdentityServiceDep,
    db: DBSession,
):
    """Create a new identity."""
    try:
        identity = identity_service.create_identity(
            provider_id=request.provider_id,
            external_username=request.external_username,
            display_name=request.display_name,
            external_user_id=request.external_user_id,
            voice_config=request.voice_config,
        )

        # Write audit log
        audit = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="identity.create",
            result="ok",
            provider_id=request.provider_id,
            identity_id=identity.id,
            entity_type="identity",
            entity_id=identity.id,
            request_json={
                "provider_id": request.provider_id,
                "external_username": request.external_username,
                "display_name": request.display_name,
            },
        )
        db.add(audit)

        return IdentityResponse.from_model(identity)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/{identity_id}", response_model=IdentityResponse)
async def get_identity(
    identity_id: int,
    current_user: CurrentUser,
    identity_service: IdentityServiceDep,
):
    """Get an identity by ID."""
    identity = identity_service.get_identity(identity_id)

    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identity {identity_id} not found",
        )

    return IdentityResponse.from_model(identity)


@router.patch("/{identity_id}", response_model=IdentityResponse)
async def update_identity(
    identity_id: int,
    request: IdentityUpdate,
    current_user: CurrentUser,
    identity_service: IdentityServiceDep,
    db: DBSession,
):
    """Update an identity."""
    try:
        identity = identity_service.update_identity(
            identity_id=identity_id,
            display_name=request.display_name,
            voice_config=request.voice_config,
            is_active=request.is_active,
        )

        # Write audit log
        audit = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="identity.update",
            result="ok",
            provider_id=identity.provider_id,
            identity_id=identity.id,
            entity_type="identity",
            entity_id=identity.id,
            request_json=request.model_dump(exclude_none=True),
        )
        db.add(audit)

        return IdentityResponse.from_model(identity)

    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete("/{identity_id}", response_model=DeleteResponse)
async def delete_identity(
    identity_id: int,
    current_user: CurrentUser,
    identity_service: IdentityServiceDep,
    db: DBSession,
):
    """Delete (deactivate) an identity."""
    # Get identity first for audit log
    identity = identity_service.get_identity(identity_id, include_inactive=True)
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identity {identity_id} not found",
        )

    try:
        identity_service.delete_identity(identity_id)

        # Write audit log
        audit = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="identity.delete",
            result="ok",
            provider_id=identity.provider_id,
            identity_id=identity.id,
            entity_type="identity",
            entity_id=identity.id,
        )
        db.add(audit)

        return DeleteResponse()

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/{identity_id}/set-default", response_model=IdentityResponse)
async def set_default_identity(
    identity_id: int,
    current_user: CurrentUser,
    identity_service: IdentityServiceDep,
    db: DBSession,
):
    """Set an identity as the default for its provider."""
    try:
        identity = identity_service.set_default_identity(identity_id)

        # Write audit log
        audit = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="identity.set_default",
            result="ok",
            provider_id=identity.provider_id,
            identity_id=identity.id,
            entity_type="identity",
            entity_id=identity.id,
        )
        db.add(audit)

        return IdentityResponse.from_model(identity)

    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
