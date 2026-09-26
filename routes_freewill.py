"""HTTP routes for the Free Will tab (Request R15).

All owner-only. The conversation itself goes through ``/api/chat/stream`` with chat id ``__freewill__``, where
``routes_live.start_turn`` refuses it until the owner has allowed Free Will and puts every tool behind its guard.
Hosted builds do not have these routes (``deploy_mode.HOSTED_BLOCKED_PREFIXES``).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


def _owner_dep():
    def dependency(http_request: Request, authorization: Optional[str] = Header(default=None)) -> Any:
        from server import require_local_owner

        return require_local_owner(http_request, authorization)
    return Depends(dependency)


Owner = _owner_dep()


class DecideBody(BaseModel):
    allow: bool


class PauseBody(BaseModel):
    paused: bool


def _service() -> Any:
    import freewill
    import server

    return server._get_service(freewill.CHAT_KEY)


@router.get("/api/freewill")
def freewill_overview(_owner=Owner) -> Dict[str, Any]:
    import freewill

    current = freewill.state()
    return {"state": current, "opinions": freewill.opinions(),
            "messages": freewill.history(_service()) if current["allowed"] else [],
            "chat_id": freewill.CHAT_KEY,
            "guard": {"categories": sorted(freewill.ALLOWED_CATEGORIES), "tools": sorted(freewill.ALLOWED_TOOLS),
                      "blocked": sorted(freewill.BLOCKED_TOOLS)}}


@router.post("/api/freewill/decide")
def freewill_decide(body: DecideBody, owner=Owner) -> Dict[str, Any]:
    import freewill

    return {"state": freewill.decide(body.allow, by=str(getattr(owner, "email", "") or "Owner"))}


@router.post("/api/freewill/pause")
def freewill_pause(body: PauseBody, _owner=Owner) -> Dict[str, Any]:
    import freewill

    try:
        return {"state": freewill.set_paused(body.paused)}
    except freewill.FreeWillError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.delete("/api/freewill/opinions/{opinion_id}")
def freewill_erase(opinion_id: str, _owner=Owner) -> Dict[str, Any]:
    import freewill

    if not freewill.erase(opinion_id):
        raise HTTPException(status_code=404, detail="That opinion is already gone.")
    return {"opinions": freewill.opinions()}


@router.delete("/api/freewill/opinions")
def freewill_erase_all(_owner=Owner) -> Dict[str, Any]:
    import freewill

    return {"erased": freewill.erase_all(), "opinions": []}


@router.post("/api/freewill/forget-chat")
def freewill_forget_chat(_owner=Owner) -> Dict[str, Any]:
    """Start the Free Will conversation over. Its opinions stay unless erased separately."""
    service = _service()
    service.clear_history()
    return {"messages": []}
