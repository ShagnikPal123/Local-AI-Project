"""Self-approval: Ichos may approve its own improvements when it judges them worthy, with a switch and a log.

The owner, 2026-10-14: "yes if it deems them worthy". Conditions: an on/off switch, and a log of every change the AI
approved itself, with its reason, so each one can be seen and undone (WS15, Fixer Upper S12).

What it changes: while the switch is on, an Improve autopilot run approves the changes its own research recommends
(the run's auto-approve, which used to need asking per run). The research step still has to say "approve", the
sandbox tests and the critic still run before anything is applied, and every approval lands in this log with a
rollback link. Switched off (the default), nothing self-approves unless a run was started with auto-approve.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List

from paths import data_path

SETTINGS_FILE = "self_approval.json"
LOG_FILE = "self_approval_log.json"
LOG_MAX = 500
_lock = threading.Lock()


def _read(name: str, default: Any) -> Any:
    try:
        return json.loads(data_path(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def enabled() -> bool:
    data = _read(SETTINGS_FILE, {})
    return bool(data.get("enabled", False)) if isinstance(data, dict) else False


def set_enabled(on: bool) -> bool:
    with _lock:
        data_path(SETTINGS_FILE).write_text(json.dumps({"enabled": bool(on), "changed_at": time.time()}), encoding="utf-8")
    return bool(on)


def record(change_id: str, title: str, reason: str, by: str = "Autopilot") -> Dict[str, Any]:
    """Note one self-approved change. Kept newest first, the last 500."""
    entry = {"change_id": str(change_id), "title": str(title)[:200], "reason": str(reason)[:600], "by": by,
             "at": time.time()}
    with _lock:
        log = _read(LOG_FILE, [])
        log = [entry] + (log if isinstance(log, list) else [])
        data_path(LOG_FILE).write_text(json.dumps(log[:LOG_MAX], indent=1), encoding="utf-8")
    return entry


def log(limit: int = 50) -> List[Dict[str, Any]]:
    """Newest first, each with the change's current status (published, rolled back…) when it can be read."""
    items = _read(LOG_FILE, [])
    items = items[:max(1, int(limit))] if isinstance(items, list) else []
    try:
        from change_review import CHANGE_LOG

        for item in items:
            change = CHANGE_LOG.get(item.get("change_id", ""))
            item["status"] = getattr(getattr(change, "status", None), "value", "") if change else "gone"
    except Exception:  # noqa: BLE001 - the log still reads without statuses
        pass
    return items


def state() -> Dict[str, Any]:
    return {"enabled": enabled(), "log": log(50)}
