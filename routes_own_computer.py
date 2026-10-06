"""HTTP routes for Nyx's own computer (Update 1, U49) — the Nyx's Computer tab.

Everything here is the owner's: where Nyx may work, its sandbox, the live view of it, and the key for a Cua Cloud
sandbox. The key goes into ``secret_store`` and is never sent back — the status only says whether one is saved.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

router = APIRouter()


def _owner(request: Request) -> Any:
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


def _fail(error: Exception) -> HTTPException:
    import own_computer

    if isinstance(error, own_computer.OwnComputerError):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=500, detail=f"{type(error).__name__}: {error}")


@router.get("/api/own-computer")
def own_computer_status(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import own_computer

    return own_computer.status()


class Settings(BaseModel):
    my_screen: Optional[str] = None
    provider: Optional[str] = None
    image: Optional[str] = None
    cloud_name: Optional[str] = None
    grant_minutes: Optional[int] = None


@router.post("/api/own-computer/settings")
def own_computer_settings(body: Settings, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import own_computer

    try:
        return own_computer.save(**body.model_dump(exclude_none=True))
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error


class KeyBody(BaseModel):
    key: str = ""


@router.post("/api/own-computer/key")
def own_computer_key(body: KeyBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    """Save (or, with an empty key, forget) the Cua Cloud API key. Only "saved: yes/no" ever comes back."""
    import own_computer

    return own_computer.set_cloud_key(body.key)


@router.post("/api/own-computer/setup")
def own_computer_setup(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    """Install the Cua Computer SDK into Nyx's own Python — the one part Nyx can set up by itself."""
    import own_computer

    if not own_computer.sdk_installed():
        done = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "cua-computer"],
                              capture_output=True, text=True, timeout=600,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if done.returncode != 0:
            raise HTTPException(status_code=409, detail="Could not install cua-computer: " + (done.stderr or done.stdout)[-600:])
        import importlib

        importlib.invalidate_caches()
    return own_computer.status()


@router.post("/api/own-computer/start")
def own_computer_start(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import own_computer

    try:
        own_computer.COMPUTER.start()
        return own_computer.status()
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error


@router.post("/api/own-computer/stop")
def own_computer_stop(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import own_computer

    own_computer.COMPUTER.stop()
    return own_computer.status()


@router.post("/api/own-computer/grant/revoke")
def own_computer_revoke(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    """Take back a "yes, use my screen" before it runs out."""
    import own_computer

    return own_computer.revoke_grant()


@router.get("/api/own-computer/screen")
def own_computer_screen(_owner_user=Depends(_owner)) -> Response:
    """The live view: what is on Nyx's computer now."""
    import own_computer

    if own_computer.COMPUTER.state != "on":
        raise HTTPException(status_code=409, detail="Nyx's computer is off.")
    try:
        data = own_computer.COMPUTER.screenshot()
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "no-store"})


class ActBody(BaseModel):
    kind: str
    x: Optional[float] = None
    y: Optional[float] = None
    text: str = ""
    button: str = "left"
    double: bool = False
    amount: int = -3


@router.post("/api/own-computer/act")
def own_computer_act(body: ActBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    """The owner taking a turn on Nyx's computer from the live view: click, type, keys, scroll, open."""
    import own_computer

    computer = own_computer.COMPUTER
    if computer.state != "on":
        raise HTTPException(status_code=409, detail="Nyx's computer is off.")
    try:
        if body.kind == "click" and body.x is not None and body.y is not None:
            said = computer.click(int(body.x), int(body.y), body.button or "left", body.double)
        elif body.kind == "type":
            said = computer.type_text(body.text)
        elif body.kind == "keys":
            said = computer.keys(body.text)
        elif body.kind == "scroll":
            said = computer.scroll(body.amount)
        elif body.kind == "open":
            said = computer.open(body.text)
        else:
            raise HTTPException(status_code=400, detail="Use click (with x and y), type, keys, scroll or open.")
    except HTTPException:
        raise
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error
    return {"done": said, "computer": computer.view()}
