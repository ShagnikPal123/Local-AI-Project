"""HTTP routes and chat tools for the Build tab (Request H4).

Every route is behind the session middleware (deny by default), and every one
that takes a spec runs it through ``design_studio``'s validators before it
reaches storage. Nothing here writes a file outside the data directory, runs a
program, or orders a part - the studio designs, the owner buys.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server_auth import RequireChat

router = APIRouter()


def _fail(error: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


# --- request bodies -----------------------------------------------------------


class ProjectRequest(BaseModel):
    name: str = ""
    goal: str = ""


class ProjectPatch(BaseModel):
    name: Optional[str] = None
    goal: Optional[str] = None
    notes: Optional[str] = None
    space: Optional[Dict[str, Any]] = None


class PartRequest(BaseModel):
    part: Dict[str, Any]
    part_id: str = ""
    place: bool = False


class PlaceRequest(BaseModel):
    part_id: str = ""
    catalog_id: str = ""
    library_id: str = ""
    at: Optional[List[float]] = None
    name: str = ""


class PlacementPatch(BaseModel):
    at: Optional[List[float]] = None
    rot: Optional[List[float]] = None
    scale: Optional[float] = None
    name: Optional[str] = None
    color: Optional[str] = None
    locked: Optional[bool] = None
    note: Optional[str] = None


class ConnectRequest(BaseModel):
    from_placement: str
    from_pin: str
    to_placement: str
    to_pin: str
    name: str = ""
    kind: str = ""


class NetPatch(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    color: Optional[str] = None
    note: Optional[str] = None
    voltage: Optional[float] = None


class JointRequest(BaseModel):
    a: str
    b: str
    kind: str = "fixed"
    note: str = ""


class AskRequest(BaseModel):
    """Every AI action in the studio, so the UI has one call to make."""

    action: str
    words: str = ""
    part_id: str = ""
    question: str = ""
    #: For "design an apparatus": how long the background job may run.
    budget_minutes: int = 30
    #: Draw/edit results are returned for review by default, not saved.
    save: bool = False


class LibraryRequest(BaseModel):
    part: Optional[Dict[str, Any]] = None
    project_id: str = ""
    part_id: str = ""


# --- projects -----------------------------------------------------------------


@router.get("/api/build/projects")
def build_projects(_user=RequireChat) -> Dict[str, Any]:
    import design_studio

    return design_studio.list_projects()


@router.post("/api/build/projects")
def build_create_project(body: ProjectRequest, _user=RequireChat) -> Dict[str, Any]:
    import design_studio

    project = design_studio.create_project(body.name or "New build", body.goal)
    return design_studio.snapshot(project)


@router.get("/api/build/projects/{project_id}")
def build_project(project_id: str, _user=RequireChat) -> Dict[str, Any]:
    import design_studio

    project = design_studio.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="That build no longer exists.")
    design_studio.set_active(project_id)
    return design_studio.snapshot(project)


@router.patch("/api/build/projects/{project_id}")
def build_update_project(project_id: str, body: ProjectPatch, _user=RequireChat) -> Dict[str, Any]:
    import design_studio

    try:
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        return design_studio.snapshot(design_studio.update_project(project_id, **fields))
    except design_studio.BuildError as error:
        raise _fail(error) from error


@router.delete("/api/build/projects/{project_id}")
def build_delete_project(project_id: str, _user=RequireChat) -> Dict[str, Any]:
    import design_studio

    return {"deleted": design_studio.delete_project(project_id)}


# --- parts --------------------------------------------------------------------


@router.post("/api/build/projects/{project_id}/parts")
def build_save_part(project_id: str, body: PartRequest, _user=RequireChat) -> Dict[str, Any]:
    import design_studio

    try:
        project, part = design_studio.save_part(project_id, body.part, body.part_id)
        if body.place:
            project, _placement = design_studio.place_part(project["id"], part["id"])
        return {**design_studio.snapshot(project), "part": part}
    except design_studio.BuildError as error:
        raise _fail(error) from error


@router.delete("/api/build/projects/{project_id}/parts/{part_id}")
def build_delete_part(project_id: str, part_id: str, _user=RequireChat) -> Dict[str, Any]:
    import design_studio

    try:
        return design_studio.snapshot(design_studio.delete_part(project_id, part_id))
    except design_studio.BuildError as error:
        raise _fail(error) from error


@router.post("/api/build/projects/{project_id}/parts/{part_id}/duplicate")
def build_duplicate_part(project_id: str, part_id: str, _user=RequireChat) -> Dict[str, Any]:
    import design_studio

    try:
        project, part = design_studio.duplicate_part(project_id, part_id)
        return {**design_studio.snapshot(project), "part": part}
    except design_studio.BuildError as error:
        raise _fail(error) from error


# --- the shared space ---------------------------------------------------------


@router.post("/api/build/projects/{project_id}/place")
def build_place(project_id: str, body: PlaceRequest, _user=RequireChat) -> Dict[str, Any]:
    import design_studio

    try:
        if body.catalog_id:
            project, part, placement = design_studio.use_catalog_part(project_id, body.catalog_id, body.at)
        elif body.library_id:
            project, part, placement = design_studio.use_library_part(project_id, body.library_id, body.at)
        elif body.part_id:
            project, placement = design_studio.place_part(project_id, body.part_id, body.at, body.name)
            part = design_studio.find_part(project, body.part_id)
        else:
            raise design_studio.BuildError("Say which part to place.")
        return {**design_studio.snapshot(project), "placement": placement, "part": part}
    except design_studio.BuildError as error:
        raise _fail(error) from error


@router.patch("/api/build/projects/{project_id}/placements/{placement_id}")
def build_update_placement(project_id: str, placement_id: str, body: PlacementPatch, _user=RequireChat) -> Dict[str, Any]:
    import design_studio

    try:
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        project, placement = design_studio.update_placement(project_id, placement_id, **fields)
        return {**design_studio.snapshot(project), "placement": placement}
    except design_studio.BuildError as error:
        raise _fail(error) from error


@router.delete("/api/build/projects/{project_id}/placements/{placement_id}")
def build_delete_placement(project_id: str, placement_id: str, _user=RequireChat) -> Dict[str, Any]:
    import design_studio

    try:
        return design_studio.snapshot(design_studio.delete_placement(project_id, placement_id))
    except design_studio.BuildError as error:
        raise _fail(error) from error


@router.post("/api/build/projects/{project_id}/joints")
def build_add_joint(project_id: str, body: JointRequest, _user=RequireChat) -> Dict[str, Any]:
    import design_studio

    try:
        project, joint = design_studio.add_joint(project_id, body.a, body.b, body.kind, body.note)
        return {**design_studio.snapshot(project), "joint": joint}
    except design_studio.BuildError as error:
        raise _fail(error) from error


@router.delete("/api/build/projects/{project_id}/joints/{joint_id}")
def build_delete_joint(project_id: str, joint_id: str, _user=RequireChat) -> Dict[str, Any]:
    import design_studio

    try:
        return design_studio.snapshot(design_studio.delete_joint(project_id, joint_id))
    except design_studio.BuildError as error:
        raise _fail(error) from error


# --- circuits -----------------------------------------------------------------


@router.post("/api/build/projects/{project_id}/connect")
def build_connect(project_id: str, body: ConnectRequest, _user=RequireChat) -> Dict[str, Any]:
    import design_studio

    try:
        project, net = design_studio.connect(project_id, body.from_placement, body.from_pin,
                                             body.to_placement, body.to_pin, body.name, body.kind)
        return {**design_studio.snapshot(project), "net": net}
    except design_studio.BuildError as error:
        raise _fail(error) from error


@router.delete("/api/build/projects/{project_id}/nets/{net_id}")
def build_disconnect(project_id: str, net_id: str, placement: str = "", pin: str = "", _user=RequireChat) -> Dict[str, Any]:
    import design_studio

    try:
        return design_studio.snapshot(design_studio.disconnect(project_id, net_id, placement, pin))
    except design_studio.BuildError as error:
        raise _fail(error) from error


@router.patch("/api/build/projects/{project_id}/nets/{net_id}")
def build_update_net(project_id: str, net_id: str, body: NetPatch, _user=RequireChat) -> Dict[str, Any]:
    import design_studio

    try:
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        return design_studio.snapshot(design_studio.update_net(project_id, net_id, **fields))
    except design_studio.BuildError as error:
        raise _fail(error) from error


# --- catalog and library ------------------------------------------------------


@router.get("/api/build/catalog")
def build_catalog_list(q: str = "", _user=RequireChat) -> Dict[str, Any]:
    import build_catalog

    return {"parts": build_catalog.search(q) if q.strip() else build_catalog.listing(),
            "groups": build_catalog.groups(), "note": build_catalog.NOMINAL_NOTE}


@router.get("/api/build/library")
def build_library(_user=RequireChat) -> Dict[str, Any]:
    import design_studio

    return {"parts": design_studio.library()}


@router.post("/api/build/library")
def build_library_save(body: LibraryRequest, _user=RequireChat) -> Dict[str, Any]:
    import design_studio

    try:
        spec = body.part
        if spec is None and body.project_id and body.part_id:
            project = design_studio.project_or_error(body.project_id)
            spec = design_studio.find_part(project, body.part_id)
        if spec is None:
            raise design_studio.BuildError("Nothing to save.")
        saved = design_studio.library_save(spec)
        return {"part": saved, "parts": design_studio.library()}
    except design_studio.BuildError as error:
        raise _fail(error) from error


@router.get("/api/build/library/{library_id}")
def build_library_part(library_id: str, _user=RequireChat) -> Dict[str, Any]:
    import design_studio

    part = design_studio.library_get(library_id)
    if part is None:
        raise HTTPException(status_code=404, detail="That saved part is gone.")
    return {"part": part}


@router.delete("/api/build/library/{library_id}")
def build_library_delete(library_id: str, _user=RequireChat) -> Dict[str, Any]:
    import design_studio

    return {"deleted": design_studio.library_delete(library_id), "parts": design_studio.library()}


# --- the AI -------------------------------------------------------------------


@router.post("/api/build/projects/{project_id}/ask")
def build_ask(project_id: str, body: AskRequest, _user=RequireChat) -> Dict[str, Any]:
    """One endpoint for every AI action, so the panel has one thing to call."""
    import build_ai
    import design_studio

    try:
        project = design_studio.project_or_error(project_id)
        action = (body.action or "").strip().lower()

        if action == "draw":
            result = build_ai.draw_part(body.words, context=design_studio.describe(project, limit=2000))
            if body.save:
                project, part = design_studio.save_part(project_id, result["part"])
                project, _placement = design_studio.place_part(project["id"], part["id"])
                return {**design_studio.snapshot(project), "part": part, "model": result["model"]}
            return {"part": result["part"], "model": result["model"], "preview": True}

        if action == "edit":
            part = design_studio.find_part(project, body.part_id)
            if part is None:
                raise design_studio.BuildError("Pick a part to change first.")
            result = build_ai.edit_part(part, body.words)
            if body.save:
                project, saved = design_studio.save_part(project_id, result["part"], part["id"])
                return {**design_studio.snapshot(project), "part": saved, "model": result["model"]}
            return {"part": result["part"], "model": result["model"], "preview": True}

        if action == "explain_part":
            part = design_studio.find_part(project, body.part_id)
            if part is None:
                raise design_studio.BuildError("Pick a part first.")
            result = build_ai.explain_part(part, context=project.get("goal", ""))
            return {"text": result["text"], "model": result["model"]}

        if action == "tutorial":
            result = build_ai.tutorial_for(project)
            project = design_studio.set_tutorial(project_id, result["tutorial"])
            return {**design_studio.snapshot(project), "model": result["model"]}

        if action == "review":
            result = build_ai.review(project, body.question)
            return {"text": result["text"], "model": result["model"],
                    "checks": design_studio.check_project(project)}

        if action == "wiring":
            result = build_ai.wiring_for(project, body.question or project.get("goal", ""))
            return {"connections": result["connections"], "notes": result["notes"], "model": result["model"]}

        if action == "compare":
            result = build_ai.compare(project, body.question or body.words)
            project = design_studio.set_comparison(project_id, result["comparison"])
            return {**design_studio.snapshot(project), "model": result["model"]}

        if action == "apparatus":
            job = build_ai.start_apparatus(project_id, body.words or body.question, budget_minutes=body.budget_minutes)
            return {"job": job}

        raise design_studio.BuildError(f"The studio has no AI action called {action!r}.")
    except (design_studio.BuildError, build_ai.BuildAIError) as error:
        raise _fail(error) from error


@router.post("/api/build/projects/{project_id}/apply-wiring")
def build_apply_wiring(project_id: str, body: Dict[str, Any], _user=RequireChat) -> Dict[str, Any]:
    """Wire up the connections the owner ticked. Nothing is applied unasked."""
    import design_studio

    wired, refused = 0, []
    project = None
    for connection in (body.get("connections") or [])[:80]:
        if not isinstance(connection, dict):
            continue
        try:
            project, _net = design_studio.connect(
                project_id,
                str(connection.get("from", {}).get("placement", "")),
                str(connection.get("from", {}).get("pin", "")),
                str(connection.get("to", {}).get("placement", "")),
                str(connection.get("to", {}).get("pin", "")),
                name=str(connection.get("name", ""))[:60],
            )
            wired += 1
        except design_studio.BuildError as error:
            refused.append(str(error))
    project = project or design_studio.project_or_error(project_id)
    return {**design_studio.snapshot(project), "wired": wired, "refused": refused[:8]}


@router.get("/api/build/jobs")
def build_jobs(project_id: str = "", _user=RequireChat) -> Dict[str, Any]:
    import build_ai

    return {"jobs": build_ai.jobs_for(project_id)}


@router.delete("/api/build/jobs/{job_id}")
def build_stop_job(job_id: str, _user=RequireChat) -> Dict[str, Any]:
    import build_ai

    return {"stopped": build_ai.stop_job(job_id)}


# --- chat tools ---------------------------------------------------------------
#
# The same studio from the chat tab: "put a Pi 5 and a fan in the AI box and
# wire them up" has to work without the owner opening the Build tab at all.


def _active_project(project_id: str = ""):
    import design_studio

    if project_id:
        return design_studio.project_or_error(project_id)
    listing = design_studio.list_projects()
    active = listing.get("active") or (listing["projects"][0]["id"] if listing["projects"] else "")
    if not active:
        return design_studio.create_project("New build")
    return design_studio.project_or_error(active)


def tool_build_status(project_id: str = "") -> str:
    import design_studio

    project = _active_project(project_id)
    checks = design_studio.check_project(project)
    bill = design_studio.bom(project)
    lines = [design_studio.describe(project, limit=3000)]
    lines.append(f"\nBill of materials: {bill['total_usd']:.2f} USD of parts, {bill['print_grams']:.0f} g to print.")
    if checks:
        lines.append("Checks: " + "; ".join(f"{c['level']}: {c['message']}" for c in checks[:6]))
    return "\n".join(lines)


def tool_build_add_part(what: str, project_id: str = "") -> str:
    """Catalog first, because a real component beats a drawn approximation."""
    import build_catalog
    import design_studio

    project = _active_project(project_id)
    hits = build_catalog.search(what, limit=3)
    if hits:
        _project, part, _placement = design_studio.use_catalog_part(project["id"], hits[0]["id"])
        return (f"Put a {part['name']} into the build {project['name']!r} and placed it in the space. "
                f"It has {len(part['pins'])} pins ready to wire.")

    import build_ai

    result = build_ai.draw_part(what, context=design_studio.describe(project, limit=1500))
    _project, part = design_studio.save_part(project["id"], result["part"])
    design_studio.place_part(project["id"], part["id"])
    size = design_studio.part_bounds(part)["size"]
    return (f"Drew {part['name']} ({size[0]:.0f} x {size[2]:.0f} x {size[1]:.0f} mm, "
            f"{len(part['features'])} shapes) and placed it in {project['name']!r}. [{result['model']}]")


def tool_build_connect(from_part: str, from_pin: str, to_part: str, to_pin: str, project_id: str = "") -> str:
    import design_studio

    project = _active_project(project_id)
    parts = {p["id"]: p for p in project["parts"]}

    def find(words: str):
        wanted = words.strip().lower()
        for placement in project["placements"]:
            name = (placement.get("name") or parts.get(placement["part_id"], {}).get("name", "")).lower()
            if wanted and (wanted in name or name in wanted):
                return placement
        return None

    left, right = find(from_part), find(to_part)
    if left is None or right is None:
        names = ", ".join(sorted({p.get("name") or parts.get(p["part_id"], {}).get("name", "") for p in project["placements"]}))
        return f"Could not find both pieces in the build. It holds: {names or '(nothing yet)'}."

    def pin_of(placement, words: str):
        part = parts.get(placement["part_id"], {})
        wanted = words.strip().lower()
        for pin in part.get("pins", []):
            if pin["name"].lower() == wanted or pin["name"].lower().endswith(wanted) or wanted in pin["name"].lower():
                return pin
        return None

    pin_a, pin_b = pin_of(left, from_pin), pin_of(right, to_pin)
    if pin_a is None or pin_b is None:
        missing = from_pin if pin_a is None else to_pin
        part = parts.get((left if pin_a is None else right)["part_id"], {})
        available = ", ".join(p["name"] for p in part.get("pins", [])[:20])
        return f"No pin called {missing!r} on {part.get('name', 'that part')}. It has: {available}."

    _project, net = design_studio.connect(project["id"], left["id"], pin_a["id"], right["id"], pin_b["id"])
    findings = [c for c in design_studio.check_project(design_studio.project_or_error(project["id"]))
                if c["level"] == "error"]
    warning = f" Warning: {findings[0]['message']}" if findings else ""
    return f"Connected {pin_a['name']} to {pin_b['name']} on net {net['name']!r} ({net['kind']}).{warning}"


def tool_build_design(brief: str, minutes: int = 30, project_id: str = "") -> str:
    import build_ai

    project = _active_project(project_id)
    job = build_ai.start_apparatus(project["id"], brief, budget_minutes=int(minutes or 30))
    return (f"Started designing {brief[:80]!r} in the build {project['name']!r}. It runs in the background for up to "
            f"{job['budget_minutes']} minutes and writes parts into the Build tab as it goes - watch it there.")


def register_build_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        "build_status", "Describe the current 3D build: parts, how they are placed, wiring and any problems found.",
        [ToolParam("project_id", "string", "Leave empty for the build the owner has open", required=False)],
        tool_build_status, category="general", label=lambda a: "Reading the build")
    registry.register(
        "build_add_part", "Add a part to the 3D build: a real component from the catalog, or a new one designed from the words.",
        [ToolParam("what", "string", "What to add, e.g. 'Raspberry Pi 5' or 'a vented bracket 60mm wide'"),
         ToolParam("project_id", "string", "Leave empty for the open build", required=False)],
        tool_build_add_part, category="files.write", label=lambda a: f"Adding {str(a.get('what', ''))[:40]} to the build")
    registry.register(
        "build_connect", "Wire two pins together in the 3D build, and report any rule the connection breaks.",
        [ToolParam("from_part", "string", "Name of the first piece"), ToolParam("from_pin", "string", "Pin name on it"),
         ToolParam("to_part", "string", "Name of the second piece"), ToolParam("to_pin", "string", "Pin name on it"),
         ToolParam("project_id", "string", "Leave empty for the open build", required=False)],
        tool_build_connect, category="files.write", label=lambda a: "Wiring the build")
    registry.register(
        "build_design", "Design a whole apparatus in the Build tab in the background: plan, parts, layout, wiring and a tutorial.",
        [ToolParam("brief", "string", "What to design"),
         ToolParam("minutes", "number", "How long it may run, up to 480", required=False),
         ToolParam("project_id", "string", "Leave empty for the open build", required=False)],
        tool_build_design, category="general", label=lambda a: f"Designing {str(a.get('brief', ''))[:40]}")
