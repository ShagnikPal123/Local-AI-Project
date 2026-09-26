"""HTTP routes for beta/dev access keys (OVERHAUL_CONTRACTS.md section 4.6).

Included by server.py's ``_include_routers()`` if this module imports cleanly
(see AGENTS.md section 5 / server.py's router loop) - no edit to server.py is
needed to wire this in.

Two tiers of gating:

* ``/api/access/status`` and ``/api/access/redeem`` use the same
  ``RequireChat`` gate as any other chat-adjacent route: open on an unclaimed
  local install, requiring a session once claimed. Any signed-in user
  (including a beta tester) may check or improve their own access level.
* Everything else is an owner/admin action. ``server_auth.RequireAdmin``
  refuses outright on an unclaimed install (nobody could hold the permission
  yet - see server_auth.require_permission), which would make a fresh local
  install unable to mint its own owner's first key. So these routes use a
  small dependency that mirrors ``server.require_local_owner`` instead: admin
  permission once claimed, loopback-only before that. It is imported lazily
  from ``server`` inside the dependency function (not at module import time)
  because server.py imports this module while building itself - a top-level
  ``from server import ...`` here would be a circular import.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import access_keys
from auth import Role
from server_auth import RequireChat

router = APIRouter()


def _require_admin_or_local_owner(request: Request) -> Any:
    """Admin once claimed; loopback-only before that. See module docstring."""
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


def _actor_label(caller: Any, request: Request) -> str:
    """A readable "who did this" string for the audit log - never a secret."""
    email = getattr(caller, "email", None)
    if email:
        return email
    host = request.client.host if request.client else "local"
    return f"owner@{host}"


def _caller_is_owner(user: Any) -> bool:
    # RequireChat returns None on an unclaimed local install - the person at
    # the keyboard owns their own machine either way (access_keys.status()'s
    # `owner` rule).
    return user is None or getattr(user, "role", None) == Role.OWNER


# ---------------------------------------------------------------------------
# Open to any signed-in caller (or anyone, pre-claim)
# ---------------------------------------------------------------------------


@router.get("/api/access/status")
def get_access_status(user: Any = RequireChat) -> Dict[str, Any]:
    return access_keys.status(owner=_caller_is_owner(user))


class RedeemRequest(BaseModel):
    key: str = ""


@router.post("/api/access/redeem")
def redeem_access_key(body: RedeemRequest, user: Any = RequireChat) -> Dict[str, Any]:
    try:
        access_keys.redeem(body.key)
    except access_keys.AccessKeyError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return access_keys.status(owner=_caller_is_owner(user))


# ---------------------------------------------------------------------------
# Owner/admin only
# ---------------------------------------------------------------------------


@router.post("/api/access/signing-key")
def admin_signing_key(_caller: Any = Depends(_require_admin_or_local_owner)) -> Dict[str, str]:
    return access_keys.ensure_signing_key()


class MintRequest(BaseModel):
    role: str
    name: str = ""
    email: str = ""
    days: int = 90
    features: Optional[List[str]] = None
    notes: str = ""


@router.post("/api/access/mint")
def admin_mint(
    body: MintRequest, request: Request, caller: Any = Depends(_require_admin_or_local_owner)
) -> Dict[str, Any]:
    try:
        return access_keys.mint(
            body.role, body.name, email=body.email, days=body.days,
            features=body.features, notes=body.notes, actor=_actor_label(caller, request),
        )
    except access_keys.AccessKeyError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/api/access/minted")
def admin_list_minted(_caller: Any = Depends(_require_admin_or_local_owner)) -> Dict[str, Any]:
    return access_keys.list_minted()


@router.post("/api/access/revoke/{key_id}")
def admin_revoke(
    key_id: str, request: Request, caller: Any = Depends(_require_admin_or_local_owner)
) -> Dict[str, Any]:
    return access_keys.revoke(key_id, actor=_actor_label(caller, request))


@router.get("/api/access/applications")
def admin_list_applications(_caller: Any = Depends(_require_admin_or_local_owner)) -> Dict[str, Any]:
    return access_keys.list_applications()


class DecisionRequest(BaseModel):
    approve: bool
    days: int = 90


@router.post("/api/access/applications/{app_id}/decision")
def admin_decide_application(
    app_id: str, body: DecisionRequest, request: Request,
    caller: Any = Depends(_require_admin_or_local_owner),
) -> Dict[str, Any]:
    try:
        return access_keys.decide_application(
            app_id, body.approve, actor=_actor_label(caller, request), days=body.days
        )
    except access_keys.AccessKeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/api/access/flags")
def admin_get_flags(_caller: Any = Depends(_require_admin_or_local_owner)) -> Dict[str, Any]:
    return {"flags": access_keys.get_flags()}


class FlagsRequest(BaseModel):
    flags: Dict[str, bool] = {}


@router.post("/api/access/flags")
def admin_set_flags(
    body: FlagsRequest, request: Request, caller: Any = Depends(_require_admin_or_local_owner)
) -> Dict[str, Any]:
    return {"flags": access_keys.set_flags(body.flags, actor=_actor_label(caller, request))}


@router.get("/api/access/audit")
def admin_read_audit(
    limit: int = 100, _caller: Any = Depends(_require_admin_or_local_owner)
) -> Dict[str, Any]:
    return {"audit": access_keys.read_audit(limit)}
