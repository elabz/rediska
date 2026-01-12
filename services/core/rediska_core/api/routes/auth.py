"""Authentication API routes."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response, status

from rediska_core.api.deps import (
    AuthServiceDep,
    CurrentUser,
    DBSession,
    SessionId,
)
from rediska_core.api.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    UserInfo,
)
from rediska_core.config import get_settings
from rediska_core.domain.models import AuditLog

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    response: Response,
    auth_service: AuthServiceDep,
    db: DBSession,
) -> LoginResponse:
    """Authenticate user and create session.

    Sets a session cookie on successful authentication.
    """
    # Authenticate user
    user = auth_service.authenticate_user(request.username, request.password)

    if user is None:
        # Log failed attempt
        audit = AuditLog(
            ts=datetime.now(timezone.utc),
            actor="user",
            action_type="auth.login",
            result="error",
            request_json={"username": request.username},
            error_detail="Invalid username or password",
        )
        db.add(audit)
        db.flush()

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # Create session
    settings = get_settings()
    session_id = auth_service.create_session(
        user.id,
        expire_hours=settings.session_expire_hours,
    )
    db.flush()

    # Log successful login
    audit = AuditLog(
        ts=datetime.now(timezone.utc),
        actor="user",
        action_type="auth.login",
        result="ok",
        request_json={"username": request.username},
        entity_type="local_user",
        entity_id=user.id,
    )
    db.add(audit)

    # Set session cookie
    response.set_cookie(
        key="session",
        value=session_id,
        httponly=True,
        secure=True,  # Requires HTTPS
        samesite="lax",
        max_age=settings.session_expire_hours * 3600,
    )

    return LoginResponse(
        success=True,
        user=UserInfo.model_validate(user),
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    response: Response,
    session_id: SessionId,
    auth_service: AuthServiceDep,
    current_user: CurrentUser,
    db: DBSession,
) -> LogoutResponse:
    """Invalidate current session and clear cookie."""
    # Invalidate session
    if session_id:
        auth_service.invalidate_session(session_id)

    # Log logout
    audit = AuditLog(
        ts=datetime.now(timezone.utc),
        actor="user",
        action_type="auth.logout",
        result="ok",
        entity_type="local_user",
        entity_id=current_user.id,
    )
    db.add(audit)

    # Clear session cookie
    response.delete_cookie(
        key="session",
        httponly=True,
        secure=True,
        samesite="lax",
    )

    return LogoutResponse()


@router.get("/me", response_model=UserInfo)
async def get_current_user_info(
    current_user: CurrentUser,
) -> UserInfo:
    """Get information about the currently authenticated user."""
    return UserInfo.model_validate(current_user)
