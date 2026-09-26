"""Keep Nyx small on disk (owner, 2026-09-15: "make sure it doesn't take too much storage").

Measured that day: the whole folder was 666 MB, almost all of it fixed (the Python environment
~136 MB, the front end's build tools ~175 MB) plus ~290 MB of old build leftovers. What grows with use
had no limit, so this module gives each growing store a budget:

* **Trimmed automatically** (derived data or copies, nothing the owner made):
  code-edit backups (≤150 MB and ≤30 days, the newest 20 always kept), the voice cache (≤50 MB,
  oldest first), learning logs (each ≤20 MB, newest lines kept), extra chats.backup-*.json (newest 3),
  and the engine log (already rotated at 5 MB).
* **Reported, never deleted automatically:** the memory database, uploads and backgrounds — those are
  the owner's. The memory database is compacted (SQLite VACUUM, no memories removed) once it has
  slack to give back.
* **Leftovers:** known old build folders are listed with their size; each is removed only when the
  owner presses Remove and confirms, and only paths on this fixed list can be removed.

``enforce()`` runs a minute after the engine starts and then once a day.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from paths import PROJECT_DIR, data_path

MB = 1024 * 1024
BUDGETS = {
    "code_backups": {"max_mb": 150, "max_days": 30, "keep_newest": 20},
    "tts_cache": {"max_mb": 50},
    "learning_log_mb": 20,
    "chat_backups_keep": 3,
    "brain_warn_mb": 500,
}

#: Old build output that nothing in Nyx uses. Paths are fixed here; the API never takes a path.
LEFTOVERS: Dict[str, Dict[str, Any]] = {
    "dist": {"path": PROJECT_DIR / "dist", "why": "Old packaged Nyx.exe builds (PyInstaller). Smart App Control blocks them."},
    "build": {"path": PROJECT_DIR / "build", "why": "Temporary files from those builds."},
    "venv-broken": {"path": PROJECT_DIR / ".venv.broken", "why": "A Python environment replaced by .venv."},
    "openai-mcp-copy": {"path": PROJECT_DIR / "openai_mcp - Copy", "why": "A duplicate of the openai_mcp folder."},
    "temp-inspect": {"path": PROJECT_DIR / "temp_inspect", "why": "An unpacked copy of an old build, used once for inspection."},
    "old-downloads": {"path": PROJECT_DIR / "site" / "downloads", "why": "Out-of-date download zips (the old Nyx.exe build)."},
    "old-installed-app": {"path": Path(os.environ.get("LOCALAPPDATA", "")) / "NyxIchos" / "app",
                          "why": "The Sep 6 installed copy of Nyx. Your .env.local next to it is not touched."},
}

_lock = threading.Lock()
_started = False


def folder_size(path: Path) -> int:
    total = 0
    if path.is_file():
        return path.stat().st_size
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def _files_oldest_first(folder: Path) -> List[Path]:
    if not folder.is_dir():
        return []
    items = [p for p in folder.rglob("*") if p.is_file()]
    return sorted(items, key=lambda p: p.stat().st_mtime)


def _trim_folder(folder: Path, max_bytes: int, max_age_days: Optional[int] = None, keep_newest: int = 0) -> Dict[str, int]:
    files = _files_oldest_first(folder)
    protected = set(files[-keep_newest:]) if keep_newest else set()
    total = sum(p.stat().st_size for p in files)
    removed = freed = 0
    cutoff = time.time() - max_age_days * 86400 if max_age_days else None
    for path in files:
        if path in protected:
            continue
        too_old = cutoff is not None and path.stat().st_mtime < cutoff
        if total <= max_bytes and not too_old:
            continue
        size = path.stat().st_size
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        freed += size
        removed += 1
    return {"removed": removed, "freed": freed}


def _trim_jsonl(path: Path, max_bytes: int) -> int:
    """Keep the newest lines of a log so it fits the budget. Returns bytes freed."""
    try:
        size = path.stat().st_size
    except OSError:
        return 0
    if size <= max_bytes:
        return 0
    with path.open("rb") as handle:
        handle.seek(size - int(max_bytes * 0.8))
        tail = handle.read()
    tail = tail[tail.find(b"\n") + 1:]
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(tail)
    os.replace(temp, path)
    return size - len(tail)


def _compact_brain(path: Path) -> int:
    """VACUUM the memory database when at least a quarter of it is free pages. Nothing is deleted."""
    if not path.is_file():
        return 0
    before = path.stat().st_size
    try:
        with sqlite3.connect(str(path), timeout=5) as db:
            free = db.execute("PRAGMA freelist_count").fetchone()[0]
            pages = db.execute("PRAGMA page_count").fetchone()[0] or 1
            if free / pages < 0.25:
                return 0
            db.execute("VACUUM")
    except sqlite3.Error:
        return 0
    return max(0, before - path.stat().st_size)


def enforce() -> Dict[str, Any]:
    """Apply every automatic budget once. Safe to call any time."""
    with _lock:
        result: Dict[str, Any] = {}
        cfg = BUDGETS["code_backups"]
        result["code_backups"] = _trim_folder(data_path("code_backups"), cfg["max_mb"] * MB, cfg["max_days"], cfg["keep_newest"])
        result["tts_cache"] = _trim_folder(data_path("tts_cache"), BUDGETS["tts_cache"]["max_mb"] * MB)
        freed = 0
        learning = data_path("learning")
        if learning.is_dir():
            for log in learning.glob("*.jsonl"):
                freed += _trim_jsonl(log, BUDGETS["learning_log_mb"] * MB)
        result["learning_logs"] = {"freed": freed}
        backups = sorted(PROJECT_DIR.glob("chats.backup-*.json"), key=lambda p: p.stat().st_mtime)
        extra = backups[:-BUDGETS["chat_backups_keep"]] if len(backups) > BUDGETS["chat_backups_keep"] else []
        chat_freed = 0
        for path in extra:
            try:
                chat_freed += path.stat().st_size
                path.unlink()
            except OSError:
                pass
        result["chat_backups"] = {"removed": len(extra), "freed": chat_freed}
        result["brain_compacted"] = {"freed": _compact_brain(data_path("brain/brain.db"))}
        result["freed_total"] = sum(int(v.get("freed", 0)) for v in result.values() if isinstance(v, dict))
        return result


def report() -> Dict[str, Any]:
    """Sizes by what they are, the budgets, and leftovers the owner may remove."""
    def entry(label: str, path: Path, kind: str, note: str = "") -> Dict[str, Any]:
        return {"label": label, "bytes": folder_size(path) if path.exists() else 0, "kind": kind, "note": note}

    growing = [
        entry("Memory (Second Brain)", data_path("brain"), "yours",
              f"Kept. Compacted when it has free space; you'll be warned above {BUDGETS['brain_warn_mb']} MB."),
        entry("Uploads and attachments", data_path("uploads"), "yours", "Kept — they belong to your chats."),
        entry("Code edit backups", data_path("code_backups"), "trimmed",
              f"Up to {BUDGETS['code_backups']['max_mb']} MB and {BUDGETS['code_backups']['max_days']} days."),
        entry("Voice cache", data_path("tts_cache"), "trimmed", f"Up to {BUDGETS['tts_cache']['max_mb']} MB."),
        entry("Learning logs", data_path("learning"), "trimmed", f"Each log up to {BUDGETS['learning_log_mb']} MB."),
        entry("Engine log", data_path("logs"), "trimmed", "Rotated at 5 MB."),
    ]
    fixed = [
        entry("Python environment (.venv)", PROJECT_DIR / ".venv", "fixed", "Needed to run Nyx."),
        entry("Front-end build tools (node_modules)", PROJECT_DIR / "frontend" / "nyx-pulse" / "node_modules", "fixed",
              "Needed only to rebuild the interface; the built app is in frontend/nyx-pulse/dist."),
    ]
    leftovers = []
    for key, item in LEFTOVERS.items():
        path = Path(item["path"])
        if str(path) and path.exists():
            leftovers.append({"id": key, "label": path.name, "path": str(path), "bytes": folder_size(path), "why": item["why"]})
    brain = growing[0]["bytes"]
    return {
        "growing": growing, "fixed": fixed, "leftovers": leftovers,
        "total_bytes": sum(e["bytes"] for e in growing + fixed) + sum(e["bytes"] for e in leftovers),
        "reclaimable_bytes": sum(e["bytes"] for e in leftovers),
        "warnings": ([f"The memory database is {brain // MB} MB."] if brain > BUDGETS["brain_warn_mb"] * MB else []),
        "last_run": _last_run,
    }


def remove_leftover(key: str) -> int:
    """Delete one folder from the fixed LEFTOVERS list. Returns bytes freed."""
    item = LEFTOVERS.get(key)
    if item is None:
        raise KeyError(key)
    path = Path(item["path"]).resolve()
    if not path.exists():
        return 0
    size = folder_size(path)
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return size


_last_run: Dict[str, Any] = {}


def start_background(first_delay: float = 60.0, every: float = 24 * 3600) -> None:
    """Run ``enforce`` shortly after start and then daily, on one daemon thread."""
    global _started
    if _started:
        return
    _started = True

    def loop() -> None:
        time.sleep(first_delay)
        while True:
            try:
                outcome = enforce()
                _last_run.clear()
                _last_run.update({"at": time.time(), "freed": outcome.get("freed_total", 0)})
            except Exception:  # pragma: no cover - housekeeping never stops the engine
                pass
            time.sleep(every)

    threading.Thread(target=loop, name="nyx-storage-budget", daemon=True).start()
