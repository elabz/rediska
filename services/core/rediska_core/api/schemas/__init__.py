"""API schemas."""

from rediska_core.api.schemas.audit import (
    AuditEntryResponse,
    AuditListResponse,
)
from rediska_core.api.schemas.auth import (
    ErrorResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    UserInfo,
)
from rediska_core.api.schemas.identity import (
    DeleteResponse,
    IdentityCreate,
    IdentityGroupedResponse,
    IdentityListResponse,
    IdentityResponse,
    IdentityUpdate,
    SetupStatusResponse,
)

__all__ = [
    # Audit schemas
    "AuditEntryResponse",
    "AuditListResponse",
    # Auth schemas
    "ErrorResponse",
    "LoginRequest",
    "LoginResponse",
    "LogoutResponse",
    "UserInfo",
    # Identity schemas
    "DeleteResponse",
    "IdentityCreate",
    "IdentityGroupedResponse",
    "IdentityListResponse",
    "IdentityResponse",
    "IdentityUpdate",
    "SetupStatusResponse",
]
