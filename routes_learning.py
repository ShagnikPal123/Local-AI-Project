"""HTTP surface for the learning system: cross-visit memory, feedback, and the
response cache (OVERHAUL_CONTRACTS.md round 2, Coder B).

Its own router, included automatically by ``server.py``'s ``_include_routers``
loop (it is already in that module's list — nothing to wire up there). Every
route here sits behind the deny-by-default session middleware once the
install is claimed (``server_auth.enforce_session_middleware``); the two
owner-only actions additionally call ``server.require_local_owner`` directly
inside the handler, the same pattern ``routes_live.set_permissions`` already
uses — a lazy import so this module never imports ``server`` (and therefore
never risks a circular import) until a request actually needs it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from client_state import ClientStateError, forget, get_state, patch_state, put_state
from learning import LEARNER
from response_cache import RESPONSE_CACHE
from server_auth import RequireChat

router = APIRouter()


def _client_id(request: Request) -> str:
    """The middleware's id when installed, else the raw cookie, else a clear 400.

    A 400 here (not 401/403) means "the client forgot to send the cookie it
    was given" — a client bug, not an authorisation failure.
    """
    client_id = getattr(request.state, "nyx_client", None)
    if not client_id:
        client_id = request.cookies.get("nyx_client")
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="No nyx_client cookie present. Is ClientCookieMiddleware installed?",
        )
    return client_id


def _account_of(user: Any) -> Optional[str]:
    return getattr(user, "email", None) or None


# ---------------------------------------------------------------------------
# Client-side persistence ("leave the site and come back")
# ---------------------------------------------------------------------------


class PutStateRequest(BaseModel):
    state: Dict[str, Any] = {}


class PatchStateRequest(BaseModel):
    patch: Dict[str, Any] = {}


@router.get("/api/client/state")
def read_client_state(request: Request, user=RequireChat) -> Dict[str, Any]:
    client_id = _client_id(request)
    try:
        return {"state": get_state(client_id, account=_account_of(user))}
    except ClientStateError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.put("/api/client/state")
def write_client_state(body: PutStateRequest, request: Request, user=RequireChat) -> Dict[str, Any]:
    client_id = _client_id(request)
    try:
        state = put_state(client_id, body.state, account=_account_of(user))
    except ClientStateError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, "state": state}


@router.patch("/api/client/state")
def patch_client_state(body: PatchStateRequest, request: Request, user=RequireChat) -> Dict[str, Any]:
    client_id = _client_id(request)
    try:
        state = patch_state(client_id, body.patch, account=_account_of(user))
    except ClientStateError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, "state": state}


@router.delete("/api/client/state")
def delete_client_state(request: Request, _user=RequireChat) -> Dict[str, Any]:
    client_id = _client_id(request)
    forget(client_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


class FeedbackRequest(BaseModel):
    turn_id: Optional[str] = None
    chat_id: Optional[str] = None
    rating: int
    comment: str = ""


@router.post("/api/feedback")
def submit_feedback(body: FeedbackRequest, _user=RequireChat) -> Dict[str, Any]:
    if body.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating must be 1 or -1")
    LEARNER.feedback(body.turn_id or "", body.rating, comment=body.comment, chat_id=body.chat_id or "")
    try:
        import prompt_optimizer

        # A 👎 on a turn whose request was rewritten teaches the optimizer's sensor too.
        prompt_optimizer.OPTIMIZER.feedback(body.turn_id or "", body.rating)
    except Exception:  # pragma: no cover - optional
        pass
    try:
        import nyx_core

        nyx_core.CORE.feedback(body.turn_id or "", body.rating)
    except Exception:  # pragma: no cover - optional
        pass
    try:
        from identity0 import experience as kahuna_experience

        # Big Kahuna credits (or debits) the member that led this turn.
        kahuna_experience.on_feedback(body.turn_id or "", body.rating)
    except Exception:  # pragma: no cover - optional
        pass
    invalidated = 0
    if body.rating == -1 and body.turn_id:
        # A disliked answer must stop being served from cache immediately —
        # otherwise the next person to ask the same question gets the exact
        # reply that was just marked wrong.
        invalidated = RESPONSE_CACHE.invalidate_turn(body.turn_id)
    return {"ok": True, "cache_invalidated": invalidated}


# ---------------------------------------------------------------------------
# Learning introspection
# ---------------------------------------------------------------------------


@router.get("/api/learning/stats")
def learning_stats(_user=RequireChat) -> Dict[str, Any]:
    return LEARNER.stats()


@router.get("/api/learning/suggest")
def learning_suggest(q: str = "", _user=RequireChat) -> Dict[str, Any]:
    return LEARNER.suggest(q)


class ResetRequest(BaseModel):
    scope: str = "all"


@router.post("/api/learning/reset")
def learning_reset(body: ResetRequest, request: Request) -> Dict[str, Any]:
    import server

    server.require_local_owner(request, request.headers.get("authorization"))
    try:
        LEARNER.reset(body.scope)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, "scope": body.scope}


# ---------------------------------------------------------------------------
# Response cache introspection
# ---------------------------------------------------------------------------


@router.get("/api/cache/stats")
def cache_stats(_user=RequireChat) -> Dict[str, Any]:
    return RESPONSE_CACHE.stats()


@router.post("/api/cache/clear")
def cache_clear(request: Request) -> Dict[str, Any]:
    import server

    server.require_local_owner(request, request.headers.get("authorization"))
    RESPONSE_CACHE.clear()
    return {"ok": True}
