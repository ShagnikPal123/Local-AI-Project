"""Nyx as a code editor's partner: open a folder or one huge file, ask for a change, review the diff (Request G7).

The owner: "add that VS Code extension and add a tab for coding/file edit where I
can click the large file and I tell it to use that and can be used like Cursor,
Claude Code and Codex."

How an edit works, so nothing is written behind anyone's back:

1. **Propose** — the model sees the file (or, for a big file, the lines around the
   selection) and replies with search/replace blocks. Every block's search text
   must occur exactly once in the part it was shown, or the proposal is refused
   with the reason. The result is a unified diff plus the whole new text.
2. **Review** — the Code tab or VS Code shows the diff.
3. **Apply** — only on Accept, and only if the file has not changed since the
   proposal (hash check). The old file goes to ``data/code_backups`` first.
4. **Undo** — restores the backup while the file still matches what was applied.

Model output is written into the owner's file only after they accept it, and is
never run (AGENTS.md invariant: no executing LLM-generated code).
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from paths import atomic_replace, data_path

_LOCK = threading.Lock()
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".cache", ".idea", ".mypy_cache", ".pytest_cache"}
#: Whole-file context up to this size; bigger files are edited through a window around the selection.
WHOLE_FILE_CHARS = 120_000
WINDOW_LINES = 220
MAX_READ_LINES = 4000
LANGUAGES = {".py": "python", ".ts": "typescript", ".tsx": "tsx", ".js": "javascript", ".jsx": "jsx", ".json": "json",
             ".css": "css", ".html": "html", ".md": "markdown", ".rs": "rust", ".go": "go", ".java": "java", ".cs": "csharp",
             ".cpp": "cpp", ".c": "c", ".h": "c", ".rb": "ruby", ".php": "php", ".sql": "sql", ".yml": "yaml", ".yaml": "yaml",
             ".toml": "toml", ".ps1": "powershell", ".sh": "bash", ".bat": "batch", ".txt": "text", ".csv": "csv"}


class CodeError(ValueError):
    """A refused request, with a sentence the editor can show."""


# --- workspaces ---------------------------------------------------------------------------


def _state_path() -> Path:
    return data_path("code_workspaces.json")


def _read_state() -> Dict[str, Any]:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("workspaces", [])
            data.setdefault("proposals", [])
            return data
    except (OSError, ValueError):
        pass
    return {"workspaces": [], "proposals": []}


def _write_state(data: Dict[str, Any]) -> None:
    temp = _state_path().with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    atomic_replace(temp, _state_path())


def workspaces() -> List[Dict[str, Any]]:
    with _LOCK:
        return [w for w in _read_state()["workspaces"] if Path(w["path"]).exists()]


def open_workspace(path: str) -> Dict[str, Any]:
    """Open a folder — or a single file, whose folder becomes the workspace with that file pinned."""
    target = Path(os.path.expandvars(os.path.expanduser((path or "").strip().strip('"')))).resolve()
    if not target.exists():
        raise CodeError(f"Nothing at {target}. Paste the full path of a folder or file.")
    root = target if target.is_dir() else target.parent
    entry = {"id": hashlib.sha1(str(root).lower().encode()).hexdigest()[:10], "path": str(root), "name": root.name or str(root),
             "opened_at": time.time(), "file": str(target) if target.is_file() else ""}
    with _LOCK:
        data = _read_state()
        data["workspaces"] = [entry] + [w for w in data["workspaces"] if w["id"] != entry["id"]][:19]
        _write_state(data)
    return entry


def close_workspace(workspace_id: str) -> None:
    with _LOCK:
        data = _read_state()
        data["workspaces"] = [w for w in data["workspaces"] if w["id"] != workspace_id]
        _write_state(data)


def resolve(path: str) -> Path:
    """A path inside an opened workspace. Anything else is refused: opening is the owner's consent."""
    target = Path(os.path.expandvars((path or "").strip().strip('"'))).resolve()
    for workspace in workspaces():
        root = Path(workspace["path"]).resolve()
        if target == root or root in target.parents:
            return target
    raise CodeError("Open the folder (or file) in the Code tab first — Nyx only edits inside folders you opened.")


def tree(path: str, limit: int = 400) -> List[Dict[str, Any]]:
    folder = resolve(path)
    if not folder.is_dir():
        raise CodeError("That is a file, not a folder.")
    entries = []
    try:
        children = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as error:
        raise CodeError(f"Can't read that folder: {error}") from error
    for child in children:
        if child.name in SKIP_DIRS or child.name.startswith(".") and child.name not in (".env.example", ".gitignore"):
            continue
        try:
            size = child.stat().st_size if child.is_file() else 0
        except OSError:
            size = 0
        entries.append({"name": child.name, "path": str(child), "dir": child.is_dir(), "size": size})
        if len(entries) >= limit:
            break
    return entries


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def _read_text(target: Path) -> str:
    if not target.is_file():
        raise CodeError("That file does not exist.")
    raw = target.read_bytes()
    if b"\x00" in raw[:4096]:
        raise CodeError("That looks like a binary file; Nyx edits text files.")
    for encoding in ("utf-8", "utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _lf(text: str) -> Tuple[str, str]:
    """Work in LF; remember whether the file uses CRLF so writes keep its line endings."""
    return (text.replace("\r\n", "\n"), "\r\n") if "\r\n" in text else (text, "\n")


def _with_eol(text: str, eol: str) -> str:
    return text.replace("\n", "\r\n") if eol == "\r\n" else text


def read(path: str, start: int = 1, end: Optional[int] = None) -> Dict[str, Any]:
    """Lines ``start``..``end`` (1-based, inclusive) of a file, capped so huge files load in pieces."""
    target = resolve(path)
    raw = _read_text(target)
    text, _eol = _lf(raw)
    lines = text.split("\n")
    total = len(lines)
    start = max(1, int(start or 1))
    end = min(total, int(end) if end else start + MAX_READ_LINES - 1, start + MAX_READ_LINES - 1)
    return {"path": str(target), "name": target.name, "language": LANGUAGES.get(target.suffix.lower(), "text"),
            "size": target.stat().st_size, "total_lines": total, "start": start, "end": end,
            "text": "\n".join(lines[start - 1:end]), "hash": _hash(raw)}


def save(path: str, text: str, base_hash: str) -> Dict[str, Any]:
    """The owner's own edit from the editor, with the same conflict check and backup as an accepted proposal."""
    target = resolve(path)
    current = _read_text(target) if target.exists() else ""
    if base_hash and current and _hash(current) != base_hash:
        raise CodeError("The file changed on disk since you opened it. Reload it, then save again.")
    backup = _backup(target, current)
    written = _with_eol(text.replace("\r\n", "\n"), _lf(current)[1] if current else "\n")
    _write_text(target, written)
    return {"path": str(target), "hash": _hash(written), "backup": backup}


def search(root: str, query: str, limit: int = 80) -> List[Dict[str, Any]]:
    folder = resolve(root)
    needle = (query or "").strip()
    if not needle:
        return []
    hits: List[Dict[str, Any]] = []
    lowered = needle.lower()
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for filename in filenames:
            path = Path(dirpath) / filename
            if path.suffix.lower() not in LANGUAGES:
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    continue
                for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").split("\n"), start=1):
                    if lowered in line.lower():
                        hits.append({"path": str(path), "line": number, "text": line.strip()[:200]})
                        if len(hits) >= limit:
                            return hits
            except OSError:
                continue
    return hits


# --- proposals ------------------------------------------------------------------------------

EDIT_SYSTEM = (
    "You are a precise senior engineer editing one file for the owner. Make only the change asked for, match the file's "
    "existing style, and keep everything else byte-for-byte identical. Reply with JSON only: "
    '{"explanation": "one or two sentences", "edits": [{"find": "exact text copied from the file, enough lines to be unique", '
    '"replace": "the new text"}]}. To add code, find a nearby unique line and replace it with that line plus the addition. '
    "Never use placeholders like '...existing code...'."
)


def _intent_for(target: Path) -> str:
    """The nearest intent.md inside the opened folder (Request H14)."""
    import intent_md

    root = next((Path(w["path"]) for w in workspaces() if target == Path(w["path"]) or Path(w["path"]) in target.parents), None)
    return intent_md.read_for(str(target), stop_at=str(root) if root else None)


def _windowed(lines: List[str], start: Optional[int], end: Optional[int]) -> tuple[int, int]:
    if start and end:
        lo, hi = max(1, start - 40), min(len(lines), end + 40)
    else:
        lo, hi = 1, min(len(lines), WINDOW_LINES)
    return lo, hi


def propose(path: str, instruction: str, start_line: Optional[int] = None, end_line: Optional[int] = None,
            context_paths: Optional[List[str]] = None) -> Dict[str, Any]:
    """Ask the code model for an edit and turn it into a reviewable diff. Nothing is written."""
    from model_roles import MODEL_ROLES
    from tools import _loads_lenient

    if not (instruction or "").strip():
        raise CodeError("Say what to change, e.g. “add input validation to save()”.")
    target = resolve(path)
    raw = _read_text(target)
    text, eol = _lf(raw)
    lines = text.split("\n")
    whole = len(text) <= WHOLE_FILE_CHARS and not (start_line and end_line and len(text) > 40_000)
    if whole:
        lo, hi = 1, len(lines)
    else:
        lo, hi = _windowed(lines, start_line, end_line)
    shown = "\n".join(lines[lo - 1:hi])
    focus = f"\nFocus on lines {start_line}–{end_line}." if start_line and end_line else ""
    extra = ""
    for other in (context_paths or [])[:3]:
        try:
            other_text = _read_text(resolve(other))[:20_000]
            extra += f"\n\nRelated file {Path(other).name} (read only):\n```\n{other_text}\n```"
        except CodeError:
            continue
    intent = _intent_for(target)
    if intent:
        extra += f"\n\nThe project's intent.md (keep the change inside it; say if the request contradicts it):\n{intent}"
    prompt = (f"File: {target.name} ({LANGUAGES.get(target.suffix.lower(), 'text')}), "
              f"{'the whole file' if whole else f'lines {lo}–{hi} of {len(lines)}'}:\n```\n{shown}\n```"
              f"{extra}\n\nChange requested: {instruction.strip()}{focus}")
    run = MODEL_ROLES.run("code_generation", prompt, system=EDIT_SYSTEM, max_tokens=6000)
    reply = run.text
    data = _loads_lenient(reply[reply.find("{"): reply.rfind("}") + 1]) if "{" in reply else None
    if not isinstance(data, dict) or not isinstance(data.get("edits"), list) or not data["edits"]:
        raise CodeError(f"{run.label} did not return a usable edit. Try rephrasing the change.")

    new_shown = shown
    for number, edit in enumerate(data["edits"], start=1):
        find, replace = str(edit.get("find", "")), str(edit.get("replace", ""))
        if not find:
            raise CodeError(f"Edit {number} had nothing to find.")
        count = new_shown.count(find)
        if count == 0:
            # Models often normalise trailing whitespace; try once with it stripped per line.
            relaxed = "\n".join(l.rstrip() for l in find.split("\n"))
            if relaxed and new_shown.count(relaxed) == 1:
                find, count = relaxed, 1
        if count != 1:
            raise CodeError(f"{run.label}'s edit {number} {'did not match the file' if count == 0 else 'matched more than one place'} — nothing was changed. Try again or select the lines to change.")
        new_shown = new_shown.replace(find, replace, 1)

    new_text = "\n".join(lines[:lo - 1] + new_shown.split("\n") + lines[hi:])
    diff = "".join(difflib.unified_diff(text.splitlines(keepends=True), new_text.splitlines(keepends=True),
                                        fromfile=f"a/{target.name}", tofile=f"b/{target.name}", n=3))
    proposal = {"id": uuid.uuid4().hex[:12], "path": str(target), "name": target.name, "instruction": instruction.strip()[:500],
                "explanation": str(data.get("explanation", "")).strip()[:600], "base_hash": _hash(raw), "diff": diff,
                "new_text": _with_eol(new_text, eol), "model": run.label, "status": "proposed", "created_at": time.time(),
                "added": sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")),
                "removed": sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))}
    try:  # which lines of which file, for the review card (Request R9)
        import diff_stats

        proposal["lines"] = diff_stats.from_texts(text, new_text, target.name)
    except Exception:  # noqa: BLE001 - the counts above still describe it
        pass
    with _LOCK:
        data_state = _read_state()
        data_state["proposals"] = [proposal] + data_state["proposals"][:49]
        _write_state(data_state)
    return _public(proposal)


def _public(proposal: Dict[str, Any], include_text: bool = False) -> Dict[str, Any]:
    public = {k: v for k, v in proposal.items() if include_text or k != "new_text"}
    if not include_text and isinstance(public.get("files"), list):
        public["files"] = [{k: v for k, v in f.items() if k != "content"} for f in public["files"]]
    return public


def proposals(path: str = "") -> List[Dict[str, Any]]:
    with _LOCK:
        items = _read_state()["proposals"]
    wanted = str(Path(path).resolve()) if path else ""
    return [_public(p) for p in items if not wanted or p["path"] == wanted]


def get_proposal(proposal_id: str, include_text: bool = True) -> Dict[str, Any]:
    with _LOCK:
        found = next((p for p in _read_state()["proposals"] if p["id"] == proposal_id), None)
    if found is None:
        raise KeyError(proposal_id)
    return _public(found, include_text)


def _backup(target: Path, text: str) -> str:
    folder = data_path("code_backups")
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{time.strftime('%Y%m%d-%H%M%S')}_{uuid.uuid4().hex[:6]}_{target.name}"
    (folder / name).write_bytes(text.encode("utf-8", "surrogatepass"))
    return str(folder / name)


def _write_text(target: Path, text: str) -> None:
    temp = target.with_name(f".{target.name}.nyx-tmp")
    temp.write_bytes(text.encode("utf-8", "surrogatepass"))
    atomic_replace(temp, target)


def _set_status(proposal_id: str, **changes: Any) -> Dict[str, Any]:
    with _LOCK:
        data = _read_state()
        found = next((p for p in data["proposals"] if p["id"] == proposal_id), None)
        if found is None:
            raise KeyError(proposal_id)
        found.update(changes)
        _write_state(data)
        return dict(found)


def apply(proposal_id: str) -> Dict[str, Any]:
    proposal = get_proposal(proposal_id)
    if proposal["status"] != "proposed":
        raise CodeError(f"That change is already {proposal['status']}.")
    if proposal.get("kind") == "create":
        return _apply_create(proposal)
    target = resolve(proposal["path"])
    current = _read_text(target)
    if _hash(current) != proposal["base_hash"]:
        _set_status(proposal_id, status="stale")
        raise CodeError("The file changed since Nyx proposed this. Ask again so the edit matches the current file.")
    backup = _backup(target, current)
    _write_text(target, proposal["new_text"])
    return _public(_set_status(proposal_id, status="applied", backup=backup, applied_hash=_hash(proposal["new_text"]),
                               applied_at=time.time()))


def reject(proposal_id: str, status: str = "rejected") -> Dict[str, Any]:
    if status not in ("rejected", "applied_in_editor"):
        raise CodeError("Unknown status.")
    return _public(_set_status(proposal_id, status=status, resolved_at=time.time()))


def undo(proposal_id: str) -> Dict[str, Any]:
    proposal = get_proposal(proposal_id)
    if proposal.get("kind") == "create" and proposal["status"] == "applied":
        return _undo_create(proposal)
    if proposal["status"] != "applied" or not proposal.get("backup"):
        raise CodeError("Only a change Nyx applied can be undone here.")
    target = resolve(proposal["path"])
    if _hash(_read_text(target)) != proposal.get("applied_hash"):
        raise CodeError("The file was edited after this change, so undoing it would lose that work. Use your editor's history.")
    _write_text(target, _read_text(Path(proposal["backup"])))
    return _public(_set_status(proposal_id, status="undone", undone_at=time.time()))


ASK_SYSTEM = "You are a senior engineer explaining code to its owner. Be concrete: name functions and lines. Markdown."


def ask(path: str, question: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> Dict[str, Any]:
    from model_roles import MODEL_ROLES

    target = resolve(path)
    text, _eol = _lf(_read_text(target))
    lines = text.split("\n")
    if len(text) > WHOLE_FILE_CHARS or (start_line and end_line):
        lo, hi = _windowed(lines, start_line, end_line)
    else:
        lo, hi = 1, len(lines)
    numbered = "\n".join(f"{n:>5}  {line}" for n, line in enumerate(lines[lo - 1:hi], start=lo))
    run = MODEL_ROLES.run("code_generation", f"File {target.name}, lines {lo}–{hi} of {len(lines)}:\n```\n{numbered}\n```\n\n"
                          f"Question: {(question or 'Explain what this code does.').strip()}", system=ASK_SYSTEM, max_tokens=2500)
    return {"answer": run.text.strip(), "model": run.label, "lines": [lo, hi]}


# --- new files, new folders, starting from scratch (Request H12) ------------------------------
#
# "Make sure I can make new files in there, and have it do things without having things in there.
# Start from scratch as an option, and in there I can open an empty or premade folder or make a
# new folder."

_BAD_NAME_CHARS = set('<>:"|?*')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def _check_name(name: str) -> str:
    clean = (name or "").strip().strip(". ")
    if not clean:
        raise CodeError("Give it a name.")
    if any(ch in _BAD_NAME_CHARS for ch in clean) or clean.split(".")[0].lower() in _RESERVED:
        raise CodeError(f"“{clean}” can't be used as a name on Windows (no < > : \" | ? * and not CON, NUL…).")
    return clean


def _inside_new(path: str) -> Path:
    """A path that may not exist yet, inside an opened folder, with a usable name."""
    target = Path(os.path.expandvars((path or "").strip().strip('"'))).resolve()
    _check_name(target.name)
    folder = target.parent
    while not folder.exists() and folder != folder.parent:
        _check_name(folder.name)
        folder = folder.parent
    resolve(str(folder))
    return target


def create_file(path: str, text: str = "") -> Dict[str, Any]:
    target = _inside_new(path)
    if target.exists():
        raise CodeError(f"{target.name} already exists — open it instead.")
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_text(target, text or "")
    return {"path": str(target), "name": target.name, "hash": _hash(text or "")}


def create_folder(path: str) -> Dict[str, Any]:
    target = _inside_new(path)
    if target.exists():
        raise CodeError(f"{target.name} already exists.")
    target.mkdir(parents=True)
    return {"path": str(target), "name": target.name}


#: Starter folders. Plain text files only — nothing here is run, installed or downloaded.
TEMPLATES: Dict[str, Dict[str, Any]] = {
    "empty": {"label": "Empty folder", "description": "Nothing in it yet — ask Nyx to build something.", "files": {}},
    "python": {"label": "Python project", "description": "main.py, requirements.txt, README and .gitignore.", "files": {
        "main.py": 'def main() -> None:\n    print("Hello from {name}")\n\n\nif __name__ == "__main__":\n    main()\n',
        "requirements.txt": "",
        "README.md": "# {name}\n\nRun it:\n\n```\npython main.py\n```\n",
        ".gitignore": "__pycache__/\n.venv/\n*.pyc\n.env\n",
    }},
    "website": {"label": "Website", "description": "index.html, style.css and script.js — open index.html in a browser.", "files": {
        "index.html": '<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1">\n  <title>{name}</title>\n  <link rel="stylesheet" href="style.css">\n</head>\n<body>\n  <main>\n    <h1>{name}</h1>\n    <p>Edit index.html to start.</p>\n  </main>\n  <script src="script.js"></script>\n</body>\n</html>\n',
        "style.css": ":root { color-scheme: light dark; font-family: system-ui, sans-serif; }\nbody { margin: 0; }\nmain { max-width: 720px; margin: 64px auto; padding: 0 16px; }\n",
        "script.js": "console.log('{name} loaded');\n",
    }},
    "node": {"label": "Node.js app", "description": "package.json and index.js (run npm install yourself).", "files": {
        "package.json": '{\n  "name": "{slug}",\n  "version": "0.1.0",\n  "private": true,\n  "type": "module",\n  "scripts": { "start": "node index.js" }\n}\n',
        "index.js": "console.log('Hello from {name}');\n",
        "README.md": "# {name}\n\n```\nnpm start\n```\n",
        ".gitignore": "node_modules/\n.env\n",
    }},
    "arduino": {"label": "Arduino sketch", "description": "A .ino sketch for the Arduino IDE (pairs with the Build tab).", "files": {
        "{slug}/{slug}.ino": "void setup() {\n  Serial.begin(115200);\n  pinMode(LED_BUILTIN, OUTPUT);\n}\n\nvoid loop() {\n  digitalWrite(LED_BUILTIN, HIGH);\n  delay(500);\n  digitalWrite(LED_BUILTIN, LOW);\n  delay(500);\n}\n",
        "README.md": "# {name}\n\nOpen `{slug}/{slug}.ino` in the Arduino IDE, pick your board and port, then Upload.\n",
    }},
}


def templates() -> List[Dict[str, str]]:
    return [{"id": key, "label": value["label"], "description": value["description"]} for key, value in TEMPLATES.items()]


def start_project(parent: str, name: str, template: str = "empty") -> Dict[str, Any]:
    """Make a new folder under ``parent`` (a folder the owner chose), fill it from a template, and open it."""
    base = Path(os.path.expandvars(os.path.expanduser((parent or "").strip().strip('"')))).resolve()
    if not base.is_dir():
        raise CodeError(f"{base} isn't a folder. Choose where the new folder should go.")
    clean = _check_name(name)
    spec = TEMPLATES.get(template or "empty")
    if spec is None:
        raise CodeError("Unknown starter.")
    root = base / clean
    if root.exists() and any(root.iterdir()):
        raise CodeError(f"{root} already exists and isn't empty — open it instead.")
    root.mkdir(parents=True, exist_ok=True)
    slug = "".join(ch if ch.isalnum() else "-" for ch in clean.lower()).strip("-") or "project"
    import intent_md

    _write_text(root / "intent.md", intent_md.template(clean))
    for relative, content in spec["files"].items():
        file_path = root / relative.replace("{slug}", slug)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        _write_text(file_path, content.replace("{name}", clean).replace("{slug}", slug))
    return open_workspace(str(root))


CREATE_SYSTEM = (
    "You are a senior engineer creating new files for the owner in a project folder. Reply with JSON only: "
    '{"explanation": "one or two sentences", "files": [{"path": "relative/path.ext", "content": "the whole file"}]}. '
    "Use relative paths with forward slashes, no '..'. Complete, working files — never placeholders. "
    "Keep it as small as the request allows."
)


def _listing(root: Path, limit: int = 120) -> str:
    rows = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for filename in filenames:
            rows.append(str((Path(dirpath) / filename).relative_to(root)).replace("\\", "/"))
            if len(rows) >= limit:
                return "\n".join(rows) + "\n…"
    return "\n".join(rows) or "(the folder is empty)"


def propose_files(root: str, instruction: str) -> Dict[str, Any]:
    """New files for a folder — including an empty one — as a proposal to review. Nothing is written."""
    from model_roles import MODEL_ROLES
    from tools import _loads_lenient

    if not (instruction or "").strip():
        raise CodeError("Say what to build, e.g. “a to-do list web page”.")
    folder = resolve(root)
    if not folder.is_dir():
        raise CodeError("Choose a folder to build in.")
    intent = _intent_for(folder)
    prompt = (f"Project folder: {folder.name}\nFiles already there:\n{_listing(folder)}\n\n"
              + (f"The project's intent.md (build inside it):\n{intent}\n\n" if intent else "")
              + f"Build: {instruction.strip()}")
    run = MODEL_ROLES.run("code_generation", prompt, system=CREATE_SYSTEM, max_tokens=12000)
    reply = run.text
    data = _loads_lenient(reply[reply.find("{"): reply.rfind("}") + 1]) if "{" in reply else None
    items = data.get("files") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise CodeError(f"{run.label} did not return any files. Try describing what to build in more detail.")
    files, skipped = [], []
    for item in items[:40]:
        relative = str((item or {}).get("path", "")).strip().lstrip("/\\").replace("\\", "/")
        content = str((item or {}).get("content", ""))
        target = (folder / relative).resolve()
        if not relative or ".." in relative.split("/") or folder not in target.parents:
            skipped.append(relative or "(no name)")
            continue
        try:
            for part in relative.split("/"):
                _check_name(part)
        except CodeError:
            skipped.append(relative)
            continue
        if target.exists():
            skipped.append(f"{relative} (already exists)")
            continue
        files.append({"path": str(target), "relative": relative, "content": content, "lines": content.count("\n") + 1})
    if not files:
        raise CodeError("Every file the model suggested already exists or had an unusable name: " + ", ".join(skipped[:6]))
    diff = "".join("".join(difflib.unified_diff([], f["content"].splitlines(keepends=True), fromfile="/dev/null",
                                                tofile=f"b/{f['relative']}", n=0)) for f in files)
    proposal = {"id": uuid.uuid4().hex[:12], "kind": "create", "path": str(folder), "name": folder.name,
                "instruction": instruction.strip()[:500], "explanation": str(data.get("explanation", "")).strip()[:600],
                "files": files, "skipped": skipped, "diff": diff, "model": run.label, "status": "proposed",
                "created_at": time.time(), "added": sum(f["lines"] for f in files), "removed": 0}
    try:
        import diff_stats

        proposal["lines"] = diff_stats.stats(diff)
    except Exception:  # noqa: BLE001
        pass
    with _LOCK:
        state = _read_state()
        state["proposals"] = [proposal] + state["proposals"][:49]
        _write_state(state)
    return _public(proposal)


def _apply_create(proposal: Dict[str, Any]) -> Dict[str, Any]:
    resolve(proposal["path"])
    clashes = [f["relative"] for f in proposal["files"] if Path(f["path"]).exists()]
    if clashes:
        _set_status(proposal["id"], status="stale")
        raise CodeError("These files appeared since the proposal: " + ", ".join(clashes[:6]) + ". Ask again.")
    written = []
    for item in proposal["files"]:
        target = Path(item["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_text(target, item["content"])
        written.append({"path": str(target), "hash": _hash(item["content"])})
    return _public(_set_status(proposal["id"], status="applied", written=written, applied_at=time.time()))


def _undo_create(proposal: Dict[str, Any]) -> Dict[str, Any]:
    edited = [w["path"] for w in proposal.get("written", []) if Path(w["path"]).exists()
              and _hash(_read_text(Path(w["path"]))) != w["hash"]]
    if edited:
        raise CodeError("Some created files were edited since, so undo would lose that work: "
                        + ", ".join(Path(p).name for p in edited[:5]))
    root = Path(proposal["path"])
    for item in proposal.get("written", []):
        target = Path(item["path"])
        if target.exists():
            target.unlink()
        parent = target.parent
        while parent != root and root in parent.parents and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    return _public(_set_status(proposal["id"], status="undone", undone_at=time.time()))
