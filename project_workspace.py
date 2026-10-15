"""A project's working file: what its main chat may open, add to, make and balance.

The owner (2026-10-15): a project is "basically creating a new file to work out of; an ai that can control, create ai
and threads, add files to the main file, open drives, look for and load balance". Commander (commander.py) already
starts, messages, reads and resolves threads. This module adds the rest, for a project's main chat only:

* **Open drives**: ``places`` are the project's folder plus its extra ``drives`` (projects.py). ``browse`` lists one of
  them, read-only, and never steps outside it. A Google Drive place is written ``drive:<name>``; it answers that Drive
  opens once Google sign-in works, instead of pretending.
* **Add files to the main file**: ``add_file`` copies a text file from a place into the project's knowledge
  (project_knowledge.py), which every thread's brief draws on. ``add_note`` adds typed text the same way.
* **Look for**: ``find`` searches the project's knowledge and the names in its places.
* **Create AI**: ``add_helper`` puts an agent on the project, making it first (agent_runtime.create_subagent) when it
  does not exist and a goal is given.
* **Load balance**: ``balance`` reads every open thread's status and how full it is, and says where new work should go.
* ``artifact_chat`` opens a Library item in the main chat: its thread's chat, or a chat made for it once.

Nothing here runs code or writes outside the app's own data; files are only read.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

#: Biggest file ``add_file`` copies into knowledge. Bigger files are cut by project_knowledge anyway.
MAX_FILE_BYTES = 400_000
#: Files that read as text. Anything else is listed but not copied.
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".log",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".css", ".html", ".htm", ".xml", ".sql", ".sh", ".ps1", ".bat", ".java",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".lua", ".r", ".tex",
}
#: Most entries one listing returns.
MAX_ENTRIES = 200
#: A thread past this share of its model's room should not get new work (matches commander.REFRESH_AT).
FULL_AT = 0.7
DRIVE_PREFIX = "drive:"
DRIVE_WAIT = ("Google Drive folders open once Google sign-in works (it is being fixed). Local folders on this PC "
              "work now.")


class WorkspaceError(ValueError):
    pass


def _project(project_id: str) -> Dict[str, Any]:
    import projects

    project = projects.get(project_id) if project_id else None
    if not project:
        raise WorkspaceError("No such project.")
    return project


# ---------------------------------------------------------------------------
# Places: the project's folder and drives
# ---------------------------------------------------------------------------

def places(project: Dict[str, Any]) -> List[Dict[str, str]]:
    """The folder, then each drive, as {path, kind, label}. Kind is "local" or "drive"."""
    rows: List[Dict[str, str]] = []
    for path in [project.get("folder") or ""] + list(project.get("drives") or []):
        path = str(path or "").strip()
        if not path or any(r["path"] == path for r in rows):
            continue
        if path.lower().startswith(DRIVE_PREFIX):
            rows.append({"path": path, "kind": "drive", "label": path[len(DRIVE_PREFIX):].strip() or "Google Drive"})
        else:
            rows.append({"path": path, "kind": "local", "label": Path(path).name or path})
    return rows


def _resolve(project: Dict[str, Any], path: str) -> tuple:
    """(place, resolved path) for a path inside one of the project's places. A relative path is read against the
    project's folder (or its first place). Anything outside every place is refused."""
    rows = places(project)
    if not rows:
        raise WorkspaceError("This project has no folder or drive yet. Link one on the project home first.")
    path = str(path or "").strip().strip('"')
    if path.lower().startswith(DRIVE_PREFIX) or (not path and rows[0]["kind"] == "drive"):
        raise WorkspaceError(DRIVE_WAIT)
    local = [r for r in rows if r["kind"] == "local"]
    if not local:
        raise WorkspaceError(DRIVE_WAIT)
    target = Path(path) if path and Path(path).is_absolute() else Path(local[0]["path"]) / path
    try:
        target = target.resolve()
    except OSError as error:
        raise WorkspaceError(f"That path cannot be read: {error}") from error
    for place in local:
        root = Path(place["path"]).resolve()
        if target == root or root in target.parents:
            return place, target
    raise WorkspaceError("That is outside this project's folder and drives. Add it as a drive first.")


def browse(project_id: str, path: str = "", match: str = "") -> Dict[str, Any]:
    """One folder of a project's places: its folders first, then files, hidden ones left out."""
    project = _project(project_id)
    place, target = _resolve(project, path)
    if not target.is_dir():
        raise WorkspaceError("That folder does not exist on this PC.")
    want = (match or "").strip().lower()
    entries: List[Dict[str, Any]] = []
    try:
        listing = sorted(os.scandir(target), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
    except OSError as error:
        raise WorkspaceError(f"That folder cannot be read: {error}") from error
    for entry in listing:
        if entry.name.startswith(".") or (want and want not in entry.name.lower()):
            continue
        is_dir = entry.is_dir(follow_symlinks=False)
        try:
            size = 0 if is_dir else entry.stat(follow_symlinks=False).st_size
        except OSError:
            size = 0
        entries.append({"name": entry.name, "path": str(Path(entry.path)), "dir": is_dir, "size": size,
                        "text": (not is_dir) and Path(entry.name).suffix.lower() in TEXT_EXTENSIONS})
        if len(entries) >= MAX_ENTRIES:
            break
    root = Path(place["path"]).resolve()
    return {"place": place, "path": str(target), "up": str(target.parent) if target != root else "",
            "entries": entries, "cut": len(entries) >= MAX_ENTRIES}


def add_file(project_id: str, path: str) -> Dict[str, Any]:
    """Copy one text file from the project's places into its knowledge."""
    import project_knowledge

    project = _project(project_id)
    _place, target = _resolve(project, path)
    if not target.is_file():
        raise WorkspaceError("That file does not exist on this PC.")
    if target.suffix.lower() not in TEXT_EXTENSIONS:
        raise WorkspaceError("Only text files (notes, code, csv, json and the like) can be added for now.")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise WorkspaceError("That file is too big to add. Add a smaller part of it as a note instead.")
    text = target.read_text(encoding="utf-8", errors="replace")
    try:
        return project_knowledge.add(project_id, target.name, text)
    except project_knowledge.KnowledgeError as error:
        raise WorkspaceError(str(error)) from error


def add_note(project_id: str, title: str, text: str) -> Dict[str, Any]:
    import project_knowledge

    _project(project_id)
    try:
        return project_knowledge.add(project_id, title, text)
    except project_knowledge.KnowledgeError as error:
        raise WorkspaceError(str(error)) from error


def find(project_id: str, query: str) -> Dict[str, Any]:
    """Knowledge passages that fit, plus file names in the project's local places (one level down) that match."""
    import project_knowledge

    project = _project(project_id)
    query = (query or "").strip()
    if not query:
        raise WorkspaceError("Say what to look for.")
    passages = project_knowledge.search(project_id, query)
    words = [w for w in query.lower().split() if len(w) > 2] or [query.lower()]
    files: List[Dict[str, Any]] = []
    for place in places(project):
        if place["kind"] != "local" or not Path(place["path"]).is_dir():
            continue
        for root, dirs, names in os.walk(place["path"]):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", "venv")]
            if Path(root) != Path(place["path"]) and Path(root).parent != Path(place["path"]):
                dirs[:] = []
            for name in names:
                if not name.startswith(".") and any(w in name.lower() for w in words):
                    files.append({"name": name, "path": str(Path(root) / name)})
            if len(files) >= 40:
                break
    return {"passages": passages, "files": files[:40]}


# ---------------------------------------------------------------------------
# Create AI: helpers on the project
# ---------------------------------------------------------------------------

def add_helper(project_id: str, name: str, goal: str = "") -> Dict[str, Any]:
    """Put an agent on the project. With a goal, an agent that does not exist yet is made first."""
    import projects

    _project(project_id)
    name = " ".join(str(name or "").split())[:60]
    if not name:
        raise WorkspaceError("Name the helper.")
    made = False
    if goal.strip():
        try:
            from agent_runtime import create_subagent, roster_entry

            if roster_entry(name) is None:
                create_subagent({"name": name, "goal": goal.strip()[:600]})
                made = True
        except ValueError as error:
            raise WorkspaceError(str(error)) from error
    project = projects.set_member(project_id, "agents", name)
    return {"name": name, "made": made, "project": project}


# ---------------------------------------------------------------------------
# Load balance
# ---------------------------------------------------------------------------

def balance(rows: List[Dict[str, Any]], job: str = "") -> Dict[str, Any]:
    """Where new work should go, from commander thread views. Busy or full threads are skipped; among the rest the
    emptiest with the same job wins. No good thread means a new one should start."""
    open_rows = [t for t in rows if t.get("status") != "resolved"]
    share = lambda t: float((t.get("tokens") or {}).get("share") or 0)  # noqa: E731
    load = []
    for t in open_rows:
        state = ("full" if share(t) >= FULL_AT else "busy" if t.get("status") == "working"
                 else "waiting" if t.get("status") == "needs_you" else "free")
        load.append({"title": t.get("title", ""), "status": t.get("status", ""), "job": t.get("job") or "build",
                     "share": round(share(t), 2), "state": state})
    free = [r for r in load if r["state"] == "free" and (not job or r["job"] == job)]
    free.sort(key=lambda r: r["share"])
    pick = free[0]["title"] if free else ""
    counts = {k: sum(1 for r in load if r["state"] == k) for k in ("free", "busy", "waiting", "full")}
    advice = (f"Send it to “{pick}”, the emptiest free {job or ''} thread.".replace("  ", " ") if pick
              else "Start a new thread: every fitting thread is busy, waiting on the owner or nearly full.")
    return {"threads": load, "counts": counts, "pick": pick, "advice": advice}


# ---------------------------------------------------------------------------
# Library items open in the main chat
# ---------------------------------------------------------------------------

def artifact_chat(artifact_id: str, store: Any = None) -> str:
    """The chat a Library item opens in: its thread's chat when a thread made it, else a chat made for it once."""
    import commander
    import projects

    artifact = next((a for a in projects.list_artifacts() if a["id"] == artifact_id), None)
    if artifact is None:
        raise WorkspaceError("No such item.")
    store = store or commander._store()
    ref = artifact.get("ref") or ""
    if ref.startswith("th-"):
        thread = commander.get(ref)
        if thread and store.exists(thread["chat_id"]):
            return thread["chat_id"]
    if artifact.get("chat_id") and store.exists(artifact["chat_id"]):
        return artifact["chat_id"]
    chat_id = store.create(artifact["title"], activate=False)
    where = ""
    if artifact.get("project_id"):
        project = projects.get(artifact["project_id"])
        where = f" (project “{project['name']}”)" if project else ""
    body = artifact.get("note") or "No notes kept with it yet."
    store.append("assistant", f"**{artifact['title']}** · {artifact.get('kind', 'item')}{where}\n\n{body}", chat_id=chat_id)
    projects.set_artifact_chat(artifact_id, chat_id)
    return chat_id


# ---------------------------------------------------------------------------
# Tools for a project's main chat
# ---------------------------------------------------------------------------

def _here() -> tuple:
    """(chat id, project id) of the chat this tool runs in; the project is empty unless it is a project's main chat."""
    import commander

    chat_id, _role = commander._context()
    return chat_id, (commander.delegator_project(chat_id) if commander.is_delegator(chat_id) else "")


def _guard(action) -> str:
    _chat, project_id = _here()
    if not project_id:
        return "Error: only a project's main chat can do this."
    try:
        return action(project_id)
    except WorkspaceError as error:
        return f"Error: {error}"


def tool_project_files(path: str = "", match: str = "") -> str:
    def run(project_id: str) -> str:
        project = _project(project_id)
        if not path and not places(project):
            return "This project has no folder or drive yet. Ask the owner to link one on the project home."
        found = browse(project_id, path, match)
        lines = [f"{'[folder]' if e['dir'] else '-'} {e['name']}" + ("" if e["dir"] else f" ({e['size']} bytes)")
                 for e in found["entries"]]
        others = [p["path"] for p in places(project) if p["path"] != found["place"]["path"]]
        tail = f"\nOther places: {', '.join(others)}" if others else ""
        return f"{found['path']}:\n" + ("\n".join(lines) or "(empty)") + tail
    return _guard(run)


def tool_add_project_file(path: str) -> str:
    return _guard(lambda pid: f"Added “{add_file(pid, path)['title']}” to the project's knowledge.")


def tool_add_project_note(title: str, text: str) -> str:
    return _guard(lambda pid: f"Added “{add_note(pid, title, text)['title']}” to the project's knowledge.")


def tool_find_in_project(query: str) -> str:
    def run(project_id: str) -> str:
        found = find(project_id, query)
        parts = [f"- {p.get('title', '')}: {str(p.get('text', ''))[:300]}" for p in found["passages"]]
        parts += [f"- file {f['path']}" for f in found["files"]]
        return "\n".join(parts) or "Nothing in this project matches that."
    return _guard(run)


def tool_add_helper(name: str, goal: str = "") -> str:
    def run(project_id: str) -> str:
        done = add_helper(project_id, name, goal)
        return f"{'Made' if done['made'] else 'Put'} the agent {done['name']} on this project."
    return _guard(run)


def tool_balance_threads(job: str = "") -> str:
    import commander

    chat_id, project_id = _here()
    if not project_id and not commander.is_delegator(chat_id):
        return "Error: only a Commander chat balances threads."
    found = balance(commander.threads(delegator=chat_id), job)
    lines = [f"- {r['title']} · {r['state']} · {r['job']} · {round(r['share'] * 100)}% full" for r in found["threads"]]
    return "\n".join(lines + [found["advice"]]) if lines else found["advice"]


def register_project_tools(registry: Any) -> None:
    from tools import ToolParam as P

    registry.register(
        "project_files",
        "Project main chats only: list a folder in the project's folder or drives (read-only). Empty path lists the "
        "project folder.",
        [P("path", "string", "A folder inside the project's folder or drives; empty for the project folder",
           required=False),
         P("match", "string", "Only names containing this", required=False)],
        tool_project_files, category="general", label=lambda a: f"Opening {str(a.get('path') or 'the project folder')[:50]}")
    registry.register(
        "add_project_file",
        "Project main chats only: copy a text file from the project's folder or drives into the project's knowledge, "
        "so every thread can use it.",
        [P("path", "string", "The file's path, inside the project's folder or drives")],
        tool_add_project_file, category="general", label=lambda a: f"Adding {Path(str(a.get('path', ''))).name[:50]}")
    registry.register(
        "add_project_note",
        "Project main chats only: save a note into the project's knowledge (the project's main file).",
        [P("title", "string", "A short title"), P("text", "string", "What to keep")],
        tool_add_project_note, category="general", label=lambda a: f"Saving the note {str(a.get('title', ''))[:40]}")
    registry.register(
        "find_in_project",
        "Project main chats only: look for something in the project's knowledge and file names.",
        [P("query", "string", "What to look for")],
        tool_find_in_project, category="general", label=lambda a: f"Looking for {str(a.get('query', ''))[:40]}")
    registry.register(
        "add_helper",
        "Project main chats only: put an agent on this project. Give a goal to make a new agent when none has that "
        "name.",
        [P("name", "string", "The agent's name"),
         P("goal", "string", "Only to make a new agent: what it is for", required=False)],
        tool_add_helper, category="agents", label=lambda a: f"Adding the helper {str(a.get('name', ''))[:40]}")
    registry.register(
        "balance_threads",
        "Commander chats only: how loaded each thread is (free, busy, waiting, full) and which should get new work.",
        [P("job", "string", "Only threads with this job", required=False,
           enum_values=["research", "plan", "build", "test", "review"])],
        tool_balance_threads, category="general", label="Balancing the threads")

