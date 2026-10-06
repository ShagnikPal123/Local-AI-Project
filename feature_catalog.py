"""Everything Nyx can do, and what is running right now — found, not listed.

The owner (2026-09-22): "In the nyx chat tab for the background processes update
it so that it can also see background processes for everything new. At times it
doesn't know about the new features and make sure it actively searches and sees.
Add all features running to a file or a catalog and it reads from there as well
as how much is being used."

The old list of background processes was written by hand, so every feature built
after it was invisible — which is exactly what the owner noticed. Nothing here is
a list of features. It is a scan:

* **What exists** comes from the live app: the tools registered this run, the
  routes FastAPI actually serves, the tabs that exist, the model roles, and every
  module in the project with the first line of its docstring.
* **What is running** comes from what the process really holds: every worker
  thread Nyx's own code started, every child process it spawned, Big Kahuna's
  training jobs (separate processes that outlive a restart), and every module
  that answers ``background_status()``. A feature built next month appears the
  moment it starts a thread — nobody has to remember to add it anywhere. A table
  below gives known thread names nicer words; it never decides what is visible.
* **How much it is used** is counted here and kept in ``data/feature_catalog.json``,
  so "which of this do I actually use?" has an answer.

`summary(...)` is what the model reads through the ``feature_catalog`` tool.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from paths import PROJECT_DIR, data_path

#: A scan is reused for this long; the file is written each time.
SCAN_TTL_SECONDS = 300.0

_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None
_cached_at = 0.0


def _store_path() -> Path:
    return data_path("feature_catalog.json")


def _read_store() -> Dict[str, Any]:
    try:
        data = json.loads(_store_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_store(data: Dict[str, Any]) -> None:
    try:
        _store_path().write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Counting use
# ---------------------------------------------------------------------------


def note(kind: str, name: str, count: int = 1) -> None:
    """One more use of a tool, a tab, a model role. Cheap and never raises."""
    if not name:
        return
    try:
        with _lock:
            store = _read_store()
            uses = store.setdefault("uses", {})
            row = uses.setdefault(f"{kind}:{name}", {"count": 0, "last": 0.0})
            row["count"] = int(row.get("count", 0)) + count
            row["last"] = time.time()
            _write_store(store)
    except Exception:  # pragma: no cover - counting must never break a turn
        pass


def uses() -> Dict[str, Dict[str, Any]]:
    return dict(_read_store().get("uses", {}))


def used(kind: str, name: str) -> int:
    return int(uses().get(f"{kind}:{name}", {}).get("count", 0))


# ---------------------------------------------------------------------------
# What exists
# ---------------------------------------------------------------------------


def _tools() -> List[Dict[str, Any]]:
    try:
        from tools import TOOL_REGISTRY

        rows = []
        for tool in TOOL_REGISTRY.list_tools():
            name = str(getattr(tool, "name", ""))
            rows.append({"name": name, "category": str(getattr(tool, "category", "")),
                         "what": str(getattr(tool, "description", ""))[:120], "used": used("tool", name)})
        return sorted(rows, key=lambda row: (-row["used"], row["name"]))
    except Exception:  # noqa: BLE001
        return []


def _routes() -> List[Dict[str, Any]]:
    try:
        import server

        rows = []
        for route in server.app.routes:
            path = getattr(route, "path", "")
            methods = sorted(getattr(route, "methods", []) or [])
            if not path.startswith("/api"):
                continue
            rows.append({"path": path, "methods": [m for m in methods if m != "HEAD"]})
        return sorted(rows, key=lambda row: row["path"])
    except Exception:  # noqa: BLE001
        return []


def _tabs() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        from landscape_tools import CORE_TABS

        rows += [{"id": key, "label": label, "kind": "built-in", "used": used("tab", key)}
                 for key, label in CORE_TABS.items()]
    except Exception:  # noqa: BLE001
        pass
    try:
        from dynamic_tabs import TAB_STORE

        rows += [{"id": str(t.get("id")), "label": str(t.get("label") or t.get("id")), "kind": "made here",
                  "used": used("tab", str(t.get("id")))} for t in TAB_STORE.list_tabs()]
    except Exception:  # noqa: BLE001
        pass
    return rows


def _roles() -> List[Dict[str, Any]]:
    try:
        from model_roles import MODEL_ROLES

        return [{"role": key, "title": entry.get("title", key), "provider": entry.get("provider", ""),
                 "model": entry.get("model", ""), "used": used("role", key)}
                for key, entry in MODEL_ROLES.list_all().items()]
    except Exception:  # noqa: BLE001
        return []


def _modules() -> List[Dict[str, Any]]:
    """Every module in the project, with the first line of its docstring.

    Read from the files, not from imports: a feature that is not loaded in this
    process is still a feature, and reading a line of text costs nothing.
    """
    rows: List[Dict[str, Any]] = []
    root = PROJECT_DIR
    skip = {".venv", ".venv.broken", "node_modules", "__pycache__", "tests", "local_pytest_tmp",
            "local_pytest_tmp - Copy", "openai_mcp", "openai_mcp - Copy", "_archive", "dist", "build"}
    try:
        for path in sorted(root.glob("*.py")) + sorted(root.glob("*/[a-z]*.py")):
            if any(part in skip for part in path.parts):
                continue
            try:
                head = path.read_text(encoding="utf-8", errors="ignore")[:400]
            except OSError:
                continue
            line = ""
            if head.lstrip().startswith(('"""', "'''")):
                body = head.lstrip()[3:]
                line = body.split("\n", 1)[0].strip().rstrip('"""').strip()
            rows.append({"module": str(path.relative_to(root)).replace("\\", "/"), "what": line[:140],
                         "kb": round(path.stat().st_size / 1024, 1)})
    except Exception:  # noqa: BLE001
        pass
    return rows


def scan(force: bool = False) -> Dict[str, Any]:
    """Build the catalog. Cached for a few minutes; the file is always rewritten."""
    global _cache, _cached_at
    if not force and _cache is not None and time.time() - _cached_at < SCAN_TTL_SECONDS:
        return _cache
    catalog = {
        "scanned_at": time.time(),
        "tools": _tools(),
        "tabs": _tabs(),
        "roles": _roles(),
        "routes": _routes(),
        "modules": _modules(),
    }
    catalog["counts"] = {key: len(catalog[key]) for key in ("tools", "tabs", "roles", "routes", "modules")}
    with _lock:
        store = _read_store()
        known = set(store.get("known_modules") or [])
        now = {row["module"] for row in catalog["modules"]}
        catalog["new_modules"] = sorted(now - known) if known else []
        store["known_modules"] = sorted(now)
        store["last_scan"] = catalog["scanned_at"]
        store["counts"] = catalog["counts"]
        _write_store(store)
    _cache, _cached_at = catalog, time.time()
    return catalog


# ---------------------------------------------------------------------------
# What is running
# ---------------------------------------------------------------------------
#
# Every row has one shape, however it was found: kind, id, label, detail, status,
# source ("probe" | "module" | "thread" | "subprocess"), group ("job" — work that
# ends; "service" — a loop that is always on), tab (where to watch it, "" if
# nowhere) and, when known, seconds and progress (0..1).

#: Words for the threads Nyx names (``threading.Thread(name="nyx-research-<id>")``):
#: the label, the tab that shows the work, and job or service. Words only — a name
#: missing here still shows, cleaned up ("nyx-new-thing-3f2a9c" → "New thing"), as
#: a job. More specific prefixes come first.
_THREAD_WORDS: List[tuple] = [
    ("nyx-turn-", "Answering", "nyx", "job"),
    ("nyx-agent-", "Sub-agent working", "subagents", "job"),
    ("nyx-dispatch-", "Agent box", "nyx", "job"),
    ("nyx-research-", "Research", "research", "job"),
    ("nyx-absorb-", "Data absorption", "absorb", "job"),
    ("nyx-data-", "Data process", "absorb", "job"),
    ("nyx-apply-rebuild", "Rebuilding the app", "apply", "job"),
    ("nyx-apply-", "Apply", "apply", "job"),
    ("nyx-build-", "Build Studio", "build", "job"),
    ("nyx-zone-tab-", "Command Zone · making a tab", "nyx", "job"),
    ("nyx-deep-", "Improve · deep mode", "improve", "job"),
    ("nyx-implement-", "Implementing a change", "improve", "job"),
    ("nyx-review-", "Reviewing changes", "improve", "job"),
    ("nyx-improve-", "Code analysis", "improve", "job"),
    ("nyx-autopilot-", "Improve autopilot", "improve", "job"),
    ("nyx-install-ollama", "Installing Ollama", "models", "job"),
    ("nyx-local-", "Local model download", "models", "job"),
    ("nyx-finder-", "Model finder", "models", "job"),
    ("nyx-brain-seed", "Seeding the brain", "nyx", "job"),
    ("nyx-brain-first-run", "Growing the brain (first run)", "nyx", "job"),
    ("nyx-core-learner", "Nyx Core learning", "nyx", "job"),
    ("nyx-connector-warmup", "Checking connectors", "connectors", "job"),
    ("nyx-folder-picker", "Folder picker", "", "job"),
    ("nyx-picker-present", "Folder picker", "", "job"),
    ("nyx-trading-autopilot", "Trading autopilot", "trading", "service"),
    ("nyx-idle-scheduler", "Idle scheduler", "", "service"),
    ("nyx-storage-budget", "Storage budget", "settings", "service"),
    ("nyx-brain-writer", "Brain writer", "nyx", "service"),
    ("nyx-computer-watch", "Computer control watch", "", "service"),
    ("nyx-admin-server", "Admin server", "admin", "service"),
    ("kahuna-judge", "Big Kahuna · judge", "kahuna", "service"),
    ("kahuna-lead", "Big Kahuna · leading", "kahuna", "job"),
    ("kahuna-warm", "Big Kahuna · warming up", "kahuna", "job"),
    ("kahuna-shadow", "Big Kahuna · shadow answer", "kahuna", "job"),
    ("kahuna-score", "Big Kahuna · scoring", "kahuna", "job"),
    ("kahuna-serve-exit", "Big Kahuna · stopping its server", "kahuna", "job"),
    ("office-", "Office Space job", "office", "job"),
    ("finance-simulator", "Finance simulator", "trading", "job"),
    ("thought-", "Thinking", "nyx", "job"),
    ("voice-", "Voice", "nyx", "job"),
]

#: Threads that are the engine itself or a library's plumbing, never a feature: the
#: server, its request workers, and pools whose work the job that owns them reports.
_PLUMBING = ("MainThread", "ThreadPoolExecutor", "asyncio_", "waitpid", "AnyIO", "uvicorn", "Dummy-", "pydevd",
             "nyx-engine")

#: Child processes that are Windows' or a shell's own helpers, not work.
_HELPER_PROCESSES = frozenset({"conhost.exe", "cmd.exe", "sh.exe", "bash.exe"})


def _row(kind: str, row_id: Any, label: str, *, detail: Any = "", status: str = "running", source: str,
         group: str = "job", tab: str = "", seconds: Any = None, progress: Any = None, **extra: Any) -> Dict[str, Any]:
    row = {"kind": kind, "id": str(row_id), "label": str(label)[:80], "detail": str(detail or "")[:90],
           "status": str(status or "running"), "source": source, "group": group if group in ("job", "service") else "job",
           "tab": str(tab or "")}
    if isinstance(seconds, (int, float)):
        row["seconds"] = max(0, round(float(seconds)))
    if isinstance(progress, (int, float)):
        row["progress"] = round(max(0.0, min(1.0, float(progress))), 3)
    row.update(extra)
    return row


def _since(started: Any) -> Optional[float]:
    try:
        return time.time() - float(started) if started else None
    except (TypeError, ValueError):
        return None


# --- probes: the registries that know more than a thread name does -------------------------------
# Each turns one registry into rows with real words and progress. A probe that breaks
# costs only its own rows; the thread scan below still shows the work underneath it.

def _probe_turns(module: Any) -> List[Dict[str, Any]]:
    return [_row("turn", t["turn_id"], "Answering", detail=t["message"], status=t["status"], source="probe",
                 tab="nyx", seconds=t.get("elapsed_seconds"), chat_id=t.get("chat_id", ""))
            for t in module.TURNS.active(include_recent=False)]


def _probe_autopilot(module: Any) -> List[Dict[str, Any]]:
    run = module.AUTOPILOT.active()
    if not run:
        return []
    progress = None
    if run.get("remaining_seconds") is not None and run.get("ends_at"):
        total = max(1.0, float(run["ends_at"]) - float(run["created_at"]))
        progress = 1 - float(run["remaining_seconds"]) / total
    return [_row("autopilot", run["run_id"], f"Improve autopilot · {run['phase']['kind']}", detail=run.get("work", ""),
                 status=run["status"], source="probe", tab="improve", seconds=_since(run.get("created_at")),
                 progress=progress)]


def _probe_analysis(module: Any) -> List[Dict[str, Any]]:
    return [_row("analysis", s["session_id"], "Code analysis", detail=s.get("progress", ""), status=s["status"],
                 source="probe", tab="improve", seconds=s.get("elapsed_seconds"))
            for s in module.ENGINE.list_sessions()[:3] if s["status"] in ("running", "stopping")]


def _probe_review(module: Any) -> List[Dict[str, Any]]:
    job = module.REVIEW_QUEUE.job()
    if not job or job.get("status") != "running":
        return []
    progress = job["done"] / job["total"] if job.get("total") else None
    return [_row("review", job["id"], "Reviewing changes", detail=job.get("now", ""), source="probe", tab="improve",
                 seconds=_since(job.get("started_at")), progress=progress)]


def _probe_dispatches(module: Any) -> List[Dict[str, Any]]:
    rows = []
    for dispatch in module.DISPATCHES.list(active_only=True):
        counts = dispatch["counts"]
        total = len(dispatch["instances"]) or 1
        names = " + ".join(f"{n}× {a}" if n > 1 else a for a, n in dispatch["agents"].items())
        rows.append(_row("dispatch", dispatch["dispatch_id"], f"Agents: {names}"[:60],
                         detail=f"{counts['working']} working · {counts['done']} done · {counts['queued']} waiting",
                         source="probe", tab="nyx", seconds=_since(dispatch.get("created_at")),
                         progress=(counts["done"] + counts["error"] + counts["stopped"]) / total))
    return rows


def _probe_absorb(module: Any) -> List[Dict[str, Any]]:
    run = module.ENGINE.active()
    if run is None:
        return []
    summary = run.summary()
    return [_row("absorb", summary["id"], "Data absorption", detail=summary.get("title") or run.prompt,
                 status=summary["status"], source="probe", tab="absorb", seconds=_since(summary.get("created_at")))]


def _probe_deep(module: Any) -> List[Dict[str, Any]]:
    job = module.DEEP_JOBS.current()
    if not job or job.get("status") != "running":
        return []
    return [_row("deep", job["job_id"], "Improve · deep mode", detail=job.get("now", ""), source="probe",
                 tab="improve", seconds=_since(job.get("started_at")))]


def _probe_kahuna_jobs(module: Any) -> List[Dict[str, Any]]:
    """Big Kahuna's training jobs are separate processes that outlive the engine, so they are read from disk."""
    return [_row("kahuna_job", job["id"], f"Big Kahuna · {str(job.get('kind', 'job')).replace('_', ' ')}",
                 detail=job.get("message", ""), status=job["state"], source="probe", tab="kahuna",
                 seconds=_since(job.get("started")), progress=job.get("progress"), pid=job.get("pid"))
            for job in module.list_jobs() if job.get("state") in ("queued", "running")]


#: (module, import it even when nothing has loaded it yet, probe). Only Big Kahuna's jobs
#: need the import: they run in processes of their own, so this engine may never have touched them.
_PROBES: List[tuple] = [
    ("turn_registry", False, _probe_turns),
    ("improve_autopilot", False, _probe_autopilot),
    ("improvement_engine", False, _probe_analysis),
    ("improve_review", False, _probe_review),
    ("agent_dispatch", False, _probe_dispatches),
    ("absorb_engine", False, _probe_absorb),
    ("improve_deep", False, _probe_deep),
    ("identity0.jobs", True, _probe_kahuna_jobs),
]


def _from_probes() -> List[Dict[str, Any]]:
    import importlib
    import sys

    rows: List[Dict[str, Any]] = []
    for module_name, always, probe in _PROBES:
        if module_name not in sys.modules and not always:
            continue                                  # not loaded: nothing of it can be running here
        try:
            rows += probe(importlib.import_module(module_name))
        except Exception:  # noqa: BLE001 - one broken probe must not hide the others
            continue
    return rows


def _as_rows(result: Any) -> List[Dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, dict):
        return [result]
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    return []


def _module_is_ours(name: str, module: Any) -> bool:
    """Top-level modules always count; a package's module counts when its file is in this project.

    The old rule took only ``identity0.``, ``trading.`` and ``office.``, so ``finance_lab``'s
    simulator answered ``background_status()`` and was never heard (U31)."""
    if "." not in name:
        return True
    return _in_project(str(getattr(module, "__file__", "") or ""))


def _from_modules() -> List[Dict[str, Any]]:
    """Anything loaded that answers ``background_status()``.

    This is the part that keeps working as Nyx grows: a new feature says what it
    is doing by defining one function, and it shows up here and in the Core view
    without anyone editing a list. A row may say ``label``, ``id``, ``detail``,
    ``status``, ``running`` (False hides it), ``group``, ``tab``, ``seconds`` and
    ``progress``.
    """
    import sys

    rows: List[Dict[str, Any]] = []
    for name, module in list(sys.modules.items()):
        status = getattr(module, "background_status", None)
        if not callable(status) or not _module_is_ours(name, module):
            continue
        try:
            for item in _as_rows(status()):
                if not item.get("running", True):
                    continue
                rows.append(_row(str(item.get("kind") or name), item.get("id") or name, str(item.get("label") or name),
                                 detail=item.get("detail"), status=str(item.get("status") or "running"),
                                 source="module", group=str(item.get("group") or "job"), tab=str(item.get("tab") or ""),
                                 seconds=item.get("seconds"), progress=item.get("progress")))
        except Exception:  # noqa: BLE001
            continue
    return rows


# --- threads: the ground truth for work inside this process ---------------------------------------

_OUTSIDE_PARTS = ("site-packages", "node_modules", "temp_inspect")
_IN_PROJECT: Dict[str, bool] = {}


def _in_project(filename: str) -> bool:
    """Code that lives in this project (not in the virtualenv or a library). Memoised: a file does not move."""
    if not filename:
        return False
    known = _IN_PROJECT.get(filename)
    if known is None:
        try:
            parts = Path(filename).resolve().relative_to(PROJECT_DIR.resolve()).parts
            known = not any(part.startswith(".venv") or part in _OUTSIDE_PARTS for part in parts)
        except (ValueError, OSError):
            known = False
        _IN_PROJECT[filename] = known
    return known


def _thread_code(thread: threading.Thread) -> tuple:
    """(file, function) of the code a thread runs, so an unnamed thread can still be told apart from a library's.

    ``Thread._target`` stays set until ``run()`` returns — for exactly as long as the work goes on."""
    target = getattr(thread, "_target", None)
    if target is None and type(thread).run is not threading.Thread.run:
        target = type(thread).run                     # a Thread subclass that overrides run()
    target = getattr(target, "func", target)          # functools.partial
    target = getattr(target, "__func__", target)      # bound method
    code = getattr(target, "__code__", None)
    return (str(getattr(code, "co_filename", "") or ""), str(getattr(code, "co_name", "") or ""))


def _looks_like_id(part: str) -> bool:
    return part.isdigit() or (len(part) >= 4 and bool(re.fullmatch(r"[0-9a-f]+", part))
                              and any(c.isdigit() for c in part))


def thread_words(name: str) -> tuple:
    """(label, tab, group) for a thread name — from the table, or made from the name itself."""
    for prefix, label, tab, group in _THREAD_WORDS:
        if name.startswith(prefix):
            return label, tab, group
    parts = [part for part in re.split(r"[-_\s]+", name) if part]
    while len(parts) > 1 and _looks_like_id(parts[-1]):
        parts.pop()
    if len(parts) > 1 and parts[0].lower() == "nyx":
        parts = parts[1:]
    words = " ".join(parts) or name
    return words[:1].upper() + words[1:], "", "job"


def _module_words(filename: str) -> str:
    stem = Path(filename).stem
    if len(stem) <= 3:
        return stem.upper()
    words = stem.replace("_", " ")
    return words[:1].upper() + words[1:]


def _threads() -> List[Dict[str, Any]]:
    """Every worker thread Nyx's own code started — named or not, built before this file or after it.

    A thread counts when it is not plumbing and either runs code from this project or is
    named like Nyx's (``nyx-…`` or a name in the table), so a feature that starts a thread
    is visible the moment it runs. Library threads (request workers, pools, the server) are not."""
    rows = []
    for thread in threading.enumerate():
        name = thread.name or ""
        if not thread.is_alive() or thread is threading.current_thread() or name.startswith(_PLUMBING):
            continue
        filename, function = _thread_code(thread)
        named_like_ours = name.startswith("nyx-") or any(name.startswith(prefix) for prefix, *_ in _THREAD_WORDS)
        if not (named_like_ours or _in_project(filename)):
            continue
        if re.fullmatch(r"Thread-\d+( \(.*\))?", name):  # unnamed: say whose code it runs
            label, tab, group = (_module_words(filename) if filename else "Background work"), "", "job"
            detail = f"{Path(filename).stem}.{function}" if filename else ""
        else:
            (label, tab, group), detail = thread_words(name), ""
        rows.append(_row("thread", name, label, detail=detail, source="thread", group=group, tab=tab))
    return rows


# --- child processes: work Nyx handed to another program -----------------------------------------

def _children() -> List[Dict[str, Any]]:
    """Processes this engine started (a model download, a training run, a build), whatever started them."""
    try:
        import psutil

        children = psutil.Process(os.getpid()).children(recursive=True)
    except Exception:  # noqa: BLE001 - no psutil, or the OS said no: the threads still show
        return []
    rows = []
    for child in children:
        try:
            with child.oneshot():
                name = child.name()
                if name.lower() in _HELPER_PROCESSES:
                    continue
                try:
                    command = child.cmdline()
                except Exception:  # noqa: BLE001 - access denied: the name is still worth showing
                    command = []
                started = child.create_time()
        except Exception:  # noqa: BLE001 - it ended while we looked
            continue
        rows.append(_row("process", child.pid, _process_words(name, command), detail=" ".join(command[1:4]),
                         source="subprocess", seconds=_since(started), pid=child.pid))
    return rows


def _process_words(name: str, command: List[str]) -> str:
    stem = Path(name).stem
    if stem.lower().startswith("python") and len(command) > 1:
        if "-m" in command[:-1]:
            return _module_words(command[command.index("-m") + 1].split(".")[-1]) + " (Python)"
        script = next((part for part in command[1:] if part.endswith(".py")), "")
        if script:
            return _module_words(script) + " (Python)"
    if len(command) > 1 and not command[1].startswith("-"):
        return f"{stem.capitalize()} {Path(command[1]).name}"[:60]
    return stem.capitalize()


def _covered(row: Dict[str, Any], ids: Iterable[str], pids: Iterable[Any]) -> bool:
    """Whether a thread or process row is work a registry already reported (its id in the name, or its pid)."""
    if row["source"] == "subprocess":
        return row.get("pid") in set(pids)
    return any(len(known) >= 4 and known in row["id"] for known in ids)


def live_processes(known_ids: Iterable[str] = ()) -> List[Dict[str, Any]]:
    """Everything running in the background right now, however new it is.

    Registries and ``background_status()`` speak first, because they know the words
    and the progress; a thread or child process then shows only when no reported job
    already accounts for it. ``known_ids`` are ids the caller lists itself."""
    reported: Dict[str, Dict[str, Any]] = {}
    for row in _from_probes() + _from_modules():
        reported.setdefault(f"{row['kind']}:{row['id']}", row)
    ids = [str(i) for i in known_ids] + [row["id"] for row in reported.values()]
    pids = [row.get("pid") for row in reported.values() if row.get("pid")]
    found = list(reported.values())
    for row in _threads() + _children():
        if not _covered(row, ids, pids):
            found.append(row)
    # Work that ends first (what the owner watches), then the loops that are always on.
    return sorted(found, key=lambda row: row["group"] == "service")


# ---------------------------------------------------------------------------
# What the model reads
# ---------------------------------------------------------------------------


def summary(area: str = "", limit: int = 40) -> str:
    """The catalog in words, for the model that asks what it can do."""
    catalog = scan()
    area = (area or "").strip().lower()
    lines: List[str] = []
    counts = catalog["counts"]
    lines.append(f"Nyx has {counts['tools']} tools, {counts['tabs']} tabs, {counts['roles']} model roles "
                 f"and {counts['routes']} API routes across {counts['modules']} modules.")
    running = live_processes()
    if running:
        lines.append("Running now: " + ", ".join(f"{row['label']}" for row in running[:12]))
    else:
        lines.append("Nothing is running in the background right now.")
    if catalog.get("new_modules"):
        lines.append("New since the last look: " + ", ".join(catalog["new_modules"][:10]))

    if not area or area in {"tool", "tools"}:
        top = [row for row in catalog["tools"] if row["used"]][:limit]
        if top:
            lines.append("Most-used tools: " + ", ".join(f"{row['name']} ({row['used']})" for row in top[:12]))
        unused = [row["name"] for row in catalog["tools"] if not row["used"]][:12]
        if unused:
            lines.append("Never used yet: " + ", ".join(unused))
    if area in {"tab", "tabs"}:
        lines.append("Tabs: " + ", ".join(f"{row['label']} ({row['used']})" for row in catalog["tabs"][:limit]))
    if area in {"role", "roles", "models"}:
        lines.append("Model roles: " + ", ".join(f"{row['title']} → {row['provider']} {row['model']}"
                                                 for row in catalog["roles"][:limit]))
    if area in {"module", "modules", "code"}:
        lines += [f"- {row['module']}: {row['what']}" for row in catalog["modules"][:limit]]
    return "\n".join(lines)


def tool_feature_catalog(area: str = "") -> str:
    """Tool: what Nyx can do, what is running, and how much each part is used."""
    return summary(area)


def register_feature_tools(registry: Any) -> None:
    from tools import ToolParam as P

    registry.register(
        "feature_catalog",
        ("What this Nyx can do right now: tools, tabs, model roles, routes and modules, what is running in "
         "the background, and how much each part is used. Read this before saying a feature does not exist."),
        [P("area", "string", "tools, tabs, roles, modules, or empty for everything", required=False)],
        tool_feature_catalog,
        category="general",
        label="Reading the feature catalog",
    )
