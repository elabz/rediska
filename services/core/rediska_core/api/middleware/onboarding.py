"""Onboarding gate middleware.

Blocks access to protected endpoints until the user has completed
the initial setup (created at least one identity).
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from rediska_core.domain.services.identity import IdentityService
from rediska_core.infra.db import get_sync_session_factory


# Paths that bypass the onboarding gate
BYPASS_PATHS = {
    # Health and root
    "/",
    "/healthz",
    "/docs",
    "/redoc",
    "/openapi.json",
    # Auth endpoints
    "/auth/login",
    "/auth/logout",
    "/auth/me",
    # Setup and identity endpoints (needed for onboarding)
    "/setup/status",
    "/identities",
}

# Path prefixes that bypass the gate
BYPASS_PREFIXES = (
    "/auth/",
    "/setup/",
    "/identities",
    "/providers/",  # OAuth flows needed during identity setup
)


class OnboardingGateMiddleware(BaseHTTPMiddleware):
    """Middleware that blocks access until setup is complete."""

    async def dispatch(self, request: Request, call_next):
        """Process the request."""
        path = request.url.path

        # Skip for paths that bypass the gate
        if path in BYPASS_PATHS:
            return await call_next(request)

        # Skip for path prefixes that bypass the gate
        if path.startswith(BYPASS_PREFIXES):
            return await call_next(request)

        # Skip for OPTIONS requests (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)

        # Check if user is authenticated (has session cookie)
        session_id = request.cookies.get("session")
        if not session_id:
            # Let the auth middleware handle unauthenticated requests
            return await call_next(request)

        # Check if setup is complete
        try:
            session_factory = get_sync_session_factory()
            with session_factory() as db:
                identity_service = IdentityService(db)
                if not identity_service.has_any_identity():
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={
                            "detail": "Setup not complete. Please create an identity first.",
                            "code": "ONBOARDING_REQUIRED",
                        },
                    )
        except Exception:
            # If we can't check, let the request through
            # (other error handling will catch issues)
            pass

        return await call_next(request)
