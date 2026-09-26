"""HTTP routes for the Apply tab (Request R16).

Everything here plans or makes changes to this install of Nyx, so every route needs the owner (loopback on an unclaimed
install, an owner/admin session once claimed). Hosted builds do not have these routes
(``deploy_mode.HOSTED_BLOCKED_PREFIXES``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()


def _owner_dep():
    def dependency(http_request: Request, authorization: Optional[str] = Header(default=None)) -> Any:
        from server import require_local_owner

        return require_local_owner(http_request, authorization)
    return Depends(dependency)


Owner = _owner_dep()


def _who(user: Any) -> str:
    return str(getattr(user, "email", "") or getattr(user, "name", "") or "Owner")


def _call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    import apply_engine

    try:
        return fn(*args, **kwargs)
    except apply_engine.ApplyError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


class StartBody(BaseModel):
    prompt: str = ""
    uploads: List[str] = Field(default_factory=list)
    links: List[str] = Field(default_factory=list)
    search: bool = True


@router.get("/api/apply")
def apply_overview(_owner=Owner) -> Dict[str, Any]:
    import apply_engine

    return apply_engine.jobs().overview()


@router.post("/api/apply")
def apply_start(body: StartBody, owner=Owner) -> Dict[str, Any]:
    import apply_engine

    return _call(apply_engine.jobs().start, body.prompt, uploads=body.uploads, links=body.links, search=body.search,
                 by=_who(owner))


@router.get("/api/apply/rebuild")
def apply_build_status(_owner=Owner) -> Dict[str, Any]:
    import apply_engine

    return apply_engine.jobs().build_status()


@router.post("/api/apply/rebuild")
def apply_rebuild(owner=Owner) -> Dict[str, Any]:
    import apply_engine

    return _call(apply_engine.jobs().rebuild, by=_who(owner))


@router.get("/api/apply/{job_id}")
def apply_job(job_id: str, _owner=Owner) -> Dict[str, Any]:
    import apply_engine

    return _call(apply_engine.jobs().get, job_id)


@router.post("/api/apply/{job_id}/cancel")
def apply_cancel(job_id: str, _owner=Owner) -> Dict[str, Any]:
    import apply_engine

    return _call(apply_engine.jobs().cancel, job_id)


@router.post("/api/apply/{job_id}/changes/{index}/{action}")
def apply_decide(job_id: str, index: int, action: str, owner=Owner) -> Dict[str, Any]:
    import apply_engine

    return _call(apply_engine.jobs().decide, job_id, index, action, by=_who(owner))
