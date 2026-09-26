"""HTTP surface for the Command Zone tab (``command_zone.py``).

Included by ``server._include_routers``. Every route sits behind the deny-by-default session
middleware once the install is claimed, and ``/api/command-zone`` is in the auth test lists.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import command_zone
from server_auth import RequireChat

router = APIRouter()

_OWNER_ROLES = {"owner", "admin", "local"}


def _role(user: Any) -> str:
    role = getattr(user, "role", None)
    return getattr(role, "value", None) or (str(role) if role else "local")


def _dispatch(message: str, user: Any) -> Dict[str, Any]:
    """Send one message to the Command Zone chat as a normal turn."""
    import server
    from routes_live import StreamRequest, start_turn

    try:
        chat_id = command_zone.ensure_chat(server._shared_chat_store())
    except RuntimeError as error:  # the chat limit
        raise HTTPException(status_code=400, detail=f"{error} The Command Zone needs a chat of its own.") from error
    turn_id, chat_id = start_turn(StreamRequest(message=message, chat_id=chat_id), user)
    return {"turn_id": turn_id, "chat_id": chat_id}


def _inbox(user: Any) -> Dict[str, Any]:
    from permissions import pending_approvals

    pending = command_zone.INBOX.pending()
    tabs = [i for i in pending if i["kind"] == "tab"]
    predicted = command_zone.predicted_tab()
    if predicted:
        tabs.append(predicted)
    approvals = pending_approvals()
    elsewhere = command_zone.elsewhere(owner=_role(user) in _OWNER_ROLES)
    ideas = [i for i in pending if i["kind"] == "idea"]
    return {
        "approvals": approvals,
        "ideas": ideas,
        "tabs": tabs,
        "elsewhere": elsewhere,
        "recent": command_zone.INBOX.recent(8),
        "waiting": len(approvals) + len(ideas) + len(tabs) + sum(e["count"] for e in elsewhere),
    }


@router.get("/api/command-zone")
def command_zone_state(range: str = "all", user=RequireChat) -> Dict[str, Any]:  # noqa: A002 - query name
    """Everything the Command Zone shows: usage, tabs, and what is waiting for the owner."""
    return {
        "usage": command_zone.USAGE.summary(range),
        "tabs": command_zone.tab_usage(),
        "inbox": _inbox(user),
        "chat_id": command_zone.INBOX.chat_id,
    }


@router.get("/api/command-zone/glance")
def command_zone_glance(user=RequireChat) -> Dict[str, Any]:
    """The two numbers the chat bar shows: waiting for the owner, and turns running now."""
    from turn_registry import TURNS

    return {"waiting": _inbox(user)["waiting"], "working": len(TURNS.active(include_recent=False))}


class SendRequest(BaseModel):
    message: str = ""


@router.post("/api/command-zone/send")
def command_zone_send(body: SendRequest, user=RequireChat) -> Dict[str, Any]:
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Type what you want the team to do.")
    return _dispatch(message[:4000], user)


class AnswerRequest(BaseModel):
    approve: bool


@router.post("/api/command-zone/items/{item_id}")
def command_zone_answer(item_id: str, body: AnswerRequest, user=RequireChat) -> Dict[str, Any]:
    """Approve or dismiss an idea or a tab suggestion."""
    try:
        item = command_zone.resolve(item_id, body.approve, dispatch=lambda message: _dispatch(message, user))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="That suggestion is gone — it may have been answered already.") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"item": item}


@router.post("/api/command-zone/items/{item_id}/restore")
def command_zone_restore(item_id: str, _user=RequireChat) -> Dict[str, Any]:
    """Undo a Dismiss."""
    try:
        return {"item": command_zone.restore(item_id)}
    except KeyError as error:
        raise HTTPException(status_code=404, detail="That suggestion is no longer kept.") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
