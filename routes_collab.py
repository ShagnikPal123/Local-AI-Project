"""HTTP routes for Collab (Request K): the tester's side of sending changes to GitHub for review.

Reading the shared feed is an ordinary signed-in action. Everything that looks at this install's files or sends
them off the PC is an owner action on that install (a tester owns their own Nyx): admin once claimed,
loopback-only before — the same gate as the Code and Improve tabs.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from server_auth import RequireChat

router = APIRouter()


def _owner(request: Request) -> Any:
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


Owner = Depends(_owner)


def _call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    import beta_collab

    try:
        return fn(*args, **kwargs)
    except beta_collab.CollabError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


class ConfigBody(BaseModel):
    site_url: str = ""


class SendBody(BaseModel):
    ids: List[str] = Field(default_factory=list)
    title: str
    description: str = ""
    kind: str = ""


class PreviewBody(BaseModel):
    ids: List[str] = Field(default_factory=list)


class FeedbackBody(BaseModel):
    title: str
    description: str = ""


@router.get("/api/collab/status")
def collab_status(_owner_user=Owner) -> Dict[str, Any]:
    import beta_collab

    settings = beta_collab.config()
    return {"site_url": settings["site_url"], "collab_url": settings["site_url"] + "/collab/", "identity": beta_collab.identity(),
            "sent": list(reversed(settings["sent"]))[:20]}


@router.put("/api/collab/config")
def collab_config(body: ConfigBody, _owner_user=Owner) -> Dict[str, Any]:
    import beta_collab

    return _call(beta_collab.save_config, site_url=body.site_url)


@router.get("/api/collab/candidates")
def collab_candidates(_owner_user=Owner) -> Dict[str, Any]:
    import beta_collab

    return {"candidates": beta_collab.candidates()}


@router.post("/api/collab/preview")
def collab_preview(body: PreviewBody, _owner_user=Owner) -> Dict[str, Any]:
    """Exactly which files would leave this PC, and whether any look like secrets — before Send."""
    import beta_collab

    result = _call(beta_collab.preview, body.ids)
    result.pop("_files", None)
    return result


@router.post("/api/collab/send")
def collab_send(body: SendBody, _owner_user=Owner) -> Dict[str, Any]:
    import beta_collab

    return _call(beta_collab.send, body.ids, body.title, body.description, body.kind)


@router.post("/api/collab/feedback")
def collab_feedback(body: FeedbackBody, _owner_user=Owner) -> Dict[str, Any]:
    import beta_collab

    return _call(beta_collab.send_feedback, body.title, body.description)


@router.get("/api/collab/feed")
def collab_feed(force: bool = False, _user=RequireChat) -> Dict[str, Any]:
    import beta_collab

    return _call(beta_collab.feed, force)
