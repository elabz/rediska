"""Authentication schemas for request/response validation."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Request body for login endpoint."""

    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """Response body for successful login."""

    success: bool = True
    user: "UserInfo"


class LogoutResponse(BaseModel):
    """Response body for successful logout."""

    success: bool = True
    message: str = "Logged out successfully"


class UserInfo(BaseModel):
    """Public user information (no sensitive data)."""

    id: int
    username: str
    created_at: datetime
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ErrorResponse(BaseModel):
    """Error response body."""

    detail: str


class BootstrapRequest(BaseModel):
    """Request body for admin bootstrap endpoint."""

    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=8, description="Minimum 8 characters")


class BootstrapResponse(BaseModel):
    """Response body for successful bootstrap."""

    success: bool = True
    message: str = "Admin user created successfully"
    user: "UserInfo"


# Update forward references
LoginResponse.model_rebuild()
BootstrapResponse.model_rebuild()
