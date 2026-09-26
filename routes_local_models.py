"""Local models on this PC and the model finder, at the bottom of Keys & Models (Request R12–R13).

Every route here changes or reveals this machine's setup — what is installed, what is on its disks, what gets
downloaded — so all of them are owner actions (owner/admin session, or loopback before the install is claimed), and
hosted builds do not have them at all (``deploy_mode.HOSTED_BLOCKED_PREFIXES``).
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


def _call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    import local_models

    try:
        return fn(*args, **kwargs)
    except local_models.LocalModelError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


class PullBody(BaseModel):
    name: str


class AddFileBody(BaseModel):
    path: str
    name: str = ""


class UseBody(BaseModel):
    name: str
    role: str = ""


class ScanBody(BaseModel):
    folders: List[str] = Field(default_factory=list)
    include_other: bool = False


class FindBody(BaseModel):
    query: str = ""
    deep: bool = True


@router.get("/api/local-models")
def local_status(_owner=Owner) -> Dict[str, Any]:
    import local_models

    return {"status": local_models.status(), "jobs": local_models.jobs(), "servers": local_models.probe_servers()}


@router.post("/api/local-models/scan")
def local_scan(body: ScanBody, _owner=Owner) -> Dict[str, Any]:
    import local_models

    return local_models.scan(body.folders, include_other=body.include_other)


@router.post("/api/local-models/pull")
def local_pull(body: PullBody, _owner=Owner) -> Dict[str, Any]:
    import local_models

    return {"job": _call(local_models.pull, body.name)}


@router.post("/api/local-models/add-file")
def local_add_file(body: AddFileBody, _owner=Owner) -> Dict[str, Any]:
    import local_models

    return {"job": _call(local_models.add_file, body.path, body.name)}


@router.post("/api/local-models/install")
def local_install(_owner=Owner) -> Dict[str, Any]:
    import local_models

    return {"job": _call(local_models.install_ollama)}


@router.post("/api/local-models/use")
def local_use(body: UseBody, _owner=Owner) -> Dict[str, Any]:
    import local_models

    return _call(local_models.use, body.name, body.role)


@router.delete("/api/local-models/{name:path}")
def local_remove(name: str, _owner=Owner) -> Dict[str, Any]:
    import local_models

    return _call(local_models.remove, name)


# --- model finder ---------------------------------------------------------------------------------


@router.get("/api/model-finder")
def finder_state(_owner=Owner) -> Dict[str, Any]:
    import model_finder

    return {"catalog": model_finder.from_catalog(), "job": model_finder.latest(), "configured": model_finder.configured()}


@router.post("/api/model-finder/search")
def finder_search(body: FindBody, _owner=Owner) -> Dict[str, Any]:
    import model_finder

    return {"job": model_finder.search(body.query, deep=body.deep)}


@router.get("/api/model-finder/{job_id}")
def finder_job(job_id: str, _owner=Owner) -> Dict[str, Any]:
    import model_finder

    job = next((j for j in model_finder.jobs() if j["id"] == job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail="No such search.")
    return {"job": job}
