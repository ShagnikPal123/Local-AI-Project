"""The desktop notch's routes (notch.py): the page reports voice state; the owner turns the notch on and off."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
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

    from fastapi.responses import FileResponse

    page = Path(__file__).resolve().parent / "frontend" / "nyx-pulse" / "dist" / "notch.html"
    if not page.is_file():
        raise HTTPException(status_code=404, detail="Build the frontend first (npm run build).")
    return FileResponse(page, headers={"Cache-Control": "no-cache"})


# ── Controls, launchers and the home view (notch_controls.py) ────────────────
# Running anything on the PC, and changing what the notch can run, is the owner's (an invited tester's session can
# read the notch but not open a cmd window on the owner's machine).


def _owner(request: Request) -> Any:
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


@router.get("/api/notch/controls")
def notch_controls(_user=RequireChat) -> Dict[str, Any]:
    import notch_controls as nc

    system = [{"id": key, "label": label, "icon": icon} for key, (label, icon, _how) in nc.SYSTEM.items()]
    return {**nc.settings(), "available": system, "views": list(nc.VIEWS)}


class ControlsChange(BaseModel):
    system: Optional[List[str]] = None
    launchers: Optional[List[Dict[str, Any]]] = None
    home: Optional[Dict[str, Any]] = None


@router.post("/api/notch/controls")
def notch_controls_save(body: ControlsChange, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import notch_controls as nc

    return nc.update(body.model_dump(exclude_none=True))


class LauncherBody(BaseModel):
    name: str
    kind: str = "app"
    target: str = ""
    command: str = ""
    folder: str = ""


@router.post("/api/notch/launchers")
def notch_launcher_add(body: LauncherBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import notch_controls as nc

    try:
        return nc.add_launcher(body.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/api/notch/launchers/{launcher_id}")
def notch_launcher_remove(launcher_id: str, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import notch_controls as nc

    return nc.remove_launcher(launcher_id)


class SuggestBody(BaseModel):
    name: str


@router.post("/api/notch/launchers/suggest")
def notch_launcher_suggest(body: SuggestBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    """"If something is not added … the AI can figure out the link": an app, a known site, a domain or a search."""
    import notch_controls as nc

    try:
        return nc.suggest(body.name)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


class RunBody(BaseModel):
    id: str
    kind: str = "system"  # system | launcher


@router.post("/api/notch/run")
def notch_run(body: RunBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import notch_controls as nc

    return nc.run_launcher(body.id) if body.kind == "launcher" else nc.run_system(body.id)


class ViewBody(BaseModel):
    view: str


@router.post("/api/notch/home/default")
def notch_home_default(body: ViewBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import notch_controls as nc

    try:
        return nc.set_default(body.view)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/api/notch/home/{view}")
def notch_home_data(view: str, _user=RequireChat) -> Dict[str, Any]:
    import notch_controls as nc

    return nc.home_data(view)


@router.get("/api/notch/waiting")
def notch_waiting(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    """What needs the owner (approvals, trades, Claude Code, question cards); a new one pops the notch open."""
    import notch

    return {"items": notch.waiting()}
