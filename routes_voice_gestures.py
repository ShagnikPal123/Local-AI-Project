"""HTTP routes for Clap — the sounds Nyx answers to (Project Null N86).

Kept out of ``routes_voice.py`` (speech and voices) so the two can be worked on
at the same time. Everything is behind the session middleware; teaching a sound
and changing what it does are the owner's, like every other setting.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server_auth import RequireChat

router = APIRouter()


class GestureBody(BaseModel):
    name: str = ""
    kind: str = "taught"
    enabled: bool = True
    when: List[str] = []
    action: str = "say"
    #: What Nyx says back when it hears this.
    say: str = ""
    #: For action "command": what to send to the chat.
    text: str = ""
    #: A taught sound's shape — frames of 12 numbers, never audio.
    template: Optional[List[List[float]]] = None


class GestureSettings(BaseModel):
    enabled: Optional[bool] = None
    sensitivity: Optional[float] = None
    greeting: Optional[Dict[str, Any]] = None


@router.get("/api/voice/gestures")
def list_gestures(_user=RequireChat) -> Dict[str, Any]:
    """Every sound Nyx listens for, and the greeting it says when listening starts."""
    import voice_gestures

    return voice_gestures.state()


@router.put("/api/voice/gestures/settings")
def update_settings(body: GestureSettings, _user=RequireChat) -> Dict[str, Any]:
    import voice_gestures

    return voice_gestures.settings(body.model_dump(exclude_none=True))


@router.post("/api/voice/gestures")
def add_gesture(body: GestureBody, _user=RequireChat) -> Dict[str, Any]:
    import voice_gestures

    try:
        return {"gesture": voice_gestures.add(body.model_dump(exclude_none=True))}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.patch("/api/voice/gestures/{gesture_id}")
def update_gesture(gesture_id: str, body: GestureBody, _user=RequireChat) -> Dict[str, Any]:
    import voice_gestures

    try:
        return {"gesture": voice_gestures.update(gesture_id, body.model_dump(exclude_none=True))}
    except KeyError as error:
        raise HTTPException(status_code=404, detail="That sound is no longer there.") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/api/voice/gestures/{gesture_id}")
def delete_gesture(gesture_id: str, _user=RequireChat) -> Dict[str, Any]:
    import voice_gestures

    if not voice_gestures.remove(gesture_id):
        raise HTTPException(status_code=404, detail="That sound is no longer there.")
    return voice_gestures.state()


@router.post("/api/voice/gestures/{gesture_id}/heard")
def gesture_heard(gesture_id: str, _user=RequireChat) -> Dict[str, Any]:
    """The browser heard it: count it, and say what Nyx does about it."""
    import voice_gestures

    try:
        return voice_gestures.heard(gesture_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="That sound is no longer there.") from error


@router.get("/api/voice/greeting")
def voice_greeting(first: bool = False, _user=RequireChat) -> Dict[str, Any]:
    """What to say when listening starts — in every mode (N86)."""
    import voice_gestures

    return {"text": voice_gestures.greeting(first_today=first)}
