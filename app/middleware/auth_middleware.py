"""Auth middleware — protects all routes except public paths.

Session-based authentication using Starlette SessionMiddleware.
Redirect browser requests to /login, return 401 JSON for API calls.
"""

import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, JSONResponse

logger = logging.getLogger(__name__)

# These paths are accessible WITHOUT authentication
PUBLIC_PATHS = {
    "/login",
    "/auth/login",
    "/auth/logout",
    "/set",
    "/api/health",
    "/api/helper/release",
    "/api/device/register",
    "/download/helper.apk",
}

# Path prefixes that bypass auth
PUBLIC_PREFIXES = (
    "/static/",
    "/ws/device/",  # Android APK WebSocket — uses token auth
    "/download/",   # APK downloads
)


def _is_public(path: str) -> bool:
    """Check if path is publicly accessible (no auth required)."""
    if path in PUBLIC_PATHS:
        return True
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _is_browser_request(request: Request) -> bool:
    """Heuristic: is this a browser navigating (not an API call)?"""
    accept = request.headers.get("accept", "")
    return "text/html" in accept


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces session-based authentication."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Always allow public paths
        if _is_public(path):
            return await call_next(request)

        # Check session
        user_id = request.session.get("user_id")
        if user_id:
            # Valid session — allow through
            return await call_next(request)

        # Not authenticated — redirect or 401
        logger.debug(f"🔒 Blocked unauthenticated access to: {path}")

        if _is_browser_request(request):
            # Redirect browsers to login page
            redirect_url = f"/login?next={path}" if path != "/login" else "/login"
            return RedirectResponse(url=redirect_url, status_code=302)
        else:
            # Return JSON 401 for API calls
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized. Please login at /login"},
            )
