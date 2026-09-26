"""HTTP routes for computer control (contract §4.2).

``state`` and ``stop`` are open to the chat gate — anyone who can talk to Nyx can
see that it is driving the mouse and can stop it. Seeing the screen and turning
the overlay off need the owner: a screenshot of this PC is not for other users.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from server_auth import RequireChat

router = APIRouter()


def _owner(request: Request) -> Any:
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


@router.get("/api/computer/state")
def computer_state(_user=RequireChat) -> Dict[str, Any]:
    import computer_control

    return computer_control.state()


@router.get("/api/computer/screenshot")
def computer_screenshot(max_width: int = 1280, cursor: int = 1, _owner_user=Depends(_owner)) -> Response:
    import computer_control

    if not computer_control.IS_WINDOWS:
        raise HTTPException(status_code=501, detail="Computer control works on Windows only.")
    try:
        data, _scale, _origin = computer_control.screenshot_jpeg(max_width=max(320, min(3840, max_width)), cursor=bool(cursor))
    except Exception as error:  # noqa: BLE001 - locked screen, secure desktop
        raise HTTPException(status_code=503, detail=f"Could not capture the screen: {error}") from error
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


class OverlayRequest(BaseModel):
    enabled: bool


@router.post("/api/computer/overlay")
def computer_overlay(body: OverlayRequest, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import computer_control

    return computer_control.set_overlay(body.enabled)


@router.post("/api/computer/stop")
def computer_stop(_user=RequireChat) -> Dict[str, Any]:
    import computer_control

    computer_control.abort("Stop pressed")
    return computer_control.state()
