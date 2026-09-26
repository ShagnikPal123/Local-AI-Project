"""HTTP routes for the Screen Share tab (Request R10).

Everything here shows or touches the owner's screen, so every route needs the owner (loopback on an unclaimed
install, an owner/admin session once claimed) — except Stop, which anyone who can talk to Nyx may press, like the
computer-control Stop. Hosted builds do not have these routes (``deploy_mode.HOSTED_BLOCKED_PREFIXES``).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from server_auth import RequireChat

router = APIRouter()


def _owner_dep():
    def dependency(http_request: Request, authorization: Optional[str] = Header(default=None)) -> Any:
        from server import require_local_owner

        return require_local_owner(http_request, authorization)
    return Depends(dependency)


Owner = _owner_dep()


def _call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    import screen_share

    try:
        return fn(*args, **kwargs)
    except screen_share.NeedsCloud as error:
        # The page shows the "allow the online model" card for this one.
        return JSONResponse(status_code=409, content={"detail": str(error), "code": "needs_cloud"})
    except screen_share.ScreenShareError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


class StartBody(BaseModel):
    source: Dict[str, Any] = Field(default_factory=dict)
    pace: str = "show"


class AskBody(BaseModel):
    question: str = ""
    next: bool = False


class PaceBody(BaseModel):
    pace: str


class CloudBody(BaseModel):
    allow: bool


@router.get("/api/screen")
def screen_state(_owner=Owner) -> Dict[str, Any]:
    from screen_share import SHARE

    return SHARE.state()


@router.get("/api/screen/sources")
def screen_sources(_owner=Owner) -> Dict[str, Any]:
    from screen_share import SHARE

    return _call(SHARE.sources)


@router.post("/api/screen/start")
def screen_start(body: StartBody, _owner=Owner) -> Any:
    from screen_share import SHARE

    return _call(SHARE.start, body.source, body.pace)


@router.post("/api/screen/stop")
def screen_stop(_user=RequireChat) -> Dict[str, Any]:
    from screen_share import SHARE

    return SHARE.stop()


@router.get("/api/screen/frame")
def screen_frame(max_width: int = 1280, _owner=Owner) -> Response:
    from screen_share import SHARE

    result = _call(SHARE.frame, max_width)
    if isinstance(result, JSONResponse):
        return result
    return Response(content=result, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/api/screen/ask")
def screen_ask(body: AskBody, _owner=Owner) -> Any:
    from screen_share import SHARE

    return _call(SHARE.ask, body.question, body.next)


@router.post("/api/screen/pace")
def screen_pace(body: PaceBody, _owner=Owner) -> Any:
    from screen_share import SHARE

    return _call(SHARE.set_pace, body.pace)


@router.post("/api/screen/cloud")
def screen_cloud(body: CloudBody, _owner=Owner) -> Any:
    from screen_share import SHARE

    return _call(SHARE.set_cloud, body.allow)


@router.post("/api/screen/steps/{step_id}/{action}")
def screen_step(step_id: str, action: str, _owner=Owner) -> Any:
    from screen_share import SHARE

    return _call(SHARE.act, step_id, action)
