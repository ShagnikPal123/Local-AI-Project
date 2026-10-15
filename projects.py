"""Constellations (projects) and Quasars (artifacts): the owner's big containers and the things made inside them.

The owner (2026-10-11, from the sidebar of the Claude app): "Projects will be a large project to group things in; within
a project tabs are auto grouped and the titles for these groups are auto named and can be changed; specific agents,
sub-agents and avatars can be added so they run on this project and help on it. Artifacts are things that are created,
like in a project, new ideas, new things."

A project is **data** (invariant 2): a name, a goal, groups of tab ids, the helpers assigned to it and its artifacts.
Nothing here runs code. Group names are generated from a fixed table of math / space words so they stay stable
("Lattice" for building, "Spectrum" for research…); the moment the owner renames one it is marked ``auto: false`` and
auto-grouping never touches it again.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from paths import data_path

_LOCK = threading.RLock()
MEMBER_KINDS = ("agents", "subagents", "avatars")
ARTIFACT_KINDS = ("idea", "document", "design", "code", "image", "plan", "other")

# Which family a tab belongs to, and what its auto-named group is called (math / space words, plain subtitle kept).
_FAMILY = {
    "nyx": "talk", "equalize": "talk", "kahuna": "talk",
    "code": "build", "collab": "build", "design": "build", "build": "build", "games": "build",
    "research": "study", "learn": "study", "notes": "study", "predict": "study", "design_research": "study",
    "agents": "crew", "subagents": "crew", "avatars": "crew", "office": "crew", "world": "crew",
    "trading": "markets", "finance": "markets",
    "connectors": "links", "computer": "links", "screen": "links",
}
GROUP_NAMES = {
    "talk": ("Dialogue", "Conversations and voice"), "build": ("Lattice", "Building and code"),
    "study": ("Spectrum", "Research and learning"), "crew": ("Orbit", "Agents and teams"),
    "markets": ("Vector", "Money and markets"), "links": ("Bridge", "Connections and the computer"),
    "other": ("Nebula", "Everything else"),
}


class ProjectError(ValueError):
    pass


def _path():
    return data_path("projects.json")


def _blank() -> Dict[str, Any]:
    return {"projects": {}, "artifacts": {}}


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("projects"), dict):
            data.setdefault("artifacts", {})
            return data
    except (OSError, ValueError):
        pass
    return _blank()


def _save(state: Dict[str, Any]) -> None:
    path = _path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(path)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _tab_ids(value: Any) -> List[str]:
    out: List[str] = []
    for item in value if isinstance(value, list) else []:
        tab = _text(item, 60)
        if tab and tab not in out:
            out.append(tab)
    return out[:60]


def auto_groups(tabs: List[str]) -> List[Dict[str, Any]]:
    """Group tab ids by family and name each group. Same input → same names, so it never flickers."""
    buckets: Dict[str, List[str]] = {}
    for tab in tabs:
        buckets.setdefault(_FAMILY.get(tab, "other"), []).append(tab)
    groups = []
    for family, (name, about) in GROUP_NAMES.items():
        if family in buckets:
            groups.append({"id": f"auto-{family}", "name": name, "about": about, "auto": True, "tabs": buckets[family]})
    return groups


def _regroup(project: Dict[str, Any]) -> None:
    """Keep the owner's renamed groups; rebuild the auto ones from whatever tabs are not in a renamed group."""
    kept = [g for g in project.get("groups", []) if not g.get("auto")]
    taken = {t for g in kept for t in g.get("tabs", [])}
    loose = [t for t in project.get("tabs", []) if t not in taken]
    project["groups"] = kept + auto_groups(loose)


def _view(project: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    mine = [a for a in state["artifacts"].values() if a.get("project_id") == project["id"]]
    return {**project, "artifacts": sorted(mine, key=lambda a: -a.get("created", 0))}


def list_projects() -> List[Dict[str, Any]]:
    with _LOCK:
        state = _load()
        rows = [_view(p, state) for p in state["projects"].values()]
    return sorted(rows, key=lambda p: (not p.get("starred"), -p.get("updated", 0)))


def get(project_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        state = _load()
        project = state["projects"].get(project_id)
        return _view(project, state) if project else None


def create(name: str, goal: str = "", tabs: Optional[List[str]] = None) -> Dict[str, Any]:
    name = _text(name, 80)
    if not name:
        raise ProjectError("Give the project a name.")
    now = time.time()
    project = {"id": _id("pr"), "name": name, "goal": _text(goal, 600), "created": now, "updated": now,
               "tabs": _tab_ids(tabs or []), "groups": [], "members": {k: [] for k in MEMBER_KINDS}}
    _regroup(project)
    with _LOCK:
        state = _load()
        state["projects"][project["id"]] = project
        _save(state)
        return _view(project, state)


def _edit(project_id: str, change) -> Dict[str, Any]:
    with _LOCK:
        state = _load()
        project = state["projects"].get(project_id)
        if not project:
            raise ProjectError("No such project.")
        change(project, state)
        project["updated"] = time.time()
        _save(state)
        return _view(project, state)


def update(project_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    def apply(project, _state):
        if "name" in changes:
            name = _text(changes["name"], 80)
            if not name:
                raise ProjectError("A project needs a name.")
            project["name"] = name
        if "goal" in changes:
            project["goal"] = _text(changes["goal"], 600)
        # Owner's ask (Drive doc 1, item 1.28): like Claude's projects, standing instructions every chat and thread on
        # the project follows, and a star that keeps a project at the top of the list.
        if "instructions" in changes:
            project["instructions"] = str(changes["instructions"] or "").replace("\r\n", "\n").strip()[:4000]
        if "starred" in changes:
            project["starred"] = bool(changes["starred"])
        # Like a Claude project's folder (owner, 2026-10-15): the folder on this PC the project's chats work in when
        # Code is on. Only the path is kept; reading it still goes through the Code gate.
        if "folder" in changes:
            project["folder"] = str(changes["folder"] or "").strip().strip('"')[:500]
        # More places the project may open (owner, 2026-10-15: "open drives"): extra folders on this PC, and Google
        # Drive folders written "drive:<name or id>" (those open once Google sign-in works). The main chat can only
        # browse the folder and these drives, nothing else on the PC.
        if "drives" in changes:
            seen: List[str] = []
            for value in changes["drives"] or []:
                path = str(value or "").strip().strip('"')[:500]
                if path and path not in seen:
                    seen.append(path)
            project["drives"] = seen[:12]
        if "tabs" in changes:
            project["tabs"] = _tab_ids(changes["tabs"])
            _regroup(project)

    return _edit(project_id, apply)


def rename_group(project_id: str, group_id: str, name: str) -> Dict[str, Any]:
    name = _text(name, 40)
    if not name:
        raise ProjectError("A group needs a name.")

    def apply(project, _state):
        for group in project["groups"]:
            if group["id"] == group_id:
                group["name"], group["auto"] = name, False        # the owner's name is never overwritten again
                return
        raise ProjectError("No such group.")

    return _edit(project_id, apply)


def add_tab(project_id: str, tab: str) -> Dict[str, Any]:
    tab = _text(tab, 60)

    def apply(project, _state):
        if tab and tab not in project["tabs"]:
            project["tabs"].append(tab)
        _regroup(project)

    return _edit(project_id, apply)


def remove_tab(project_id: str, tab: str) -> Dict[str, Any]:
    def apply(project, _state):
        project["tabs"] = [t for t in project["tabs"] if t != tab]
        for group in project["groups"]:
            group["tabs"] = [t for t in group.get("tabs", []) if t != tab]
        project["groups"] = [g for g in project["groups"] if g.get("tabs") or not g.get("auto")]
        _regroup(project)

    return _edit(project_id, apply)


def set_member(project_id: str, kind: str, member: str, on: bool = True) -> Dict[str, Any]:
    if kind not in MEMBER_KINDS:
        raise ProjectError(f"Members are {', '.join(MEMBER_KINDS)}.")
    member = _text(member, 80)

    def apply(project, _state):
        members = project["members"].setdefault(kind, [])
        if on and member and member not in members:
            members.append(member)
        elif not on and member in members:
            members.remove(member)

    return _edit(project_id, apply)


def delete(project_id: str) -> bool:
    """Removes the project and keeps its artifacts (they become unattached) — nothing the owner made is lost."""
    with _LOCK:
        state = _load()
        if project_id not in state["projects"]:
            return False
        del state["projects"][project_id]
        for artifact in state["artifacts"].values():
            if artifact.get("project_id") == project_id:
                artifact["project_id"] = ""
        _save(state)
        return True


def project_note(project_id: str) -> str:
    """One paragraph for a helper's prompt: what the project is and who else is on it. Empty if unknown."""
    project = get(project_id)
    if not project:
        return ""
    crew = [f"{k}: {', '.join(v)}" for k, v in project["members"].items() if v]
    return (f"You are working on the project “{project['name']}”. Goal: {project['goal'] or 'not stated'}."
            + (f" Others on it — {'; '.join(crew)}." if crew else "")
            + (f" The owner's instructions for this project, to follow: {project['instructions']}"
               if project.get("instructions") else ""))


# --- artifacts -----------------------------------------------------------------------------------------------------

def add_artifact(title: str, kind: str = "idea", note: str = "", project_id: str = "", ref: str = "") -> Dict[str, Any]:
    title = _text(title, 120)
    if not title:
        raise ProjectError("Give the artifact a title.")
    with _LOCK:
        state = _load()
        if project_id and project_id not in state["projects"]:
            raise ProjectError("No such project.")
        artifact = {"id": _id("ar"), "title": title, "kind": kind if kind in ARTIFACT_KINDS else "other",
                    "note": _text(note, 4000), "project_id": project_id, "ref": _text(ref, 300), "created": time.time()}
        state["artifacts"][artifact["id"]] = artifact
        _save(state)
        return artifact


def file_result(project_id: str, ref: str, title: str, note: str, kind: str = "document") -> Dict[str, Any]:
    """A project's Library keeps one entry per source (a Commander thread, by ``ref``): its latest result updates that
    entry's note instead of adding another, so a busy thread does not bury the rest."""
    with _LOCK:
        state = _load()
        for artifact in state["artifacts"].values():
            if ref and artifact.get("ref") == ref and artifact.get("project_id") == project_id:
                artifact.update(title=_text(title, 120) or artifact["title"], note=_text(note, 4000), updated=time.time())
                _save(state)
                return artifact
    return add_artifact(title, kind, note, project_id, ref)


def list_artifacts(project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with _LOCK:
        rows = list(_load()["artifacts"].values())
    if project_id is not None:
        rows = [a for a in rows if a.get("project_id") == project_id]
    return sorted(rows, key=lambda a: -a.get("created", 0))


def set_artifact_chat(artifact_id: str, chat_id: str) -> None:
    """Remember the chat a Library item opens in (project_workspace.artifact_chat), so it opens the same one again."""
    with _LOCK:
        state = _load()
        if artifact_id in state["artifacts"]:
            state["artifacts"][artifact_id]["chat_id"] = _text(chat_id, 80)
            _save(state)


def move_artifact(artifact_id: str, project_id: str) -> Dict[str, Any]:
    with _LOCK:
        state = _load()
        artifact = state["artifacts"].get(artifact_id)
        if not artifact:
            raise ProjectError("No such artifact.")
        if project_id and project_id not in state["projects"]:
            raise ProjectError("No such project.")
        artifact["project_id"] = project_id
        _save(state)
        return artifact


def delete_artifact(artifact_id: str) -> bool:
    with _LOCK:
        state = _load()
        if artifact_id not in state["artifacts"]:
            return False
        del state["artifacts"][artifact_id]
        _save(state)
        return True
