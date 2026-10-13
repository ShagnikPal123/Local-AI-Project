"""The desktop notch's routes (notch.py): the page reports voice state; the owner turns the notch on and off."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Request
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
def notch_start(request: Request, _user=RequireChat) -> Dict[str, Any]:
    """Open the desktop notch; it signs in with the session of whoever turned it on."""
    import notch

    header = request.headers.get("authorization") or ""
    return notch.start(token=header.split(" ", 1)[1] if header.lower().startswith("bearer ") else "")


@router.post("/api/notch/stop")
def notch_stop(_user=RequireChat) -> Dict[str, Any]:
    import notch

    return notch.stop()



class OpenApp(BaseModel):
    tab: str = "chat"


@router.post("/api/notch/open-app")
def notch_open_app(body: OpenApp, _user=RequireChat) -> Dict[str, Any]:
    """The notch's Back-to-chat and Open-Equalize buttons: the open app page switches tab; with none open, a browser
    opens on the app."""
    import notch

    return notch.open_app(body.tab)


@router.get("/notch", include_in_schema=False)
def notch_page() -> Any:
    """The Equalize notch's page, loaded by the desktop window (notch_window.py)."""
    from pathlib import Path

    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    page = Path(__file__).resolve().parent / "frontend" / "nyx-pulse" / "dist" / "notch.html"
    if not page.is_file():
        raise HTTPException(status_code=404, detail="Build the frontend first (npm run build).")
    return FileResponse(page, headers={"Cache-Control": "no-cache"})
