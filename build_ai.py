"""The AI half of the Build studio.

The owner: "the AI helps heavily". So the model is not a chat box bolted to the
side - it draws parts, wires them up, explains each one as a tutorial step,
compares real options, and can be left running for hours on "design an
apparatus and the parts needed to make a containment device for the AI itself".

Everything a model produces comes back as JSON and goes through
``design_studio``'s validators before it can touch a project, so the worst a
bad answer can do is be refused (invariant 2). Nothing here executes anything
a model wrote, and nothing orders, buys or uploads.

Long jobs run on a daemon thread and write into the project as they go, phase
by phase, so the owner watches parts appear rather than waiting on a spinner.
The job record survives a restart; a thread does not, and a job interrupted by
one is marked as such instead of pretending to still be running.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

import design_studio as ds
from paths import atomic_replace, data_path

ROLE = "build_studio"

SYSTEM = (
    "You are the design engineer inside Nyx's Build studio. You design real, buildable things: 3D-printed "
    "parts, enclosures, mechanisms and the circuits that go in them. You are precise about millimetres, "
    "voltages and currents, and you say plainly when something is a guess or needs a datasheet. You never "
    "invent a part number you are not sure of. Safety notes are short and specific, never boilerplate."
)

#: The whole vocabulary a model is allowed to draw with. Kept in one string so
#: the prompt and the validator can never drift apart in a way nobody notices.
GEOMETRY_RULES = """
A part is JSON: {"name", "kind", "color", "material", "summary", "features":[...], "pins":[...], "specs":{...}}.
kind is one of mechanical, electronic, enclosure, fastener, material.

Units are millimetres. Axes: X right, Z forward, Y UP. A part is centred on its own origin.

Each feature is:
  {"type", "name", "op", "at":[x,y,z], "rot":[deg,deg,deg], "size":{...}, "round", "blend", "note"}
  type: box | cylinder | sphere | cone | torus | wedge | pipe | extrude | revolve
  op:   add (default) | cut (subtracts it) | intersect (keeps only the shared volume)
  size fields per type:
    box, wedge : w (X), d (Z), h (Y)
    cylinder   : r, h          - stands along Y. Add "sides": 6 for a hex prism.
    pipe       : r, t, h       - a tube with wall thickness t
    sphere     : r
    cone       : r (bottom), r2 (top, 0 for a point), h
    torus      : r (ring), t (tube)
    extrude    : h, plus "profile": [[x,z], ...] - a closed outline drawn in XZ, pushed along Y
    revolve    : plus "profile": [[radius, y], ...] - swept around the Y axis
  round : radius that softens this shape's own edges
  blend : fillet radius where this shape meets everything before it (a cut with
          a blend makes a rounded pocket). Keep both under a third of the smallest size.
  note  : one sentence on what this feature is FOR. It becomes the tutorial text.

Modifiers, to avoid repeating yourself:
  "repeat": {"count": 8, "step": [10,0,0]}          - a line of copies
  "radial": {"count": 6, "axis": "y", "radius": 20} - a ring of copies
  "mirror": ["x"]                                   - a copy across that axis
Whole-part: "shell": {"thickness": 2} hollows it out to a wall.

The FIRST feature must be an add. A cut only removes material that an earlier
add put there.

A pin is a point something connects to:
  {"name", "kind", "direction", "at":[x,y,z], "voltage", "required", "note"}
  kind:      power | gnd | digital | analog | pwm | i2c | spi | uart | usb | net | mech
  direction: in | out | bidir | power | gnd | passive
  Put pins where the real connector is, not at the origin. Mark power and ground required.

Reply with JSON only. No prose, no markdown fence.
"""


class BuildAIError(RuntimeError):
    """The model could not produce something usable; the message says why."""


def _run(prompt: str, *, system: str = SYSTEM, max_tokens: int = 3000) -> Tuple[str, str]:
    from model_roles import MODEL_ROLES

    run = MODEL_ROLES.run(ROLE, prompt, system=system, max_tokens=max_tokens)
    if not (run.text or "").strip():
        raise BuildAIError("The model came back empty. Try again, or pick another model in Keys & Models.")
    return run.text, run.label


def _json_block(text: str) -> Any:
    """Pull the JSON object or array out of an answer that may be wrapped."""
    from tools import _loads_lenient

    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = stripped.split("```")[1] if stripped.count("```") >= 2 else stripped[3:]
        if stripped.lstrip().lower().startswith("json"):
            stripped = stripped.lstrip()[4:]
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = stripped.find(opener), stripped.rfind(closer)
        if start != -1 and end > start:
            parsed = _loads_lenient(stripped[start:end + 1])
            if parsed is not None:
                return parsed
    raise BuildAIError("The model did not answer with the JSON the studio needs. Try once more.")


# --- drawing and editing parts ------------------------------------------------


def draw_part(words: str, *, context: str = "") -> Dict[str, Any]:
    """Turn a sentence into a validated part spec."""
    wanted = str(words or "").strip()
    if not wanted:
        raise BuildAIError("Say what to draw first.")
    prompt = (
        f"Design this part: {wanted}\n\n"
        f"{('Context - the build it goes into:' + chr(10) + context + chr(10) + chr(10)) if context else ''}"
        f"{GEOMETRY_RULES}\n"
        "Use real dimensions. If the part bolts to something standard, use that standard hole pattern "
        "(M3 clearance is r=1.7). Give every feature a note. Give the part a one-paragraph summary that "
        "says what it is and how it is meant to be made."
    )
    text, label = _run(prompt, max_tokens=3200)
    spec = _json_block(text)
    if isinstance(spec, dict) and isinstance(spec.get("part"), dict):
        spec = spec["part"]
    spec["source"] = "ai"
    part = ds.clean_part(spec)
    return {"part": part, "model": label}


def edit_part(part: Dict[str, Any], instruction: str) -> Dict[str, Any]:
    """Change an existing part by description, keeping its identity."""
    told = str(instruction or "").strip()
    if not told:
        raise BuildAIError("Say what to change.")
    slim = {key: part[key] for key in ("name", "kind", "color", "material", "summary", "features", "pins", "specs")
            if key in part}
    prompt = (
        f"Here is a part as JSON:\n{json.dumps(slim)[:12000]}\n\n"
        f"Change it: {told}\n\n{GEOMETRY_RULES}\n"
        "Return the WHOLE part, not a patch. Keep every feature id you did not change, and keep the pins "
        "unless the change moves a connector."
    )
    text, label = _run(prompt, max_tokens=3600)
    spec = _json_block(text)
    if isinstance(spec, dict) and isinstance(spec.get("part"), dict):
        spec = spec["part"]
    spec["source"] = "ai"
    updated = ds.clean_part(spec, keep_id=part.get("id", ""))
    return {"part": updated, "model": label}


# --- the tutorial -------------------------------------------------------------


def tutorial_for(project: Dict[str, Any]) -> Dict[str, Any]:
    """One step per part, each pointing at the thing the viewport should light.

    This is the feature the owner asked for by name - "make sure each part is
    highlighted, similar to a tutorial" - so the ids are validated against the
    project here rather than trusted: a step that points at nothing would
    silently highlight nothing, which reads as a broken viewport.
    """
    placements = project.get("placements", [])
    if not placements and not project.get("parts"):
        raise BuildAIError("There is nothing in this build to explain yet.")
    known = {p["id"]: p for p in placements}
    parts = {p["id"]: p for p in project.get("parts", [])}
    nets = {n["id"]: n for n in project.get("nets", [])}

    prompt = (
        f"{ds.describe(project)}\n\n"
        "Write the assembly tutorial for this build, in the order someone would actually put it together: "
        "base and structure first, then boards, then wiring, then the lid. One step per piece or per wire. "
        "Each step names the ONE thing to look at.\n\n"
        "JSON only:\n"
        '{"title": "...", "intro": "one short paragraph", "steps": [\n'
        '  {"title": "...", "body": "2-4 sentences: what this is, what it does, how it attaches",\n'
        '   "focus": {"kind": "placement|part|net", "id": "the id from the list above"},\n'
        '   "tips": ["at most two"], "warning": "only when something can really go wrong"}\n]}\n'
        "Use the exact ids given above. Do not invent ids."
    )
    text, label = _run(prompt, max_tokens=3600)
    raw = _json_block(text)
    if isinstance(raw, list):
        raw = {"steps": raw}

    # Drop steps that point at nothing, and let a placement id stand in for a
    # part id (models mix the two up, and the intent is always the same).
    kept: List[Dict[str, Any]] = []
    for step in (raw.get("steps") or []):
        if not isinstance(step, dict):
            continue
        focus = step.get("focus") if isinstance(step.get("focus"), dict) else {}
        target = str(focus.get("id") or "")
        kind = str(focus.get("kind") or "")
        if target in known:
            focus = {"kind": "placement", "id": target, "part_id": known[target]["part_id"]}
        elif target in parts:
            first = next((p["id"] for p in placements if p["part_id"] == target), "")
            focus = {"kind": "placement", "id": first, "part_id": target} if first else {"kind": "part", "id": target}
        elif target in nets:
            focus = {"kind": "net", "id": target}
        elif kind and target:
            continue  # points at an id this build does not have
        else:
            focus = {"kind": "none", "id": ""}
        kept.append({**step, "focus": focus})

    raw["steps"] = kept
    raw["model"] = label
    raw["source"] = "ai"
    tutorial = ds.clean_tutorial(raw)
    if tutorial is None:
        raise BuildAIError("The model did not produce a usable tutorial. Try again.")
    return {"tutorial": tutorial, "model": label}


def explain_part(part: Dict[str, Any], *, context: str = "") -> Dict[str, Any]:
    """A short read on one part: what it is, how to make it, what to watch."""
    bounds = ds.part_bounds(part)
    prompt = (
        f"Part: {part['name']} ({part['kind']}), {bounds['size'][0]:.1f} x {bounds['size'][2]:.1f} x "
        f"{bounds['size'][1]:.1f} mm, material {part.get('material') or 'unset'}.\n"
        f"Summary: {part.get('summary', '(none)')}\n"
        f"Shapes: {json.dumps([{k: f[k] for k in ('type', 'op', 'name', 'size')} for f in part['features']])[:4000]}\n"
        f"Pins: {json.dumps([{k: p[k] for k in ('name', 'kind', 'direction', 'voltage')} for p in part.get('pins', [])])[:2000]}\n"
        f"{('Build context: ' + context) if context else ''}\n\n"
        "In Markdown, under 200 words: what this part is for, how it should be made (printed, machined, bought), "
        "the one dimension most likely to be wrong, and anything genuinely unsafe. No headings, no filler."
    )
    text, label = _run(prompt, max_tokens=700)
    return {"text": text.strip(), "model": label}


# --- reviewing and wiring -----------------------------------------------------


def review(project: Dict[str, Any], question: str = "") -> Dict[str, Any]:
    """Analysis of the whole build, on top of the checks arithmetic already did."""
    asked = str(question or "").strip()
    prompt = (
        f"{ds.describe(project)}\n\n"
        + (f"The owner asks: {asked}\n\n" if asked else "")
        + "Review this build as an engineer who has to make it work. In Markdown, short sections:\n"
        "**Will it work** - the honest answer.\n"
        "**Problems** - only real ones, with the fix. Do not repeat the checks listed above; go past them.\n"
        "**Missing** - what this build still needs and does not have.\n"
        "**Next** - the three things to do next, in order.\n"
        "Be specific about millimetres, volts and amps. Say when you are unsure."
    )
    text, label = _run(prompt, max_tokens=1800)
    return {"text": text.strip(), "model": label}


def wiring_for(project: Dict[str, Any], goal: str = "") -> Dict[str, Any]:
    """Propose connections. The owner applies them; nothing is wired silently."""
    if len(project.get("placements", [])) < 2:
        raise BuildAIError("Put at least two pieces in the space before asking for wiring.")
    prompt = (
        f"{ds.describe(project)}\n\n"
        + (f"What it has to do: {goal}\n\n" if goal else "")
        + "Wire this up. Power and ground first, then signals. Use the exact placement ids and pin NAMES "
        "shown above.\n\n"
        'JSON only: {"connections": [{"from": {"placement": "id", "pin": "pin name"}, '
        '"to": {"placement": "id", "pin": "pin name"}, "name": "what this wire is", '
        '"why": "one sentence"}], "notes": "anything the owner must add that is not here"}\n'
        "Do not connect a power pin to a ground pin. Do not connect two outputs together. "
        "If a part needs a resistor or a level shifter that is not in the build, say so in notes "
        "instead of wiring around it."
    )
    text, label = _run(prompt, max_tokens=2200)
    raw = _json_block(text)
    if isinstance(raw, list):
        raw = {"connections": raw}

    placements = {p["id"]: p for p in project["placements"]}
    parts = {p["id"]: p for p in project["parts"]}

    def resolve(side: Any) -> Optional[Dict[str, str]]:
        if not isinstance(side, dict):
            return None
        placement = placements.get(str(side.get("placement") or side.get("id") or ""))
        if placement is None:
            return None
        part = parts.get(placement["part_id"])
        wanted = str(side.get("pin") or "").strip().lower()
        pin = next((p for p in (part or {}).get("pins", []) if p["name"].lower() == wanted), None)
        if pin is None:  # models shorten "2 5V" to "5V"; match on the tail
            pin = next((p for p in (part or {}).get("pins", [])
                        if wanted and (p["name"].lower().endswith(wanted) or p["id"].lower() == wanted)), None)
        return {"placement": placement["id"], "pin": pin["id"], "label": f"{placement.get('name') or part['name']}.{pin['name']}"} if pin else None

    proposals: List[Dict[str, Any]] = []
    for item in (raw.get("connections") or [])[:60]:
        if not isinstance(item, dict):
            continue
        left, right = resolve(item.get("from")), resolve(item.get("to"))
        if not left or not right or (left["placement"] == right["placement"] and left["pin"] == right["pin"]):
            continue
        proposals.append({
            "id": uuid.uuid4().hex[:8],
            "from": left,
            "to": right,
            "name": str(item.get("name") or "")[:60] or f"{left['label']} to {right['label']}",
            "why": str(item.get("why") or "")[:300],
        })
    if not proposals:
        raise BuildAIError("The model did not name any two pins that exist in this build. Try again.")
    return {"connections": proposals, "notes": str(raw.get("notes") or "")[:1200], "model": label}


def compare(project: Dict[str, Any], question: str) -> Dict[str, Any]:
    """Pi vs Arduino vs Jetson, as a table the UI renders and a pick with reasons."""
    import build_catalog

    asked = str(question or "").strip() or "Which board should this build use?"
    known = json.dumps([{"id": e["id"], "name": e["name"], "summary": e["summary"], "specs": e["specs"]}
                        for e in build_catalog.listing() if e["group"] == "Compute"])[:4000]
    prompt = (
        f"Build so far:\n{ds.describe(project, limit=2500)}\n\n"
        f"Question: {asked}\n\n"
        f"Parts already in Nyx's catalog (prefer these, and give their id as catalog_id):\n{known}\n\n"
        "Compare two to four real options. Use real prices and real numbers; where you are unsure of a price, "
        "say so in the summary rather than inventing one.\n\n"
        'JSON only: {"question": "...", "options": [{"name": "...", "catalog_id": "... or empty", '
        '"summary": "2-3 sentences", "price_usd": 0, "pros": ["..."], "cons": ["..."], '
        '"specs": {"key": "value"}, "score": 0-10}], "recommendation": "the name of the pick", '
        '"because": "why, in 3-4 sentences, including what would change the answer"}'
    )
    text, label = _run(prompt, max_tokens=2400)
    raw = _json_block(text)
    raw["model"] = label
    comparison = ds.clean_comparison(raw)
    if comparison is None:
        raise BuildAIError("The model did not return two comparable options. Try again.")
    return {"comparison": comparison, "model": label}


# --- long jobs ----------------------------------------------------------------
#
# "tell the ai in this tab to take a couple hours to generate an apparatus and
# the parts needed" (01_GOALS.md). Each phase is one model call that writes its
# result into the project before the next one starts, so stopping halfway still
# leaves something real behind.

PHASES: List[Tuple[str, str]] = [
    ("plan", "Working out what this needs"),
    ("choose", "Choosing the real components"),
    ("parts", "Drawing the custom parts"),
    ("layout", "Arranging everything in the space"),
    ("wiring", "Wiring the circuit"),
    ("tutorial", "Writing the build tutorial"),
    ("review", "Checking the whole thing over"),
]

_JOB_LOCK = threading.RLock()
_STOPS: Dict[str, threading.Event] = {}


def _jobs_path():
    return data_path("build/jobs.json")


def _load_jobs() -> Dict[str, Any]:
    try:
        data = json.loads(_jobs_path().read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("jobs"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"jobs": []}


def _save_jobs(data: Dict[str, Any]) -> None:
    path = _jobs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    atomic_replace(temp, path)


def _put_job(job: Dict[str, Any]) -> Dict[str, Any]:
    with _JOB_LOCK:
        data = _load_jobs()
        for index, existing in enumerate(data["jobs"]):
            if existing["id"] == job["id"]:
                data["jobs"][index] = job
                break
        else:
            data["jobs"].insert(0, job)
        data["jobs"] = data["jobs"][:40]
        _save_jobs(data)
    from agent_events import publish_ui

    publish_ui("build.job", job={k: job[k] for k in ("id", "project_id", "state", "phase", "progress", "brief")})
    return job


def _get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOB_LOCK:
        return next((j for j in _load_jobs()["jobs"] if j["id"] == job_id), None)


def jobs_for(project_id: str = "", limit: int = 10) -> List[Dict[str, Any]]:
    with _JOB_LOCK:
        jobs = _load_jobs()["jobs"]
    # A running job with no live thread is one a restart killed. Say so rather
    # than leaving a progress bar that will never move again.
    for job in jobs:
        if job["state"] == "running" and job["id"] not in _STOPS:
            job["state"] = "interrupted"
            job["message"] = "Nyx restarted while this was running. Start it again to carry on."
    return [j for j in jobs if not project_id or j["project_id"] == project_id][:limit]


def stop_job(job_id: str) -> bool:
    event = _STOPS.get(job_id)
    if event:
        event.set()
        return True
    job = _get_job(job_id)
    if job and job["state"] == "running":
        job["state"] = "stopped"
        _put_job(job)
        return True
    return False


def start_apparatus(project_id: str, brief: str, *, budget_minutes: int = 30) -> Dict[str, Any]:
    """Design a whole apparatus in the background, writing as it goes."""
    project = ds.project_or_error(project_id)
    wanted = str(brief or "").strip() or project.get("goal", "")
    if not wanted:
        raise BuildAIError("Say what to design first.")
    if any(j["state"] == "running" and j["project_id"] == project_id for j in jobs_for(project_id, 40)):
        raise BuildAIError("This build already has a design job running. Stop it first.")

    job = {
        "id": uuid.uuid4().hex[:10],
        "project_id": project_id,
        "brief": wanted[:2000],
        "state": "running",
        "phase": PHASES[0][0],
        "phase_label": PHASES[0][1],
        "progress": 0.0,
        "message": "Starting",
        "steps": [],
        "started_at": time.time(),
        "ended_at": 0.0,
        "budget_minutes": max(1, min(int(budget_minutes or 30), 480)),
        "model": "",
    }
    _put_job(job)
    stop = threading.Event()
    _STOPS[job["id"]] = stop
    thread = threading.Thread(target=_work, args=(job["id"], stop), name=f"nyx-build-{job['id']}", daemon=True)
    thread.start()
    return job


def _note(job: Dict[str, Any], phase: str, text: str, *, model: str = "") -> None:
    job["steps"].append({"phase": phase, "text": text[:600], "model": model, "at": time.time()})
    job["steps"] = job["steps"][-40:]
    job["message"] = text[:300]
    if model:
        job["model"] = model
    _put_job(job)


def _work(job_id: str, stop: threading.Event) -> None:
    job = _get_job(job_id)
    if job is None:
        return
    deadline = job["started_at"] + job["budget_minutes"] * 60
    try:
        for index, (phase, label) in enumerate(PHASES):
            if stop.is_set():
                job["state"] = "stopped"
                job["message"] = "Stopped."
                break
            if time.time() > deadline:
                job["state"] = "done"
                job["message"] = f"Out of time after {label.lower()}. What it finished is saved."
                break
            job.update(phase=phase, phase_label=label, progress=round(index / len(PHASES), 2))
            _put_job(job)
            _PHASE_WORK[phase](job)
        else:
            job["state"] = "done"
            job["message"] = "Finished. Open the tutorial to walk through it."
    except ds.BuildError as error:
        job["state"] = "failed"
        job["message"] = str(error)
    except BuildAIError as error:
        job["state"] = "failed"
        job["message"] = str(error)
    except Exception as error:  # noqa: BLE001 - a background thread must not die silently
        job["state"] = "failed"
        job["message"] = f"Stopped on an unexpected error: {error}"
    finally:
        job["progress"] = 1.0 if job["state"] == "done" else job.get("progress", 0.0)
        job["ended_at"] = time.time()
        _STOPS.pop(job_id, None)
        _put_job(job)


def _phase_plan(job: Dict[str, Any]) -> None:
    project = ds.project_or_error(job["project_id"])
    prompt = (
        f"Design brief: {job['brief']}\n\n"
        f"Starting point:\n{ds.describe(project, limit=2000)}\n\n"
        "Plan this apparatus before drawing anything. JSON only:\n"
        '{"understanding": "what is actually being asked for, in 3 sentences", '
        '"requirements": ["..."], "risks": ["..."], '
        '"structure": ["the physical pieces this needs, one line each"], '
        '"electronics": ["the electronic parts this needs, one line each"], '
        '"space_mm": {"width": 0, "depth": 0, "height": 0}}'
    )
    text, label = _run(prompt, max_tokens=1600)
    plan = _json_block(text)
    job["plan"] = {
        "understanding": str(plan.get("understanding", ""))[:1200],
        "requirements": [str(r)[:200] for r in (plan.get("requirements") or [])[:12]],
        "risks": [str(r)[:200] for r in (plan.get("risks") or [])[:8]],
        "structure": [str(r)[:200] for r in (plan.get("structure") or [])[:12]],
        "electronics": [str(r)[:200] for r in (plan.get("electronics") or [])[:12]],
    }
    space = plan.get("space_mm") if isinstance(plan.get("space_mm"), dict) else None
    if space:
        ds.update_project(job["project_id"], space=space)
    ds.update_project(job["project_id"], notes=job["plan"]["understanding"])
    _note(job, "plan", job["plan"]["understanding"] or "Planned.", model=label)


def _phase_choose(job: Dict[str, Any]) -> None:
    import build_catalog

    project = ds.project_or_error(job["project_id"])
    wanted = "; ".join(job.get("plan", {}).get("electronics", [])) or job["brief"]
    known = json.dumps([{"id": e["id"], "name": e["name"], "summary": e["summary"]}
                        for e in build_catalog.listing()])[:6000]
    prompt = (
        f"Apparatus: {job['brief']}\nElectronics needed: {wanted}\n\n"
        f"Catalog:\n{known}\n\n"
        'Pick the catalog parts this build needs, with how many of each. JSON only: '
        '{"picks": [{"catalog_id": "...", "quantity": 1, "why": "one sentence"}], '
        '"missing": ["anything needed that is not in the catalog"]}'
    )
    text, label = _run(prompt, max_tokens=1400)
    chosen = _json_block(text)
    added = 0
    for pick in (chosen.get("picks") or [])[:20]:
        if not isinstance(pick, dict):
            continue
        catalog_id = str(pick.get("catalog_id") or "").strip()
        if catalog_id not in build_catalog.CATALOG:
            continue
        for _ in range(max(1, min(int(float(pick.get("quantity", 1) or 1)), 8))):
            try:
                ds.use_catalog_part(job["project_id"], catalog_id)
                added += 1
            except ds.BuildError:
                break
    job["missing"] = [str(m)[:200] for m in (chosen.get("missing") or [])[:10]]
    _note(job, "choose", f"Added {added} component(s) from the catalog."
          + (f" Still needed: {', '.join(job['missing'][:3])}." if job["missing"] else ""), model=label)


def _phase_parts(job: Dict[str, Any]) -> None:
    project = ds.project_or_error(job["project_id"])
    wanted = job.get("plan", {}).get("structure") or []
    if not wanted:
        _note(job, "parts", "No custom parts were needed.")
        return
    context = ds.describe(project, limit=2000)
    drawn = 0
    for line in wanted[:6]:
        try:
            result = draw_part(f"{line}. It is part of: {job['brief']}", context=context)
        except (BuildAIError, ds.BuildError) as error:
            _note(job, "parts", f"Could not draw {line[:60]}: {error}")
            continue
        project, part = ds.save_part(job["project_id"], result["part"])
        ds.place_part(job["project_id"], part["id"])
        drawn += 1
        _note(job, "parts", f"Drew {part['name']}.", model=result["model"])
    _note(job, "parts", f"Drew {drawn} custom part(s).")


def _phase_layout(job: Dict[str, Any]) -> None:
    project = ds.project_or_error(job["project_id"])
    if len(project.get("placements", [])) < 2:
        _note(job, "layout", "Nothing to arrange yet.")
        return
    prompt = (
        f"Apparatus: {job['brief']}\n\n{ds.describe(project, limit=3500)}\n\n"
        "Arrange these pieces sensibly in the build space: nothing overlapping, everything sitting on or "
        "above the plate (y = 0 is the plate, Y is up), heat sources with room around them, connectors "
        "reachable.\n\n"
        'JSON only: {"placements": [{"id": "the placement id", "at": [x, y, z], "rot": [0, 0, 0], '
        '"why": "one short sentence"}]}'
    )
    text, label = _run(prompt, max_tokens=2000)
    raw = _json_block(text)
    known = {p["id"] for p in project["placements"]}
    moved = 0
    for item in (raw.get("placements") or [])[:80]:
        if not isinstance(item, dict) or str(item.get("id")) not in known:
            continue
        try:
            ds.update_placement(job["project_id"], str(item["id"]), at=item.get("at"), rot=item.get("rot"),
                                note=str(item.get("why") or "")[:400])
            moved += 1
        except ds.BuildError:
            continue
    _note(job, "layout", f"Arranged {moved} piece(s) in the space.", model=label)


def _phase_wiring(job: Dict[str, Any]) -> None:
    project = ds.project_or_error(job["project_id"])
    if len([p for p in project["parts"] if p.get("pins")]) < 2:
        _note(job, "wiring", "Nothing here needs wiring.")
        return
    try:
        result = wiring_for(project, goal=job["brief"])
    except BuildAIError as error:
        _note(job, "wiring", f"Could not wire it: {error}")
        return
    wired = 0
    for connection in result["connections"]:
        try:
            ds.connect(job["project_id"], connection["from"]["placement"], connection["from"]["pin"],
                       connection["to"]["placement"], connection["to"]["pin"], name=connection["name"])
            wired += 1
        except ds.BuildError:
            continue
    job["wiring_notes"] = result.get("notes", "")
    _note(job, "wiring", f"Connected {wired} wire(s)." + (f" Note: {result['notes'][:200]}" if result.get("notes") else ""),
          model=result["model"])


def _phase_tutorial(job: Dict[str, Any]) -> None:
    project = ds.project_or_error(job["project_id"])
    try:
        result = tutorial_for(project)
    except BuildAIError as error:
        _note(job, "tutorial", f"Could not write the tutorial: {error}")
        return
    ds.set_tutorial(job["project_id"], result["tutorial"])
    _note(job, "tutorial", f"Wrote {len(result['tutorial']['steps'])} tutorial steps.", model=result["model"])


def _phase_review(job: Dict[str, Any]) -> None:
    project = ds.project_or_error(job["project_id"])
    try:
        result = review(project, question=f"Does this meet the brief: {job['brief']}?")
    except BuildAIError as error:
        _note(job, "review", f"Could not review it: {error}")
        return
    job["review"] = result["text"]
    checks = ds.check_project(project)
    errors = [c for c in checks if c["level"] == "error"]
    _note(job, "review", f"Reviewed. {len(errors)} error(s) and {len(checks) - len(errors)} note(s) from the rule checks.",
          model=result["model"])


_PHASE_WORK: Dict[str, Callable[[Dict[str, Any]], None]] = {
    "plan": _phase_plan,
    "choose": _phase_choose,
    "parts": _phase_parts,
    "layout": _phase_layout,
    "wiring": _phase_wiring,
    "tutorial": _phase_tutorial,
    "review": _phase_review,
}
