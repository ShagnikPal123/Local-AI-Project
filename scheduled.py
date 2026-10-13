"""Orbits (scheduled tasks): tell Ichos once what to do and when, and it repeats.

The owner (2026-10-11): "Schedule is a general thing that can be set to repeated, will have Google Calendar linking, and
we can just tell the AI to do things, almost anything — every day send emails, read emails, text people."

A task is **data** (invariant 2): a title, the instruction in the owner's words, a repeat rule and WHICH AVATAR does it.
Doing it is delegated to ``avatars.run`` so the avatar's deny-by-default guard decides what the task may touch — sending
mail or texting waits for the owner's click when that avatar has Send set to Ask. A task with no avatar is never run by
the clock (it can still be listed and edited), so a typo cannot quietly start spending model calls.

Repeat rules: ``once`` (at ``at``), ``every`` N minutes, ``daily``, ``weekdays``, ``weekly`` (on ``days``, Mon=0).
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from paths import data_path

log = logging.getLogger(__name__)
_LOCK = threading.RLock()
REPEATS = ("once", "every", "daily", "weekdays", "weekly")
MAX_TASKS = 100


class ScheduleError(ValueError):
    pass


def _path():
    return data_path("scheduled.json")


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("tasks"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"tasks": {}}


def _save(state: Dict[str, Any]) -> None:
    path = _path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(path)


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _clock(value: Any, default: str = "09:00") -> str:
    parts = str(value or "").split(":")
    try:
        hour, minute = int(parts[0]), int(parts[1])
        if 0 <= hour < 24 and 0 <= minute < 60:
            return f"{hour:02d}:{minute:02d}"
    except (ValueError, IndexError):
        pass
    return default


def clean(raw: Dict[str, Any], base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = base or {}
    merged = {**base, **{k: v for k, v in raw.items() if v is not None}}
    title = _text(merged.get("title"), 80)
    prompt = str(merged.get("prompt") or "").strip()[:2000]
    if not title or not prompt:
        raise ScheduleError("A scheduled task needs a title and what to do.")
    repeat = merged.get("repeat") if merged.get("repeat") in REPEATS else "daily"
    try:
        every = max(5, min(10080, int(merged.get("every_minutes") or 60)))
    except (TypeError, ValueError):
        every = 60
    days = sorted({int(d) for d in merged.get("days") or [] if str(d).isdigit() and 0 <= int(d) <= 6})
    at = merged.get("at") if isinstance(merged.get("at"), (int, float)) else 0
    return {"id": merged.get("id") or f"sc-{uuid.uuid4().hex[:8]}", "title": title, "prompt": prompt, "repeat": repeat,
            "every_minutes": every, "time": _clock(merged.get("time")), "days": days or [0], "at": float(at),
            "avatar": _text(merged.get("avatar"), 60), "enabled": bool(merged.get("enabled", True)),
            "calendar": bool(merged.get("calendar", False)), "created": merged.get("created") or time.time(),
            "last_run": float(merged.get("last_run") or 0), "last_reply": str(merged.get("last_reply") or "")[:1500],
            "last_ok": bool(merged.get("last_ok", True))}


def next_run(task: Dict[str, Any], after: Optional[datetime] = None) -> Optional[datetime]:
    """When the task is next due, counted from its last run (or from now if it never ran). None = never again."""
    if not task["enabled"]:
        return None
    now = after or datetime.now()
    last = datetime.fromtimestamp(task["last_run"]) if task["last_run"] else None
    if task["repeat"] == "once":
        return None if last else datetime.fromtimestamp(task["at"]) if task["at"] else None
    if task["repeat"] == "every":
        return (last + timedelta(minutes=task["every_minutes"])) if last else now
    hour, minute = (int(x) for x in task["time"].split(":"))
    for ahead in range(0, 8):
        day = (now + timedelta(days=ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if task["repeat"] == "weekdays" and day.weekday() > 4:
            continue
        if task["repeat"] == "weekly" and day.weekday() not in task["days"]:
            continue
        if (last and day <= last) or (not last and day < now - timedelta(minutes=1)):
            continue
        return day
    return None


def is_due(task: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    due = next_run(task, now)
    return bool(task["avatar"]) and due is not None and due <= now


# --- CRUD ------------------------------------------------------------------------------------------------------------

def _view(task: Dict[str, Any]) -> Dict[str, Any]:
    due = next_run(task)
    return {**task, "next": due.timestamp() if due else 0}


def list_tasks() -> List[Dict[str, Any]]:
    with _LOCK:
        rows = [_view(t) for t in _load()["tasks"].values()]
    return sorted(rows, key=lambda t: (t["next"] == 0, t["next"]))


def create(raw: Dict[str, Any]) -> Dict[str, Any]:
    task = clean(raw)
    with _LOCK:
        state = _load()
        if len(state["tasks"]) >= MAX_TASKS:
            raise ScheduleError(f"That is the most scheduled tasks ({MAX_TASKS}) — remove one first.")
        state["tasks"][task["id"]] = task
        _save(state)
    return _view(task)


def update(task_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    with _LOCK:
        state = _load()
        old = state["tasks"].get(task_id)
        if not old:
            raise ScheduleError("No such task.")
        task = clean({k: v for k, v in changes.items() if k not in ("id", "created", "last_run", "last_reply")}, old)
        state["tasks"][task_id] = task
        _save(state)
    return _view(task)


def delete(task_id: str) -> bool:
    with _LOCK:
        state = _load()
        if task_id not in state["tasks"]:
            return False
        del state["tasks"][task_id]
        _save(state)
    return True


# --- running ---------------------------------------------------------------------------------------------------------

def _record(task_id: str, ok: bool, reply: str) -> None:
    with _LOCK:
        state = _load()
        task = state["tasks"].get(task_id)
        if task:
            task.update(last_run=time.time(), last_ok=ok, last_reply=reply[:1500])
            if task["repeat"] == "once":
                task["enabled"] = False
            _save(state)


def run_now(task_id: str, wait: float = 0) -> Dict[str, Any]:
    """Do the task through its avatar. Failures are recorded on the task, never raised into the clock."""
    import avatars

    with _LOCK:
        task = _load()["tasks"].get(task_id)
    if not task:
        raise ScheduleError("No such task.")
    if not task["avatar"]:
        raise ScheduleError("Pick an avatar to do this task first.")
    text = (f"[Scheduled: {task['title']}] It is time for this scheduled task. Do it now with your tools:\n"
            f"{task['prompt']}\nReport what you did in two lines.")
    try:
        result = avatars.run(task["avatar"], text, kind="scheduled", wait=wait)
        ok, reply = bool(result["ok"]), str(result["reply"])
    except avatars.AvatarError as error:
        ok, reply = False, str(error)
    _record(task_id, ok, reply)
    return {"id": task_id, "ok": ok, "reply": reply}


def tick(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    done = []
    with _LOCK:
        tasks = list(_load()["tasks"].values())
    for task in tasks:
        if is_due(task, now):
            done.append(run_now(task["id"], wait=0))
    return done


_started = threading.Event()


def _loop() -> None:
    while True:
        try:
            tick()
        except Exception:  # noqa: BLE001 - the clock keeps going
            log.warning("scheduled clock failed", exc_info=True)
        time.sleep(60)


def start_in_background() -> None:
    if _started.is_set():
        return
    _started.set()
    threading.Thread(target=_loop, name="ichos-scheduled", daemon=True).start()
