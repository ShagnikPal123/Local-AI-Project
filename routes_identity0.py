"""HTTP routes for Identity 0 — "Big Kahuna" (Request S).

All owner-only (``server.require_local_owner``): Big Kahuna sees every answer and can open things on
this PC by voice, so nobody else may read or steer it. Hosted builds do not have these routes
(``deploy_mode.HOSTED_BLOCKED_PREFIXES``). The model/training routes hand over to ``identity0.jobs``
and ``identity0.model``, which run torch in their own processes, never in this one.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


def _owner_dep():
    def dependency(http_request: Request, authorization: Optional[str] = Header(default=None)) -> Any:
        from server import require_local_owner

        user = require_local_owner(http_request, authorization)
        # require_local_owner also lets admins in (they may restart the engine). Big Kahuna reads every
        # answer and acts on this PC, so on a claimed install it is the owner's alone.
        if user is not None:
            from auth import Role

            if getattr(user, "role", None) is not Role.OWNER:
                raise HTTPException(status_code=403, detail="Only the owner can use Big Kahuna.")
        return user
    return Depends(dependency)


Owner = _owner_dep()


def _router() -> Any:
    import server

    return server._get_service(None).router


class SettingsBody(BaseModel):
    changes: Dict[str, Any]


class TextBody(BaseModel):
    text: str
    tab: str = ""


class IntentBody(BaseModel):
    text: str
    final: bool = False
    tabs: List[Dict[str, str]] = []


class ActBody(BaseModel):
    action: Dict[str, Any]


class JobBody(BaseModel):
    kind: str
    params: Dict[str, Any] = {}


@router.get("/api/identity0")
def kahuna_overview(_owner=Owner) -> Dict[str, Any]:
    from identity0 import companion, competence, provider

    overview = provider.status(_router())
    overview["competence"] = competence.table()
    overview["companion"] = {"enabled": companion.enabled()}
    overview["own_model"] = _own_model()
    return overview


def _own_model() -> Dict[str, Any]:
    try:
        from identity0 import jobs
        from identity0.model import client, registry

        return {"current": client.current(), "ready": client.is_ready(), "versions": registry.list_versions(),
                "requirements": jobs.requirements()}
    except Exception as error:  # noqa: BLE001 - the model track may not be installed yet
        return {"current": None, "ready": False, "versions": [], "note": f"not available yet ({type(error).__name__})"}


def _own_model_version(member: str) -> bool:
    """``self:<version>`` names the promoted own model (the one the scoreboard can start and ask)."""
    try:
        from identity0.model import client

        current = client.current() or {}
        return member == f"self:{current.get('version')}"
    except Exception:  # noqa: BLE001
        return False


@router.get("/api/identity0/settings")
def kahuna_settings(_owner=Owner) -> Dict[str, Any]:
    from identity0 import state

    return {"settings": state.get_settings(), "defaults": state.DEFAULTS}


@router.put("/api/identity0/settings")
def kahuna_update_settings(body: SettingsBody, _owner=Owner) -> Dict[str, Any]:
    from identity0 import members, state

    try:
        settings = state.update_settings(**body.changes)
    except state.SettingsError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    members.forget_cache()
    return {"settings": settings}


@router.post("/api/identity0/main")
def kahuna_make_main(_owner=Owner) -> Dict[str, Any]:
    """Make Big Kahuna the chat's default answerer (the owner can still pick any other model)."""
    from config import SETTINGS
    from identity0 import state

    import model_choice

    state.update_settings(enabled=True)
    SETTINGS.preferred_online_provider = "identity0"
    model_choice.remember("identity0")
    return {"provider": "identity0"}


@router.get("/api/identity0/competence")
def kahuna_competence(_owner=Owner) -> Dict[str, Any]:
    from identity0 import competence

    return competence.table()


@router.get("/api/identity0/experiences")
def kahuna_experiences(limit: int = 30, offset: int = 0, _owner=Owner) -> Dict[str, Any]:
    from identity0 import experience

    rows = experience.recent(max(1, min(200, limit)), max(0, offset))
    for row in rows:  # the list view needs the gist, not 8 KB answers
        for key in ("lead", "shadow"):
            if isinstance(row.get(key), dict):
                row[key] = {**row[key], "text": str(row[key].get("text", ""))[:600]}
    return {"experiences": rows, "stats": experience.stats()}


@router.post("/api/identity0/predict")
def kahuna_predict(body: TextBody, _owner=Owner) -> Dict[str, Any]:
    from identity0 import predict

    return predict.everything(body.text, body.tab)


@router.get("/api/identity0/companion")
def kahuna_companion(_owner=Owner) -> Dict[str, Any]:
    from identity0 import companion

    return {"enabled": companion.enabled(), "messages": companion.history()}


@router.post("/api/identity0/companion/ask")
def kahuna_companion_ask(body: TextBody, _owner=Owner) -> Dict[str, Any]:
    from identity0 import companion

    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Say something first.")
    return {"message": companion.ask(body.text.strip()[:4000], _router())}


@router.delete("/api/identity0/companion")
def kahuna_companion_clear(_owner=Owner) -> Dict[str, Any]:
    from identity0 import companion

    companion.clear()
    return {"messages": []}


@router.post("/api/identity0/warm")
def kahuna_warm(_owner=Owner) -> Dict[str, Any]:
    """Load the local models into VRAM now — the voice bar calls this when it starts listening."""
    from identity0 import api

    return {"warming": api.warm_up()}


@router.post("/api/identity0/intent")
def kahuna_intent(body: IntentBody, _owner=Owner) -> Dict[str, Any]:
    from identity0 import companion

    return companion.intent(body.text[:2000], final=body.final, tabs=body.tabs[:80])


@router.post("/api/identity0/act")
def kahuna_act(body: ActBody, _owner=Owner) -> Dict[str, Any]:
    from identity0 import companion

    result = companion.act(body.action, router=_router())
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "That could not be done."))
    return result


# --- templates and suggested tabs (identity0.templates / identity0.tabs) ---------------------------


@router.get("/api/identity0/templates")
def kahuna_templates(q: str = "", category: str = "", _owner=Owner) -> Dict[str, Any]:
    try:
        from identity0 import templates
    except ImportError as error:
        raise HTTPException(status_code=503, detail="Templates are not installed yet.") from error
    return {"templates": templates.search(q, category=category), "categories": templates.categories()}


@router.get("/api/identity0/templates/{template_id}")
def kahuna_template(template_id: str, _owner=Owner) -> Dict[str, Any]:
    from identity0 import templates

    found = templates.get(template_id)
    if not found:
        raise HTTPException(status_code=404, detail="No template with that id.")
    return {"template": found}


class InstantiateBody(BaseModel):
    folder: str = ""
    name: str = ""


@router.post("/api/identity0/templates/{template_id}/use")
def kahuna_template_use(template_id: str, body: InstantiateBody, _owner=Owner) -> Dict[str, Any]:
    from identity0 import templates

    try:
        return templates.instantiate(template_id, folder=body.folder, name=body.name)
    except templates.TemplateError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/api/identity0/tabs")
def kahuna_tab_proposals(_owner=Owner) -> Dict[str, Any]:
    try:
        from identity0 import tabs
    except ImportError as error:
        raise HTTPException(status_code=503, detail="The tab planner is not installed yet.") from error
    return {"proposals": tabs.refresh(), "auto": tabs.auto_enabled()}


@router.post("/api/identity0/tabs/refresh")
def kahuna_tab_refresh(_owner=Owner) -> Dict[str, Any]:
    from identity0 import tabs

    return {"proposals": tabs.refresh()}


@router.post("/api/identity0/tabs/{proposal_id}/{decision}")
def kahuna_tab_decide(proposal_id: str, decision: str, _owner=Owner) -> Dict[str, Any]:
    from identity0 import tabs

    if decision not in ("approve", "dismiss"):
        raise HTTPException(status_code=400, detail="approve or dismiss")
    try:
        return tabs.decide(proposal_id, decision == "approve")
    except tabs.TabPlanError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


# --- its own model (identity0.jobs / identity0.model: torch runs in subprocesses) -------------------


def _jobs() -> Any:
    try:
        from identity0 import jobs

        return jobs
    except ImportError as error:
        raise HTTPException(status_code=503, detail="The model track is not installed yet.") from error


@router.get("/api/identity0/model")
def kahuna_model(_owner=Owner) -> Dict[str, Any]:
    return _own_model()


@router.get("/api/identity0/jobs")
def kahuna_jobs(_owner=Owner) -> Dict[str, Any]:
    return {"jobs": _jobs().list_jobs(), "requirements": _jobs().requirements()}


@router.post("/api/identity0/jobs")
def kahuna_start_job(body: JobBody, _owner=Owner) -> Dict[str, Any]:
    jobs = _jobs()
    try:
        return {"job": jobs.start(body.kind, body.params)}
    except jobs.JobError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/api/identity0/jobs/{job_id}/cancel")
def kahuna_cancel_job(job_id: str, _owner=Owner) -> Dict[str, Any]:
    jobs = _jobs()
    try:
        return {"job": jobs.cancel(job_id)}
    except jobs.JobError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/api/identity0/jobs/{job_id}/resume")
def kahuna_resume_job(job_id: str, _owner=Owner) -> Dict[str, Any]:
    """Carry an interrupted training run on from its last checkpoint."""
    jobs = _jobs()
    try:
        return {"job": jobs.resume(job_id)}
    except jobs.JobError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/api/identity0/model/{version}/promote")
def kahuna_promote(version: str, _owner=Owner) -> Dict[str, Any]:
    try:
        from identity0.model import registry
    except ImportError as error:
        raise HTTPException(status_code=503, detail="The model track is not installed yet.") from error
    try:
        return {"versions": registry.promote(version)}
    except registry.RegistryError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/api/identity0/scoreboard")
def kahuna_scoreboard(_owner=Owner) -> Dict[str, Any]:
    try:
        from identity0 import evaluate
    except ImportError as error:
        raise HTTPException(status_code=503, detail="Evaluation is not installed yet.") from error
    return {"scoreboard": evaluate.scoreboard(), "suites": evaluate.suites(), "running": _SCORING["running"]}


class ScoreBody(BaseModel):
    member: str
    suite: str = "core"


_SCORING: Dict[str, Any] = {"running": None}


@router.post("/api/identity0/scoreboard/run")
def kahuna_score(body: ScoreBody, _owner=Owner) -> Dict[str, Any]:
    """Put the fixed questions to one member in the background (HTTP calls only — no torch here)."""
    import threading

    from identity0 import evaluate

    if body.suite not in evaluate.SUITES:
        raise HTTPException(status_code=400, detail="Unknown suite.")
    from identity0 import members

    # Only a member Big Kahuna may use right now: never a paid key the owner did not pick, never a typo.
    allowed = {m.id for m in members.available(_router())}
    if body.member not in allowed and not (body.member.startswith("self:") and _own_model_version(body.member)):
        raise HTTPException(status_code=400, detail="That model is not available to Big Kahuna right now.")
    if _SCORING["running"]:
        raise HTTPException(status_code=409, detail=f"Already scoring {_SCORING['running']}.")
    _SCORING["running"] = body.member

    def work() -> None:
        try:
            if body.member.startswith("self:"):
                from identity0.model import client

                client.ensure_started()
            evaluate.run(body.member, body.suite)
        finally:
            _SCORING["running"] = None

    threading.Thread(target=work, name="kahuna-score", daemon=True).start()
    return {"running": body.member}


# --- the constitution (identity0.supercore): the owner edits; Big Kahuna only proposes -------------


class ConstitutionBody(BaseModel):
    changes: Dict[str, Any]


@router.get("/api/identity0/constitution")
def kahuna_constitution(_owner=Owner) -> Dict[str, Any]:
    from identity0 import supercore

    return {"current": supercore.current(), "pending": supercore.pending()}


@router.put("/api/identity0/constitution")
def kahuna_constitution_update(body: ConstitutionBody, _owner=Owner) -> Dict[str, Any]:
    from identity0 import supercore

    try:
        return {"current": supercore.update(body.changes, by="owner")}
    except supercore.ConstitutionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/identity0/constitution/{proposal_id}/{decision}")
def kahuna_constitution_decide(proposal_id: str, decision: str, _owner=Owner) -> Dict[str, Any]:
    from identity0 import supercore

    if decision not in ("approve", "decline"):
        raise HTTPException(status_code=400, detail="approve or decline")
    try:
        return supercore.decide(proposal_id, decision == "approve", by="owner")
    except supercore.ConstitutionError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
