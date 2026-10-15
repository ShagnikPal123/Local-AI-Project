"""The week calendar (Fixer Upper S21, "MausBot-style calendar the AI can restyle").

Two halves, both plain data:

* **What is on it.** Orbits (``scheduled.py``) are rules, so this module expands them into dated occurrences for one week;
  Google Calendar events are added when Calendar is connected. Nothing here runs a task, it only shows when one would.
* **How it looks.** The look is a small validated spec (view, density, hours, colouring, accent). The AI restyles the
  calendar by changing that spec through the ``restyle_calendar`` tool, never by writing UI code (invariant 2), and
  every field is checked against a closed set or clamped, so a bad value falls back instead of breaking the page.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from paths import atomic_replace, data_path

_LOCK = threading.RLock()

VIEWS = ("week", "agenda")
DENSITIES = ("compact", "comfortable", "roomy")
COLOUR_BY = ("avatar", "repeat", "source")
DEFAULT_LOOK: Dict[str, Any] = {
    "view": "week", "density": "comfortable", "start_hour": 6, "end_hour": 22, "show_weekend": True,
    "week_starts": "mon", "colour_by": "source", "accent": "", "show_google": True,
}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
#: Most occurrences one repeating task may add to a week, so an "every 5 minutes" rule cannot flood the page.
MAX_PER_TASK = 80


def _path():
    return data_path("calendar_look.json")


def clean_look(raw: Dict[str, Any], base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Merge ``raw`` over ``base``, keeping only valid values. Unknown keys are dropped, bad values keep the old one."""
    look = {**DEFAULT_LOOK, **(base or {})}
    raw = raw or {}
    if raw.get("view") in VIEWS:
        look["view"] = raw["view"]
    if raw.get("density") in DENSITIES:
        look["density"] = raw["density"]
    if raw.get("colour_by") in COLOUR_BY:
        look["colour_by"] = raw["colour_by"]
    if raw.get("week_starts") in ("mon", "sun"):
        look["week_starts"] = raw["week_starts"]
    for key in ("show_weekend", "show_google"):
        if isinstance(raw.get(key), bool):
            look[key] = raw[key]
    for key in ("start_hour", "end_hour"):
        if isinstance(raw.get(key), (int, float)) and not isinstance(raw.get(key), bool):
            look[key] = int(raw[key])
    look["start_hour"] = max(0, min(int(look["start_hour"]), 22))
    look["end_hour"] = max(look["start_hour"] + 2, min(int(look["end_hour"]), 24))
    if isinstance(raw.get("accent"), str) and (raw["accent"] == "" or _HEX.match(raw["accent"])):
        look["accent"] = raw["accent"].lower()
    return {key: look[key] for key in DEFAULT_LOOK}


def get_look() -> Dict[str, Any]:
    with _LOCK:
        try:
            saved = json.loads(_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        return clean_look(saved if isinstance(saved, dict) else {})


def set_look(changes: Dict[str, Any]) -> Dict[str, Any]:
    """Change some fields of the look and save it. Returns the look that is now in force."""
    with _LOCK:
        look = clean_look(changes, get_look())
        path = _path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(look, indent=1), encoding="utf-8")
        atomic_replace(tmp, path)
        return look


def reset_look() -> Dict[str, Any]:
    with _LOCK:
        try:
            _path().unlink()
        except OSError:
            pass
        return get_look()


# --- what is on it --------------------------------------------------------------------------------------------------

def week_start(day: date, week_starts: str = "mon") -> date:
    """The first day of the week that contains ``day``."""
    back = (day.weekday() + 1) % 7 if week_starts == "sun" else day.weekday()
    return day - timedelta(days=back)


def occurrences(tasks: List[Dict[str, Any]], start: date, days: int = 7) -> List[Dict[str, Any]]:
    """Dated runs of every Orbit between ``start`` and ``start + days``, in time order.

    A task with no avatar is listed (``runs`` False) because it never runs by itself; a paused one is listed so the
    owner can see what is switched off. "Every N minutes" tasks under an hour become one all-day marker per day.
    """
    first = datetime.combine(start, datetime.min.time())
    last = first + timedelta(days=days)
    out: List[Dict[str, Any]] = []

    def add(task: Dict[str, Any], when: datetime, all_day: bool = False) -> None:
        # A repeating Orbit has no runs before the day it was made (owner, 2026-10-15, "calendar doesn't work": a new
        # daily task filled the whole past week as if it had been running all along).
        if task.get("repeat") != "once" and task.get("created") and when.date() < datetime.fromtimestamp(task["created"]).date():
            return
        out.append({"id": task["id"], "title": task["title"], "avatar": task.get("avatar", ""), "repeat": task["repeat"],
                    "at": when.timestamp(), "time": "all day" if all_day else when.strftime("%H:%M"),
                    "day": (when.date() - start).days, "all_day": all_day, "enabled": bool(task.get("enabled", True)),
                    "runs": bool(task.get("avatar")), "source": "orbit"})

    for task in tasks:
        repeat = task.get("repeat")
        if repeat == "once":
            at = task.get("at") or 0
            if at and first <= datetime.fromtimestamp(at) < last:
                add(task, datetime.fromtimestamp(at))
        elif repeat == "every":
            step = int(task.get("every_minutes") or 60)
            if step < 60:
                for index in range(days):
                    add(task, first + timedelta(days=index), all_day=True)
                continue
            when, count = first, 0
            while when < last and count < MAX_PER_TASK:
                add(task, when)
                when += timedelta(minutes=step)
                count += 1
        elif repeat in ("daily", "weekdays", "weekly"):
            try:
                hour, minute = (int(part) for part in str(task.get("time") or "09:00").split(":"))
            except ValueError:
                hour, minute = 9, 0
            for index in range(days):
                day = first + timedelta(days=index)
                if repeat == "weekdays" and day.weekday() > 4:
                    continue
                if repeat == "weekly" and day.weekday() not in (task.get("days") or [0]):
                    continue
                add(task, day.replace(hour=hour, minute=minute))
    out.sort(key=lambda item: (item["at"], item["title"]))
    return out


def google_events(start: date, days: int = 7, call: Optional[Callable[..., Dict[str, Any]]] = None,
                  connected: Optional[Callable[[], bool]] = None) -> Tuple[bool, List[Dict[str, Any]], str]:
    """(connected, events, error). Never raises: a calendar that cannot be read just shows the Orbits."""
    try:
        if call is None or connected is None:
            import connector_use
            call = call or connector_use.call
            connected = connected or (lambda: connector_use.is_connected("google_calendar"))
        if not connected():
            return False, [], ""
        begin = datetime.combine(start, datetime.min.time()).astimezone()
        result = call("google_calendar", "events", params={
            "calendar_id": "primary", "timeMin": begin.isoformat(), "timeMax": (begin + timedelta(days=days)).isoformat(),
            "singleEvents": "true", "orderBy": "startTime", "maxResults": "100"})
    except Exception as error:  # noqa: BLE001 - see docstring
        return False, [], str(error)[:200]
    events: List[Dict[str, Any]] = []
    for item in (result.get("data") or {}).get("items") or []:
        begins = item.get("start") or {}
        stamp = begins.get("dateTime") or begins.get("date") or ""
        try:
            when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        local = when.astimezone().replace(tzinfo=None) if when.tzinfo else when
        events.append({"id": str(item.get("id") or ""), "title": str(item.get("summary") or "Untitled")[:120],
                       "at": local.timestamp(), "time": "all day" if "T" not in stamp else local.strftime("%H:%M"),
                       "day": (local.date() - start).days, "all_day": "T" not in stamp, "source": "google",
                       "avatar": "", "repeat": "", "enabled": True, "runs": False})
    return True, [e for e in events if 0 <= e["day"] < days], ""


def week(day: Optional[date] = None, tasks: Optional[List[Dict[str, Any]]] = None,
         google: Optional[Callable[..., Tuple[bool, List[Dict[str, Any]], str]]] = None) -> Dict[str, Any]:
    """Everything the page needs for the week containing ``day`` (today when not given)."""
    today = date.today()
    look = get_look()
    start = week_start(day or today, look["week_starts"])
    if tasks is None:
        import scheduled
        tasks = scheduled.list_tasks()
    items = occurrences(tasks, start)
    connected, events, error = (google or google_events)(start) if look["show_google"] else (False, [], "")
    items = sorted(items + events, key=lambda item: (item["at"], item["title"]))
    days = [{"date": (start + timedelta(days=i)).isoformat(), "label": (start + timedelta(days=i)).strftime("%a"),
             "number": (start + timedelta(days=i)).day, "today": start + timedelta(days=i) == today} for i in range(7)]
    return {"start": start.isoformat(), "days": days, "items": items, "look": look,
            "google": {"connected": connected, "error": error}}


# --- the AI's way in -------------------------------------------------------------------------------------------------

def tool_restyle(view: str = "", density: str = "", start_hour: Any = None, end_hour: Any = None,
                 show_weekend: Any = None, colour_by: str = "", accent: Optional[str] = None, reset: bool = False) -> str:
    if reset:
        reset_look()
        return "The calendar is back to its default look."
    changes = {key: value for key, value in {
        "view": view, "density": density, "start_hour": start_hour, "end_hour": end_hour, "show_weekend": show_weekend,
        "colour_by": colour_by, "accent": accent}.items() if value not in ("", None)}
    if not changes:
        return "Nothing to change. Options: view " + "/".join(VIEWS) + ", density " + "/".join(DENSITIES) \
            + ", start_hour, end_hour, show_weekend, colour_by " + "/".join(COLOUR_BY) + ", accent (#rrggbb)."
    before = get_look()
    after = set_look(changes)
    changed = [f"{key} {after[key]}" for key in after if after[key] != before[key]]
    return ("Restyled the calendar: " + ", ".join(changed) + ".") if changed else "Those values were not valid, so the look is unchanged."


def register_calendar_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        "restyle_calendar",
        "Change how the owner's week calendar looks (Orbits tab, Calendar). It only changes a saved look, never code. "
        "Use for 'make the calendar compact', 'show only work hours', 'hide weekends', 'colour by avatar'.",
        [ToolParam("view", "string", "week grid or agenda list", required=False, enum_values=list(VIEWS)),
         ToolParam("density", "string", "Row height", required=False, enum_values=list(DENSITIES)),
         ToolParam("start_hour", "number", "First hour shown, 0-22", required=False),
         ToolParam("end_hour", "number", "Last hour shown, up to 24", required=False),
         ToolParam("show_weekend", "boolean", "Show Saturday and Sunday", required=False),
         ToolParam("colour_by", "string", "What colours the entries", required=False, enum_values=list(COLOUR_BY)),
         ToolParam("accent", "string", "Accent colour as #rrggbb, or empty for the app's accent", required=False),
         ToolParam("reset", "boolean", "Go back to the default look", required=False)],
        tool_restyle, category="general", label="Restyling the calendar")
