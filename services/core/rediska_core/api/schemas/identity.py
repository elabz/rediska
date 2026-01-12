"""Identity schemas for request/response validation."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class IdentityCreate(BaseModel):
    """Request body for creating an identity."""

    provider_id: str = Field(..., min_length=1, max_length=32)
    external_username: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=128)
    external_user_id: Optional[str] = Field(None, max_length=128)
    voice_config: Optional[dict[str, Any]] = None


class IdentityUpdate(BaseModel):
    """Request body for updating an identity."""

    display_name: Optional[str] = Field(None, min_length=1, max_length=128)
    voice_config: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None


class IdentityResponse(BaseModel):
    """Response body for an identity."""

    id: int
    provider_id: str
    external_username: str
    external_user_id: Optional[str] = None
    display_name: str
    voice_config: Optional[dict[str, Any]] = None
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_model(cls, identity) -> "IdentityResponse":
        """Create response from Identity model."""
        return cls(
            id=identity.id,
            provider_id=identity.provider_id,
            external_username=identity.external_username,
            external_user_id=identity.external_user_id,
            display_name=identity.display_name,
            voice_config=identity.voice_config_json,
            is_default=identity.is_default,
            is_active=identity.is_active,
            created_at=identity.created_at,
            updated_at=identity.updated_at,
        )


class IdentityListResponse(BaseModel):
    """Response body for listing identities."""

    identities: list[IdentityResponse]
    total: int


class IdentityGroupedResponse(BaseModel):
    """Response body for grouped identities."""

    by_provider: dict[str, list[IdentityResponse]]
    total: int


class SetupStatusResponse(BaseModel):
    """Response body for setup status."""

    has_identity: bool
    is_complete: bool


class DeleteResponse(BaseModel):
    """Response body for delete operation."""

    success: bool = True
    message: str = "Identity deactivated successfully"
