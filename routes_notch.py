"""The desktop notch's routes (notch.py): the page reports voice state; the owner turns the notch on and off."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel

from server_auth import RequireChat

router = APIRouter()


class NotchState(BaseModel):
    state: str = "idle"
    text: str = ""
    voice: bool = False


@router.post("/api/notch/state")
def notch_state(body: NotchState, _user=RequireChat) -> Dict[str, Any]:
    import notch

    notch.set_state(body.state, body.text, body.voice)
    return {"ok": True}


@router.get("/api/notch")
def notch_status(_user=RequireChat) -> Dict[str, Any]:
    import notch

    return notch.status()


@router.post("/api/notch/start")
def notch_start(_user=RequireChat) -> Dict[str, Any]:
    import notch

    return notch.start()


@router.post("/api/notch/stop")
def notch_stop(_user=RequireChat) -> Dict[str, Any]:
    import notch

    return notch.stop()
