"""FastAPI authentication layer for Nyx Ichos (ROADMAP AA6, V1).

Design goal: correct by default, with no setting to remember.

The API runs in one of two modes, chosen automatically:

* **Unclaimed** — no owner account exists yet. This is a fresh local install, so
  the app works immediately without a login. Privileged routes are still refused,
  because there is nobody who could be authorised for them.
* **Claimed** — an owner account exists (someone ran `admin_setup.py claim`).
  Every route now requires a valid session, and each privileged route requires
  its specific permission.

The transition happens the moment the owner claims the account. Nothing to
configure, and no window where a deployed instance is accidentally wide open —
you cannot deploy a useful instance without claiming it first.
"""

from __future__ import annotations

from typing import Optional

from auth import AuthError, AuthStore, Permission, Role, User

try:
    from fastapi import Depends, Header, HTTPException, status
except ImportError as exc:  # pragma: no cover
    raise ImportError("FastAPI is required for server_auth.") from exc


AUTH_STORE = AuthStore()


def _bearer(authorization: Optional[str]) -> str:
    """Extract a bearer token, tolerating a bare token for convenience."""
    if not authorization:
        return ""
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip()


def is_claimed(store: Optional[AuthStore] = None) -> bool:
    """True once an owner account exists."""
    active = store or AUTH_STORE
    return any(u.role is Role.OWNER for u in active.users.values())


def current_user(authorization: Optional[str] = Header(default=None)) -> Optional[User]:
    """Resolve the caller, or None when unauthenticated.

    Never raises — routes decide whether anonymous access is acceptable.
    """
    return AUTH_STORE.resolve_session(_bearer(authorization))


def require_session(authorization: Optional[str] = Header(default=None)) -> Optional[User]:
    """Allow the request through, enforcing login only once the app is claimed.

    Returns the user when signed in, or None on an unclaimed local install.
    """
    user = current_user(authorization)
    if user is not None:
        return user
    if not is_claimed():
        return None
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sign in required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_permission(permission: Permission):
    """Build a dependency enforcing one permission.

    Privileged routes are refused on an unclaimed install too: with no owner,
    there is nobody who could legitimately hold the permission, and leaving these
    open would make an unclaimed instance strictly more powerful than a claimed
    one — exactly backwards.
    """

    def dependency(authorization: Optional[str] = Header(default=None)) -> User:
        user = current_user(authorization)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Sign in required. Run: python admin_setup.py claim <your-email>"
                    if not is_claimed()
                    else "Sign in required."
                ),
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            return AUTH_STORE.require(_bearer(authorization), permission)
        except AuthError as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=str(error)
            ) from error

    return dependency


# Routes that must stay reachable without a session, for obvious reasons:
# the client needs to discover whether a login is required, perform the login,
# and redeem an invite before it has any credentials at all.
PUBLIC_PATHS = frozenset({
    "/api/health",
    # Claiming happens before any account exists, so it cannot require a session.
    # It is guarded instead by being loopback-only and by refusing once an owner
    # exists - see server.claim_ownership.
    "/api/auth/claim",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/join",
    "/docs",
    "/redoc",
    "/openapi.json",
})


async def enforce_session_middleware(request, call_next):
    """Require a session for every /api route except the public allowlist.

    Deny by default. Adding a dependency to each route individually meant a new
    endpoint was unprotected until someone remembered to gate it — and the first
    pass at this missed `/api/memory`, `/api/chats`, and `/api/connectors`, all
    of which expose personal data. A path-based gate makes new routes protected
    automatically, which is the only version of this that stays correct as the
    surface grows.

    Only active once the app is claimed, so a fresh local install still works
    with no account.
    """
    path = request.url.path

    # Hosted builds do not merely gate the dangerous surfaces — the routes are
    # absent. A 404 rather than a 403 so a probe cannot even confirm they exist.
    from deploy_mode import hosted_blocked_reason, is_route_available

    if not is_route_available(path):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=404,
            content={"detail": hosted_blocked_reason(path)},
        )

    if (
        path.startswith("/api/")
        and path not in PUBLIC_PATHS
        and is_claimed()
        and current_user(request.headers.get("authorization")) is None
    ):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Sign in required."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)


# Convenience dependencies for the common gates.
RequireChat = Depends(require_session)
RequireAdmin = Depends(require_permission(Permission.VIEW_ADMIN))
RequireInvite = Depends(require_permission(Permission.INVITE_TESTERS))
RequireGrant = Depends(require_permission(Permission.GRANT_ADMIN))
RequireMachineControl = Depends(require_permission(Permission.MACHINE_CONTROL))
RequireReviewChanges = Depends(require_permission(Permission.REVIEW_CHANGES))
RequirePublishChanges = Depends(require_permission(Permission.PUBLISH_CHANGES))
RequireModifyAI = Depends(require_permission(Permission.MODIFY_BASE_AI))
