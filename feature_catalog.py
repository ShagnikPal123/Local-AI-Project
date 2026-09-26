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
* **What is running** comes from the threads that exist plus every module that
  answers ``background_status()``. A feature built next month appears here the
  moment it defines that function — nobody has to remember to add it.
* **How much it is used** is counted here and kept in ``data/feature_catalog.json``,
  so "which of this do I actually use?" has an answer.

`summary(...)` is what the model reads through the ``feature_catalog`` tool.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from paths import PROJECT_DIR, data_path

#: A scan is reused for this long; the file is written each time.
SCAN_TTL_SECONDS = 300.0
#: Modules whose background work is asked for by name, when they are loaded.
#: Anything not here is still found through ``background_status``.
_PROBES: List[tuple] = [
    ("improve_autopilot", "AUTOPILOT", "active", "Improve autopilot"),
    ("improvement_engine", "ENGINE", "list_sessions", "Code analysis"),
    ("improve_review", "REVIEW_QUEUE", "job", "Change review"),
    ("absorb_engine", "ENGINE", "active_runs", "Data absorption"),
    ("agent_dispatch", "DISPATCHES", "list", "Agent boxes"),
    ("research_engine", "ENGINE", "active_jobs", "Research"),
    ("apply_engine", "ENGINE", "active_jobs", "Apply"),
]

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


def _from_probes() -> List[Dict[str, Any]]:
    import importlib
    import sys

    rows: List[Dict[str, Any]] = []
    for module_name, holder, method, label in _PROBES:
        if module_name not in sys.modules:
            continue                                  # not loaded: nothing of it can be running
        try:
            module = importlib.import_module(module_name)
            target = getattr(module, holder, None) if holder else module
            call: Optional[Callable[..., Any]] = getattr(target, method, None) if target else None
            if not callable(call):
                continue
            result = call()
        except Exception:  # noqa: BLE001 - one broken probe must not hide the others
            continue
        for item in _as_rows(result):
            status = str(item.get("status", "running"))
            if status in {"done", "stopped", "error", "idle", ""} and not item.get("active"):
                continue
            rows.append({"kind": module_name, "label": label, "id": str(item.get("id") or item.get("run_id")
                         or item.get("session_id") or item.get("dispatch_id") or label),
                         "detail": str(item.get("detail") or item.get("work") or item.get("now")
                                       or item.get("progress") or "")[:90],
                         "status": status, "source": "probe"})
    return rows


def _as_rows(result: Any) -> List[Dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, dict):
        return [result]
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    return []


def _from_modules() -> List[Dict[str, Any]]:
    """Anything loaded that answers ``background_status()``.

    This is the part that keeps working as Nyx grows: a new feature says what it
    is doing by defining one function, and it shows up here and in the Core view
    without anyone editing a list.
    """
    import sys

    rows: List[Dict[str, Any]] = []
    for name, module in list(sys.modules.items()):
        if "." in name and not name.startswith(("identity0.", "trading.", "office.")):
            continue
        status = getattr(module, "background_status", None)
        if not callable(status):
            continue
        try:
            for item in _as_rows(status()):
                if not item.get("running", True):
                    continue
                rows.append({"kind": name, "label": str(item.get("label") or name), "id": str(item.get("id") or name),
                             "detail": str(item.get("detail") or "")[:90],
                             "status": str(item.get("status") or "running"), "source": "module"})
        except Exception:  # noqa: BLE001
            continue
    return rows


def _threads() -> List[Dict[str, Any]]:
    """Nyx's own worker threads, named so they read as English."""
    rows = []
    for thread in threading.enumerate():
        name = thread.name or ""
        if not thread.is_alive() or name.startswith(("MainThread", "ThreadPoolExecutor", "asyncio_", "waitpid",
                                                     "AnyIO", "uvicorn")):
            continue
        rows.append({"kind": "thread", "label": name.replace("-", " ").replace("_", " "), "id": name,
                     "detail": "", "status": "running", "source": "thread"})
    return rows


def live_processes() -> List[Dict[str, Any]]:
    """Everything running in the background right now, however new it is."""
    seen: Dict[str, Dict[str, Any]] = {}
    for row in _from_probes() + _from_modules() + _threads():
        seen.setdefault(f"{row['kind']}:{row['id']}", row)
    return list(seen.values())


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
