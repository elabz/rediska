"""API dependencies for dependency injection."""

from typing import Annotated, Optional

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from rediska_core.domain.models import LocalUser
from rediska_core.domain.services.auth import AuthService
from rediska_core.infra.db import get_sync_session_factory


def get_db() -> Session:
    """Get a database session."""
    session_factory = get_sync_session_factory()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_auth_service(db: Annotated[Session, Depends(get_db)]) -> AuthService:
    """Get the authentication service."""
    return AuthService(db)


def get_session_id(session: Annotated[Optional[str], Cookie()] = None) -> Optional[str]:
    """Get the session ID from cookie."""
    return session


def get_current_user_optional(
    session_id: Annotated[Optional[str], Depends(get_session_id)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> Optional[LocalUser]:
    """Get the current user if authenticated, None otherwise."""
    if not session_id:
        return None
    return auth_service.validate_session(session_id)


def get_current_user(
    user: Annotated[Optional[LocalUser], Depends(get_current_user_optional)],
) -> LocalUser:
    """Get the current authenticated user.

    Raises:
        HTTPException: If user is not authenticated.
    """
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return user


# Type aliases for cleaner route signatures
DBSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[LocalUser, Depends(get_current_user)]
CurrentUserOptional = Annotated[Optional[LocalUser], Depends(get_current_user_optional)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
SessionId = Annotated[Optional[str], Depends(get_session_id)]
