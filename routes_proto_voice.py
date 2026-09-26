"""HTTP routes for Proto Voice (Project Null N92).

Owner-only, all of it: this is the microphone that may open programs, lock the
screen and stop Nyx. An invited account never gets near it. `POST /act` is the
one the browser calls for every finished sentence while Proto Voice is on.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


def _owner(request: Request) -> None:
    import server

    server.require_local_owner(request, request.headers.get("authorization"))


@router.get("/api/proto-voice")
def proto_state(request: Request) -> Dict[str, Any]:
    _owner(request)
    import proto_voice

    return proto_voice.state()


class ProtoSettings(BaseModel):
    allowed: Optional[bool] = None
    standby: Optional[bool] = None
    wake_words: Optional[List[str]] = None
    speak_actions: Optional[bool] = None
    confirm_power: Optional[bool] = None
    agents: Optional[bool] = None


@router.put("/api/proto-voice")
def set_proto(body: ProtoSettings, request: Request) -> Dict[str, Any]:
    _owner(request)
    import proto_voice

    changes = body.model_dump(exclude_none=True)
    words = changes.get("wake_words")
    if words is not None:
        cleaned = [w.strip().lower() for w in words if isinstance(w, str) and 2 <= len(w.strip()) <= 24][:6]
        if not cleaned:
            raise HTTPException(status_code=400, detail="Give at least one word it should answer to.")
        changes["wake_words"] = cleaned
    return {"settings": proto_voice.update_settings(**changes)}


class ActBody(BaseModel):
    text: str = ""
    session_id: str = "default"
    chat_id: str = ""
    #: The UI's tabs, [{"id", "label"}], so "open the finance tab" finds the real one.
    tabs: List[dict] = []


def _tabs_here() -> List[dict]:
    """Every tab that exists, so "open the finance tab" works without the browser listing them."""
    tabs: List[dict] = []
    try:
        from landscape_tools import CORE_TABS

        tabs += [{"id": key, "label": label} for key, label in CORE_TABS.items()]
    except Exception:  # pragma: no cover
        pass
    try:
        from dynamic_tabs import TAB_STORE

        tabs += [{"id": str(t.get("id")), "label": str(t.get("label") or t.get("id"))}
                 for t in TAB_STORE.list_tabs()]
    except Exception:  # pragma: no cover
        pass
    return tabs


@router.post("/api/proto-voice/act")
def proto_act(body: ActBody, request: Request) -> Dict[str, Any]:
    """One heard sentence: act on it, ask about it, refuse it, or send it to the chat."""
    _owner(request)
    import proto_voice

    tabs = body.tabs[:60] or _tabs_here()
    return proto_voice.handle(body.text, session_id=body.session_id or "default",
                              tabs=tabs, chat_id=body.chat_id)


class ConfirmBody(BaseModel):
    token: str
    session_id: str = "default"
    yes: bool = True


@router.post("/api/proto-voice/confirm")
def proto_confirm(body: ConfirmBody, request: Request) -> Dict[str, Any]:
    """Yes or no to the thing it just asked about (the spoken "yes" goes through /act)."""
    _owner(request)
    import proto_voice

    return proto_voice.confirm(body.token, session_id=body.session_id or "default", yes=body.yes)


class SimulateBody(BaseModel):
    text: str = ""


@router.post("/api/proto-voice/simulate")
def proto_simulate(body: SimulateBody, request: Request) -> Dict[str, Any]:
    """What it *would* do, doing none of it."""
    _owner(request)
    import proto_voice

    return {"plan": proto_voice.describe_plan(body.text)}
