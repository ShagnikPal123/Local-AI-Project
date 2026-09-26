"""HTTP routes for the Data Absorption tab (Request R1–R8).

Watching a run is an ordinary signed-in read. Starting, steering and — above all — approving what a run suggests
changes this machine's Nyx, so those need the owner (loopback on an unclaimed install, an owner/admin session once
claimed), like the Code tab. Hosted builds do not have these routes (``deploy_mode.HOSTED_BLOCKED_PREFIXES``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response
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
    import absorb_engine

    try:
        return fn(*args, **kwargs)
    except absorb_engine.AbsorbError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


class StartBody(BaseModel):
    mode: str
    prompt: str = ""
    links: List[str] = Field(default_factory=list)
    uploads: List[str] = Field(default_factory=list)
    settings: Dict[str, Any] = Field(default_factory=dict)
    replace: bool = False


class FocusBody(BaseModel):
    topic: Optional[str] = None


class AgainBody(BaseModel):
    how: str = "same"
    topic: str = ""


class PrefsBody(BaseModel):
    use_in_chats: Optional[bool] = None


@router.get("/api/absorb")
def absorb_overview(_user=RequireChat) -> Dict[str, Any]:
    import absorb_engine
    import absorb_text

    engine = absorb_engine.ENGINE
    active = engine.active()
    return {"runs": engine.list(), "active": engine.live(active.id) if active else None, "defaults": absorb_engine.DEFAULTS,
            "limits": absorb_engine.LIMITS, "sources": list(absorb_engine.SOURCES), "stages": list(absorb_engine.STAGES),
            "topics": [{"id": t["id"], "code": t["code"], "name": t["name"]} for t in absorb_text.DEFAULT_TOPICS],
            "prefs": absorb_engine.settings(), "storage_bytes": engine.storage_bytes()}


@router.post("/api/absorb/start")
def absorb_start(body: StartBody, _owner=Owner) -> Dict[str, Any]:
    import absorb_engine

    return _call(absorb_engine.ENGINE.start, body.mode, prompt=body.prompt, links=body.links, uploads=body.uploads,
                 settings=body.settings, replace=body.replace)


@router.put("/api/absorb/prefs")
def absorb_prefs(body: PrefsBody, _owner=Owner) -> Dict[str, Any]:
    import absorb_engine

    return absorb_engine.save_settings(**body.model_dump())


@router.get("/api/absorb/{run_id}/live")
def absorb_live(run_id: str, have_doc: str = "", _user=RequireChat) -> Dict[str, Any]:
    import absorb_engine

    return _call(absorb_engine.ENGINE.live, run_id, have_doc=have_doc)


@router.get("/api/absorb/{run_id}")
def absorb_run(run_id: str, _user=RequireChat) -> Dict[str, Any]:
    import absorb_engine

    run = _call(absorb_engine.ENGINE.get, run_id)
    data = run.to_dict()
    data["docs"] = [{k: v for k, v in d.items() if k not in ("lines", "spans", "text", "_key")} for d in data["docs"]]
    return {"run": data}


@router.get("/api/absorb/{run_id}/doc/{doc_id}")
def absorb_doc(run_id: str, doc_id: str, _user=RequireChat) -> Dict[str, Any]:
    import absorb_engine

    return {"doc": _call(absorb_engine.ENGINE.doc, run_id, doc_id)}


@router.post("/api/absorb/{run_id}/again")
def absorb_again(run_id: str, body: AgainBody, _owner=Owner) -> Dict[str, Any]:
    import absorb_engine

    return _call(absorb_engine.ENGINE.again, run_id, body.how, body.topic)


@router.post("/api/absorb/{run_id}/{action}")
def absorb_action(run_id: str, action: str, _owner=Owner) -> Dict[str, Any]:
    import absorb_engine

    engine = absorb_engine.ENGINE
    actions = {"stop": engine.stop, "pause": engine.pause, "resume": engine.resume, "forget": engine.forget}
    if action not in actions:
        raise HTTPException(status_code=404, detail="Unknown action.")
    return _call(actions[action], run_id)


@router.put("/api/absorb/{run_id}/focus")
def absorb_focus(run_id: str, body: FocusBody, _owner=Owner) -> Dict[str, Any]:
    import absorb_engine

    return _call(absorb_engine.ENGINE.set_focus, run_id, body.topic)


@router.put("/api/absorb/{run_id}/settings")
def absorb_settings(run_id: str, body: Dict[str, Any], _owner=Owner) -> Dict[str, Any]:
    import absorb_engine

    return _call(absorb_engine.ENGINE.update_settings, run_id, body)


@router.post("/api/absorb/{run_id}/suggestions/{suggestion_id}/{decision}")
def absorb_decide(run_id: str, suggestion_id: str, decision: str, _owner=Owner) -> Dict[str, Any]:
    import absorb_engine

    if decision not in ("approve", "dismiss"):
        raise HTTPException(status_code=404, detail="Approve or dismiss.")
    return {"suggestion": _call(absorb_engine.ENGINE.decide, run_id, suggestion_id, decision)}


@router.delete("/api/absorb/{run_id}")
def absorb_delete(run_id: str, _owner=Owner) -> Dict[str, Any]:
    import absorb_engine

    _call(absorb_engine.ENGINE.delete, run_id)
    return {"deleted": run_id}


@router.get("/api/absorb/{run_id}/export")
def absorb_export(run_id: str, _owner=Owner) -> Response:
    import absorb_engine

    path = _call(absorb_engine.ENGINE.export_dataset, run_id)
    return Response(content=path.read_bytes(), media_type="application/jsonl",
                    headers={"Content-Disposition": f"attachment; filename=\"{path.name}\""})


# ---------------------------------------------------------------------------
# Data Process Use (Request R7–R8)
# ---------------------------------------------------------------------------


def _data_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    import data_process

    try:
        return fn(*args, **kwargs)
    except data_process.DataError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


class DataBody(BaseModel):
    request: str
    uploads: List[str] = Field(default_factory=list)
    links: List[str] = Field(default_factory=list)
    text: str = ""
    parent: str = ""


@router.get("/api/data-process")
def data_list(_user=RequireChat) -> Dict[str, Any]:
    import data_process

    return {"jobs": data_process.JOBS.list(), "presets": data_process.PRESETS, "steps": list(data_process.STEPS)}


@router.post("/api/data-process")
def data_start(body: DataBody, _owner=Owner) -> Dict[str, Any]:
    import data_process

    return {"job": _data_call(data_process.JOBS.start, body.request, uploads=body.uploads, links=body.links, text=body.text,
                              parent=body.parent)}


@router.get("/api/data-process/{job_id}")
def data_get(job_id: str, _user=RequireChat) -> Dict[str, Any]:
    import data_process

    return {"job": _data_call(data_process.JOBS.get, job_id)}


@router.post("/api/data-process/{job_id}/stop")
def data_stop(job_id: str, _owner=Owner) -> Dict[str, Any]:
    import data_process

    return {"job": _data_call(data_process.JOBS.stop, job_id)}


@router.post("/api/data-process/{job_id}/suggestions/{suggestion_id}/{decision}")
def data_decide(job_id: str, suggestion_id: str, decision: str, _owner=Owner) -> Dict[str, Any]:
    import data_process

    if decision not in ("approve", "dismiss"):
        raise HTTPException(status_code=404, detail="Approve or dismiss.")
    return {"suggestion": _data_call(data_process.JOBS.decide, job_id, suggestion_id, decision)}


@router.get("/api/data-process/{job_id}/export")
def data_export(job_id: str, what: str = "report", _user=RequireChat) -> Response:
    import data_process

    result = _data_call(data_process.JOBS.export, job_id, what)
    return Response(content=result["content"], media_type=f"{result['mime']}; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=\"{result['filename']}\""})


@router.delete("/api/data-process/{job_id}")
def data_delete(job_id: str, _owner=Owner) -> Dict[str, Any]:
    import data_process

    _data_call(data_process.JOBS.delete, job_id)
    return {"deleted": job_id}
