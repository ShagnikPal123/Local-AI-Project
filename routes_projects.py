"""HTTP routes for Constellations (projects.py), Quasars (artifacts) and Orbits (scheduled.py). All the owner's:
a scheduled task can send mail and text people through an avatar, and a project can hand helpers the owner's files."""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


def _owner(request: Request) -> Any:
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


def _call(action):
    import projects
    import scheduled

    try:
        return action()
    except (projects.ProjectError, scheduled.ScheduleError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


class ProjectBody(BaseModel):
    name: str = ""
    goal: str = ""
    tabs: Optional[List[str]] = None


class NameBody(BaseModel):
    name: str


class TabBody(BaseModel):
    tab: str


class MemberBody(BaseModel):
    kind: str
    member: str
    on: bool = True


class ArtifactBody(BaseModel):
    title: str
    kind: str = "idea"
    note: str = ""
    project_id: str = ""
    ref: str = ""


class MoveBody(BaseModel):
    project_id: str = ""


# --- projects ----------------------------------------------------------------------------------------------------

@router.get("/api/projects")
def projects_list(_o=Depends(_owner)) -> Dict[str, Any]:
    import projects

    return {"projects": projects.list_projects()}


@router.post("/api/projects")
def projects_create(body: ProjectBody, _o=Depends(_owner)) -> Dict[str, Any]:
    import projects

    return {"project": _call(lambda: projects.create(body.name, body.goal, body.tabs))}


@router.get("/api/projects/{project_id}")
def projects_get(project_id: str, _o=Depends(_owner)) -> Dict[str, Any]:
    import projects

    project = projects.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="No such project.")
    return {"project": project}


@router.put("/api/projects/{project_id}")
def projects_update(project_id: str, body: Dict[str, Any], _o=Depends(_owner)) -> Dict[str, Any]:
    import projects

    return {"project": _call(lambda: projects.update(project_id, body))}


@router.delete("/api/projects/{project_id}")
def projects_delete(project_id: str, _o=Depends(_owner)) -> Dict[str, Any]:
    import projects

    if not projects.delete(project_id):
        raise HTTPException(status_code=404, detail="No such project.")
    return {"ok": True}


@router.put("/api/projects/{project_id}/groups/{group_id}")
def projects_rename_group(project_id: str, group_id: str, body: NameBody, _o=Depends(_owner)) -> Dict[str, Any]:
    import projects

    return {"project": _call(lambda: projects.rename_group(project_id, group_id, body.name))}


@router.post("/api/projects/{project_id}/tabs")
def projects_add_tab(project_id: str, body: TabBody, _o=Depends(_owner)) -> Dict[str, Any]:
    import projects

    return {"project": _call(lambda: projects.add_tab(project_id, body.tab))}


@router.delete("/api/projects/{project_id}/tabs/{tab}")
def projects_remove_tab(project_id: str, tab: str, _o=Depends(_owner)) -> Dict[str, Any]:
    import projects

    return {"project": _call(lambda: projects.remove_tab(project_id, tab))}


@router.post("/api/projects/{project_id}/members")
def projects_member(project_id: str, body: MemberBody, _o=Depends(_owner)) -> Dict[str, Any]:
    import projects

    return {"project": _call(lambda: projects.set_member(project_id, body.kind, body.member, body.on))}


# --- artifacts ---------------------------------------------------------------------------------------------------

@router.get("/api/artifacts")
def artifacts_list(project_id: Optional[str] = None, _o=Depends(_owner)) -> Dict[str, Any]:
    import projects

    return {"artifacts": projects.list_artifacts(project_id), "kinds": list(projects.ARTIFACT_KINDS)}


@router.post("/api/artifacts")
def artifacts_add(body: ArtifactBody, _o=Depends(_owner)) -> Dict[str, Any]:
    import projects

    return {"artifact": _call(lambda: projects.add_artifact(body.title, body.kind, body.note, body.project_id, body.ref))}


@router.put("/api/artifacts/{artifact_id}/project")
def artifacts_move(artifact_id: str, body: MoveBody, _o=Depends(_owner)) -> Dict[str, Any]:
    import projects

    return {"artifact": _call(lambda: projects.move_artifact(artifact_id, body.project_id))}


@router.delete("/api/artifacts/{artifact_id}")
def artifacts_delete(artifact_id: str, _o=Depends(_owner)) -> Dict[str, Any]:
    import projects

    if not projects.delete_artifact(artifact_id):
        raise HTTPException(status_code=404, detail="No such artifact.")
    return {"ok": True}


# --- scheduled ---------------------------------------------------------------------------------------------------

@router.get("/api/scheduled")
def scheduled_list(_o=Depends(_owner)) -> Dict[str, Any]:
    import scheduled

    return {"tasks": scheduled.list_tasks(), "repeats": list(scheduled.REPEATS)}


@router.post("/api/scheduled")
def scheduled_create(body: Dict[str, Any], _o=Depends(_owner)) -> Dict[str, Any]:
    import scheduled

    return {"task": _call(lambda: scheduled.create(body))}


# The week calendar. Under /api/scheduled so the hosted-mode block and the owner-only rule cover it too.
@router.get("/api/scheduled/calendar/week")
def calendar_week(day: str = "", _o=Depends(_owner)) -> Dict[str, Any]:
    from datetime import date

    import calendar_view

    try:
        chosen = date.fromisoformat(day) if day else None
    except ValueError as error:
        raise HTTPException(status_code=400, detail="day must look like 2026-10-14.") from error
    return calendar_view.week(chosen)


@router.get("/api/scheduled/calendar/look")
def calendar_look(_o=Depends(_owner)) -> Dict[str, Any]:
    import calendar_view

    return {"look": calendar_view.get_look()}


@router.put("/api/scheduled/calendar/look")
def calendar_look_set(body: Dict[str, Any], _o=Depends(_owner)) -> Dict[str, Any]:
    import calendar_view

    return {"look": calendar_view.set_look(body)}


@router.put("/api/scheduled/{task_id}")
def scheduled_update(task_id: str, body: Dict[str, Any], _o=Depends(_owner)) -> Dict[str, Any]:
    import scheduled

    return {"task": _call(lambda: scheduled.update(task_id, body))}


@router.delete("/api/scheduled/{task_id}")
def scheduled_delete(task_id: str, _o=Depends(_owner)) -> Dict[str, Any]:
    import scheduled

    if not scheduled.delete(task_id):
        raise HTTPException(status_code=404, detail="No such task.")
    return {"ok": True}


@router.post("/api/scheduled/{task_id}/run")
def scheduled_run(task_id: str, _o=Depends(_owner)) -> Dict[str, Any]:
    """Runs in the background (a task can take minutes); the list shows the result when it lands."""
    import scheduled

    task = next((t for t in scheduled.list_tasks() if t["id"] == task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="No such task.")
    if not task["avatar"]:
        raise HTTPException(status_code=400, detail="Pick an avatar to do this task first.")
    threading.Thread(target=scheduled.run_now, args=(task_id, 600), name="ichos-scheduled-run", daemon=True).start()
    return {"started": True}
