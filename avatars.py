"""Avatars — always-on helpers the owner shapes: a main function, what it does, when it runs, and what it may touch.

The owner (2026-10-10): "Add in the functions of dots from openai, muse from meta, grok bot from xAI, and MausBot from
open source and integrate into normal chat and include a new part called avatars. Here we can select a main function
of the ai, what it does, if it runs all day or all year, functions and more with the ability to create more or to just
have the default options similar to the ones I said, new names though and add a couple more."

What came from where (ideas only — no code was taken; see docs/AVATARS.md):

* **Dots (OpenAI)** — goal-driven, not prompt-driven; keeps working in the background; connected apps; asks for
  approval before an action that needs it.                                   → goals, check-ins, per-function Ask.
* **Muse (Meta)** — a Goals list with a plan; "monitor the weather and tell me about rain" on its own; remembers what
  you mentioned once.                                                        → goals, watches, the avatar's notes.
* **Grok Bot (xAI)** — teach a task once and it repeats it; two to six bots in one group chat handing work to each
  other, a chief of staff in front.                                          → lessons, ``avatar_team``.
* **MausBot (open source)** — local-first; each bot its own model and memory; every file or outside access waits for
  a click; runs on the coding CLIs already on the PC.                        → model "local", all-Ask, ``tell_claude``.

An avatar is **data** (invariant 2): a validated record, never code. Shipped defaults live here; the owner's edits are
stored beside them in ``avatars.json`` and "Reset" drops the edit (invariant 3: the base is never mutated).

Every avatar turn runs in the avatar's own chat behind a **deny-by-default guard**: a tool runs only when its
category belongs to a function the avatar has switched on; functions set to Ask put an approval card in front of the
owner; deleting files, power and system settings, the clipboard and Ichos's own code are never an avatar's. Scheduled
work costs model calls, so **every avatar starts switched off** and a daily run cap holds each one.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from paths import data_path

log = logging.getLogger("nyx.avatars")

# ---------------------------------------------------------------------------
# The catalogue: functions, main functions, schedules
# ---------------------------------------------------------------------------

#: What an avatar can be allowed to do. Each maps to the tool categories it opens. "ask" is the default rule.
FUNCTIONS: Dict[str, Dict[str, Any]] = {
    "talk": {"label": "Talk & remember", "about": "Answer, remember, notify you", "categories": ["general", "memory"],
             "default": "allow", "locked": True},
    "web": {"label": "Search the web", "about": "Search, read pages, weather, prices", "categories": ["web"],
            "default": "allow"},
    "apps": {"label": "Connected apps", "about": "Google, Notion, GitHub… through Connections", "categories": ["connectors"],
             "default": "allow"},
    "email": {"label": "Read email", "about": "Read and sort the inbox", "categories": ["email.read"], "default": "allow"},
    "send": {"label": "Send email & texts", "about": "Email and your WhatsApp line", "categories": ["email.send", "whatsapp"],
             "default": "ask"},
    "files": {"label": "Read files & notes", "about": "Read files, notes and documents", "categories": ["files.read", "files"],
              "default": "allow"},
    "write": {"label": "Write files & notes", "about": "Make and edit files and notes", "categories": ["files.write"],
              "default": "ask"},
    "computer": {"label": "Use a computer", "about": "Ichos Computer, your screen, apps, windows",
                 "categories": ["computer", "own_computer", "windows", "apps"], "default": "ask"},
    "code": {"label": "Code & Claude Code", "about": "Run code, commands, tell Claude Code", "categories": ["code", "shell"],
             "default": "ask"},
    "pictures": {"label": "Make pictures", "about": "Images and downloads", "categories": ["network"], "default": "allow"},
    "money": {"label": "Money & trading", "about": "Prices, orders — always asks first", "categories": ["finance"],
              "default": "ask", "always_ask": True},
    "learn": {"label": "Study & learn", "about": "Study topics, wonder, analyse data", "categories": ["learning"],
              "default": "allow"},
    "agents": {"label": "Team up", "about": "Hand work to agents and other avatars", "categories": ["agents"],
               "default": "allow"},
}

#: Categories no avatar may ever use, whatever it is given.
NEVER = frozenset({"files.delete", "system", "self", "clipboard"})
#: UI tools an avatar may use (the rest of "ui" — themes, tabs, mods — stays the owner's).
UI_OK = frozenset({"ui_notify", "show_diagram"})

MAIN_FUNCTIONS: Dict[str, str] = {
    "goals": "Work toward goals",
    "life": "Personal life helper",
    "repeat": "Repeat taught tasks",
    "local": "Local coding crew",
    "watch": "Watch & alert",
    "study": "Study partner",
    "inbox": "Inbox & schedule",
    "custom": "Something else",
}

SCHEDULES = {"on_call": "Only when called", "all_day": "All day (between hours)", "all_year": "All year, around the clock"}
MODELS = {"": "Ichos's usual model", "local": "Local only (Ollama, stays on this PC)"}
REPEATS = ("", "daily", "weekly")

#: Personality used when an avatar has none (the owner: "if there is not a personality set please add one").
FALLBACK_PERSONALITY = "close_friend"
#: Each shipped avatar's own personality (presets from personalities.py, or "custom" + text).
DEFAULT_PERSONALITIES = {"orbit": "professional", "halo": "close_friend", "quasar": "concise", "vector": "coding_mentor",
                         "parallax": "concise", "lemma": "homework_helper", "perigee": "professional"}


def personality_options() -> Dict[str, str]:
    try:
        from personalities import PERSONALITY_PRESETS

        options = {key: value["display_name"] for key, value in PERSONALITY_PRESETS.items()}
    except Exception:  # noqa: BLE001
        options = {FALLBACK_PERSONALITY: "Close Friend"}
    return {**options, "custom": "Custom…"}


def personality_text(avatar: Dict[str, Any]) -> str:
    if avatar.get("personality") == "custom" and avatar.get("personality_custom"):
        return avatar["personality_custom"]
    try:
        from personalities import PERSONALITY_PRESETS

        preset = PERSONALITY_PRESETS.get(avatar.get("personality") or "") or PERSONALITY_PRESETS[FALLBACK_PERSONALITY]
        return preset["system_guidance"]
    except Exception:  # noqa: BLE001
        return "Warm, direct and honest, like a trusted friend."


LIMITS = {"name": 40, "text": 1200, "goals": 12, "watches": 10, "lessons": 12, "notes": 40, "activity": 40, "team": 6}


def _sched(mode: str, every: int = 60, start: str = "08:00", end: str = "20:00") -> Dict[str, Any]:
    return {"mode": mode, "every_minutes": every, "start": start, "end": end, "days": [0, 1, 2, 3, 4, 5, 6]}


def _rules(*on: str, ask: tuple = ()) -> Dict[str, str]:
    rules = {"talk": "allow"}
    for key in on:
        rules[key] = "ask" if key in ask else FUNCTIONS[key]["default"]
    return rules


#: The shipped avatars. New names (the owner asked for them) in the app's space-and-mathematics style.
DEFAULTS: List[Dict[str, Any]] = [
    {"id": "orbit", "name": "Orbit", "icon": "ph-planet", "main": "goals", "inspired_by": "Dots (OpenAI)",
     "does": "Give me a goal, not a prompt. I keep working on it in the background across your connected apps, show "
             "progress after each check-in, and ask before anything that changes something.",
     "schedule": _sched("all_day", 60), "functions": _rules("web", "apps", "email", "files", "write", "code", "learn")},
    {"id": "halo", "name": "Halo", "icon": "ph-sun-horizon", "main": "life", "inspired_by": "Muse (Meta)",
     "does": "Your everyday helper: reminders, plans for bigger goals, keeping an eye on things you care about (rain, "
             "deliveries, prices), pictures and documents. I remember what you mention once and suggest things.",
     "schedule": _sched("all_year", 120), "functions": _rules("web", "apps", "files", "write", "pictures", "send", "money")},
    {"id": "quasar", "name": "Quasar", "icon": "ph-shooting-star", "main": "repeat", "inspired_by": "Grok Bot (xAI)",
     "does": "Teach me a task once and I repeat it on schedule. I can lead a team of avatars as chief of staff, handing "
             "parts to the right one, and come back only when I'm stuck.",
     "schedule": _sched("all_day", 90), "functions": _rules("web", "apps", "files", "write", "computer", "agents")},
    {"id": "vector", "name": "Vector", "icon": "ph-cpu", "main": "local", "inspired_by": "MausBot (open source)",
     "does": "Local-first crew member: I run on the models on this PC, hand coding to Claude Code, and every file or "
             "outside access waits for your click.",
     "schedule": _sched("on_call"), "model": "local",
     "functions": _rules("files", "write", "code", "web", ask=("files", "write", "code", "web"))},
    {"id": "parallax", "name": "Parallax", "icon": "ph-binoculars", "main": "watch", "inspired_by": "",
     "does": "I watch what you point me at — prices, news, a web page, the weather — and only speak up when something "
             "changes that you'd want to know.",
     "schedule": _sched("all_year", 30), "functions": _rules("web", "send", ask=("send",))},
    {"id": "lemma", "name": "Lemma", "icon": "ph-function", "main": "study", "inspired_by": "",
     "does": "Study partner: I research a topic, explain it step by step, quiz you, and keep tidy notes.",
     "schedule": _sched("on_call"), "functions": _rules("web", "learn", "files", "write", "pictures")},
    {"id": "perigee", "name": "Perigee", "icon": "ph-envelope-simple-open", "main": "inbox", "inspired_by": "",
     "does": "Inbox and calendar: I sort new mail, flag what needs you, spot clashing events and draft replies for you "
             "to approve.",
     "schedule": _sched("all_day", 60, "08:00", "20:00"), "functions": _rules("email", "apps", "send", ask=("send",))},
]
DEFAULT_IDS = [d["id"] for d in DEFAULTS]

# ---------------------------------------------------------------------------
# Validation — an avatar is data
# ---------------------------------------------------------------------------

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class AvatarError(ValueError):
    pass


def _text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _block(value: Any, limit: int) -> str:
    """Like ``_text`` but keeps line breaks, for the long boxes (what it does, its own personality).

    Flattening them made the Avatars tab's Save button useless: the owner's text came back from the server
    different from what the box held, so the editor still thought there was something to save.
    """
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in str(value or "").replace("\r\n", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()[:limit]


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _short_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


def clean(raw: Dict[str, Any], base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return a valid avatar from ``raw`` laid over ``base``. Unknown keys and values are dropped, never stored."""
    base = base or {}
    merged = {**base, **{k: v for k, v in (raw or {}).items() if v is not None}}
    name = _text(merged.get("name"), LIMITS["name"])
    if not name:
        raise AvatarError("An avatar needs a name.")
    main = merged.get("main") if merged.get("main") in MAIN_FUNCTIONS else "custom"

    sched_in = merged.get("schedule") if isinstance(merged.get("schedule"), dict) else {}
    old = base.get("schedule") or _sched("on_call")
    mode = sched_in.get("mode", old.get("mode"))
    days = sched_in.get("days", old.get("days", list(range(7))))
    schedule = {
        "mode": mode if mode in SCHEDULES else "on_call",
        "every_minutes": max(15, min(1440, int(_num(sched_in.get("every_minutes", old.get("every_minutes", 60)), 60) or 60))),
        "start": sched_in.get("start") if _TIME.match(str(sched_in.get("start", ""))) else old.get("start", "08:00"),
        "end": sched_in.get("end") if _TIME.match(str(sched_in.get("end", ""))) else old.get("end", "20:00"),
        "days": sorted({int(d) for d in days if str(d).isdigit() and 0 <= int(d) <= 6}) or list(range(7)),
    }

    rules_in = merged.get("functions") if isinstance(merged.get("functions"), dict) else {}
    functions = {"talk": "allow"}
    for key, rule in rules_in.items():
        if key in FUNCTIONS and rule in ("allow", "ask"):
            functions[key] = "ask" if FUNCTIONS[key].get("always_ask") else rule

    def items(key: str, limit: int, shape: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        out = []
        for item in (merged.get(key) or [])[:limit]:
            if isinstance(item, dict):
                shaped = shape(item)
                if shaped:
                    out.append(shaped)
        return out

    def goal(g: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        text = _text(g.get("text"), 300)
        if not text:
            return None
        steps = [{"text": _text(s.get("text"), 200), "done": bool(s.get("done"))}
                 for s in (g.get("steps") or [])[:12] if isinstance(s, dict) and _text(s.get("text"), 200)]
        return {"id": str(g.get("id") or _short_id("g"))[:12], "text": text, "steps": steps,
                "status": g.get("status") if g.get("status") in ("open", "done", "paused") else "open",
                "progress": _text(g.get("progress"), 400)}

    def watch(w: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        what = _text(w.get("what"), 300)
        if not what:
            return None
        return {"id": str(w.get("id") or _short_id("w"))[:12], "what": what,
                "every_minutes": max(15, min(10080, int(_num(w.get("every_minutes"), 60) or 60))),
                "phone": bool(w.get("phone")), "last_at": _num(w.get("last_at"), 0),
                "last": _text(w.get("last"), 400)}

    def lesson(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        title = _text(item.get("name"), 60)
        steps = [_text(s, 240) for s in (item.get("steps") or [])[:20] if _text(s, 240)]
        if not title or not steps:
            return None
        return {"id": str(item.get("id") or _short_id("l"))[:12], "name": title, "steps": steps,
                "repeat": item.get("repeat") if item.get("repeat") in REPEATS else "", "last_at": _num(item.get("last_at"), 0)}

    notes = [_text(n, 300) for n in (merged.get("notes") or [])[-LIMITS["notes"]:] if _text(n, 300)]
    personality = merged.get("personality")
    if personality not in personality_options() or (personality == "custom" and not _block(merged.get("personality_custom"), 600)):
        personality = DEFAULT_PERSONALITIES.get(str(merged.get("id") or ""), FALLBACK_PERSONALITY)
    return {
        "id": str(merged.get("id") or _short_id("av"))[:24],
        "name": name,
        "icon": _text(merged.get("icon"), 40) if str(merged.get("icon", "")).startswith("ph-") else "ph-user-circle",
        "main": main,
        "main_custom": _text(merged.get("main_custom"), 80) if main == "custom" else "",
        "does": _block(merged.get("does"), LIMITS["text"]),
        "inspired_by": _text(merged.get("inspired_by"), 60),
        "personality": personality,
        "personality_custom": _block(merged.get("personality_custom"), 600) if personality == "custom" else "",
        "enabled": bool(merged.get("enabled")),
        "model": merged.get("model") if merged.get("model") in MODELS else "",
        "max_runs_per_day": max(1, min(96, int(_num(merged.get("max_runs_per_day"), 24) or 24))),
        "schedule": schedule,
        "functions": functions,
        "goals": items("goals", LIMITS["goals"], goal),
        "watches": items("watches", LIMITS["watches"], watch),
        "lessons": items("lessons", LIMITS["lessons"], lesson),
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# The store: shipped defaults + the owner's records
# ---------------------------------------------------------------------------

_lock = threading.RLock()


def _path():
    return data_path("avatars.json")


def _blank_state() -> Dict[str, Any]:
    return {"avatars": {}, "hidden": [], "runtime": {}}


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("avatars"), dict):
            data.setdefault("hidden", [])
            data.setdefault("runtime", {})
            return data
    except (OSError, ValueError):
        pass
    return _blank_state()


def _save(state: Dict[str, Any]) -> None:
    path = _path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(path)


def _default(avatar_id: str) -> Optional[Dict[str, Any]]:
    for d in DEFAULTS:
        if d["id"] == avatar_id:
            return clean(d)
    return None


def _runtime(state: Dict[str, Any], avatar_id: str) -> Dict[str, Any]:
    rt = state["runtime"].setdefault(avatar_id, {})
    rt.setdefault("chat_id", "")
    rt.setdefault("last_tick", 0.0)
    rt.setdefault("day", "")
    rt.setdefault("runs_today", 0)
    rt.setdefault("activity", [])
    return rt


def _view(avatar: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    rt = _runtime(state, avatar["id"])
    return {**avatar, "builtin": avatar["id"] in DEFAULT_IDS, "edited": avatar["id"] in state["avatars"],
            "busy": avatar["id"] in _busy, "runs_today": rt["runs_today"] if rt["day"] == _today() else 0,
            "last_tick": rt["last_tick"], "chat_id": rt["chat_id"], "activity": rt["activity"][-12:][::-1]}


def list_avatars() -> List[Dict[str, Any]]:
    with _lock:
        state = _load()
        out = [_view(state["avatars"].get(i) or _default(i), state) for i in DEFAULT_IDS if i not in state["hidden"]]
        out += [_view(a, state) for i, a in state["avatars"].items() if i not in DEFAULT_IDS]
        return out


def get(avatar_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        state = _load()
        if avatar_id in state["hidden"]:
            return None
        found = state["avatars"].get(avatar_id) or _default(avatar_id)
        return _view(found, state) if found else None


def find(name_or_id: str) -> Optional[Dict[str, Any]]:
    """By id, or by name ignoring case and a leading @ — how chat refers to them."""
    wanted = (name_or_id or "").strip().lstrip("@").lower()
    if not wanted:
        return None
    avatars = list_avatars()
    for a in avatars:
        if a["id"] == wanted or a["name"].lower() == wanted:
            return a
    starts = [a for a in avatars if a["name"].lower().startswith(wanted)]
    return starts[0] if len(starts) == 1 else None


def _record(avatar_id: str) -> Dict[str, Any]:
    """The stored (not view) record, for editing. Caller holds the lock."""
    state = _load()
    record = state["avatars"].get(avatar_id) or _default(avatar_id)
    if record is None or avatar_id in state["hidden"]:
        raise AvatarError("No such avatar.")
    return record


def create(raw: Dict[str, Any], template: str = "") -> Dict[str, Any]:
    """A new avatar, blank or copied from another (``template``)."""
    with _lock:
        state = _load()
        if len(state["avatars"]) >= 60:
            raise AvatarError("That is a lot of avatars — delete one first.")
        base = {}
        if template:
            source = state["avatars"].get(template) or _default(template)
            if source is None:
                raise AvatarError("No such avatar to copy.")
            base = {k: v for k, v in source.items() if k not in ("id", "goals", "watches", "lessons", "notes")}
            base["name"] = f"{source['name']} copy"
        avatar = clean({**raw, "id": _short_id("av")}, base or {"schedule": _sched("on_call"), "functions": _rules("web")})
        avatar["enabled"] = bool(raw.get("enabled", False))
        state["avatars"][avatar["id"]] = avatar
        _save(state)
        return _view(avatar, state)


def update(avatar_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    with _lock:
        record = _record(avatar_id)
        state = _load()
        avatar = clean({**changes, "id": avatar_id}, record)
        state["avatars"][avatar_id] = avatar
        _save(state)
    _publish(avatar_id)
    return get(avatar_id) or avatar


def reset(avatar_id: str) -> Dict[str, Any]:
    """A shipped avatar goes back to how it shipped (switched off). Its chat and activity stay."""
    if avatar_id not in DEFAULT_IDS:
        raise AvatarError("Only a built-in avatar can be reset.")
    with _lock:
        state = _load()
        state["avatars"].pop(avatar_id, None)
        if avatar_id in state["hidden"]:
            state["hidden"].remove(avatar_id)
        _save(state)
    return get(avatar_id)  # type: ignore[return-value]


def delete(avatar_id: str) -> bool:
    """A custom avatar is removed; a built-in one is hidden (Reset All brings it back). Its chat is kept."""
    with _lock:
        state = _load()
        if avatar_id in DEFAULT_IDS:
            if avatar_id in state["hidden"]:
                return False
            state["hidden"].append(avatar_id)
            state["avatars"].pop(avatar_id, None)
        elif state["avatars"].pop(avatar_id, None) is None:
            return False
        _save(state)
        return True


def restore_defaults() -> List[Dict[str, Any]]:
    with _lock:
        state = _load()
        state["hidden"] = []
        _save(state)
    return list_avatars()


def add_item(avatar_id: str, kind: str, item: Dict[str, Any]) -> Dict[str, Any]:
    """Append a goal, watch or lesson (validated with the rest)."""
    if kind not in ("goals", "watches", "lessons"):
        raise AvatarError("Unknown list.")
    with _lock:
        record = _record(avatar_id)
        if len(record.get(kind) or []) >= LIMITS[kind]:
            raise AvatarError(f"{record['name']} already has the most {kind} it can hold.")
        before = len(record.get(kind) or [])
        avatar = update(avatar_id, {kind: [*(record.get(kind) or []), item]})
        if len(avatar.get(kind) or []) == before:
            raise AvatarError("That was empty — say what it should be.")
        return avatar


def remove_item(avatar_id: str, kind: str, item_id: str) -> Dict[str, Any]:
    with _lock:
        record = _record(avatar_id)
        return update(avatar_id, {kind: [i for i in (record.get(kind) or []) if i.get("id") != item_id]})


def add_note(avatar_id: str, note: str) -> None:
    with _lock:
        record = _record(avatar_id)
        update(avatar_id, {"notes": [*(record.get("notes") or []), note]})


# ---------------------------------------------------------------------------
# The guard every avatar turn runs behind
# ---------------------------------------------------------------------------

#: Avatar tools an avatar may use about itself; managing avatars (create, switch on) stays with the owner.
SELF_TOOLS = frozenset({"avatar_list", "avatar_note", "avatar_progress", "avatar_goal", "avatar_watch"})
TEAM_TOOLS = frozenset({"avatar_ask", "avatar_team"})


def function_for(category: str) -> str:
    for key, spec in FUNCTIONS.items():
        if (category or "general") in spec["categories"]:
            return key
    return ""


class AvatarGuard:
    """Deny by default. Holds the avatar's id so avatar tools know who is speaking."""

    def __init__(self, avatar: Dict[str, Any]) -> None:
        self.avatar_id = avatar["id"]
        self.name = avatar["name"]
        self.rules = dict(avatar.get("functions") or {})

    def __call__(self, name: str, category: str) -> None:
        from permissions import PermissionDenied

        category = category or "general"
        if name in SELF_TOOLS:
            return
        if name in TEAM_TOOLS:
            if "agents" in self.rules:
                return
            raise PermissionDenied(f"{self.name} cannot hand work to other avatars — 'Team up' is off for it.")
        if category in NEVER or (category == "ui" and name not in UI_OK) or name.startswith("avatar_"):
            raise PermissionDenied(f"Blocked: avatars never use {name}. Tell the owner what you wanted to do.")
        if category == "ui":
            return
        key = function_for(category)
        if not key or key not in self.rules:
            label = FUNCTIONS[key]["label"] if key else category
            raise PermissionDenied(f"Blocked: {self.name} is not allowed to {label.lower()} ({name}). The owner can "
                                   "switch that function on in Avatars; say what you would have done.")
        if self.rules[key] == "ask":
            from permissions import ask

            ask(category, f"{self.name} wants to use {name}", f"Avatar {self.name} · {FUNCTIONS[key]['label']}")


def _current_avatar_id() -> str:
    try:
        from tool_context import current

        ctx = current()
        return str(getattr(getattr(ctx, "guard", None), "avatar_id", "") or "")
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Running a turn
# ---------------------------------------------------------------------------

_busy: set = set()
_avatar_locks: Dict[str, threading.Lock] = {}
_depth = threading.local()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _publish(avatar_id: str) -> None:
    try:
        from agent_events import publish_ui

        publish_ui("avatar.update", id=avatar_id)
    except Exception:  # noqa: BLE001
        pass


def note_for(avatar: Dict[str, Any]) -> str:
    """What the avatar is told on every turn: who it is, what it may use, its goals, watches, lessons and notes."""
    main = avatar.get("main_custom") or MAIN_FUNCTIONS.get(avatar["main"], "")
    lines = [f"You are {avatar['name']}, one of the owner's Ichos avatars. Main function: {main}.",
             f"What you do: {avatar['does'] or '(the owner has not said yet — ask them)'}",
             f"Your personality (how you sound): {personality_text(avatar)}",
             "Functions you may use: " + ", ".join(
                 f"{FUNCTIONS[k]['label']}{' (asks the owner first)' if r == 'ask' else ''}"
                 for k, r in avatar["functions"].items() if k in FUNCTIONS) + ". Anything else is blocked — say so "
             "plainly instead of trying another way.",
             "Keep answers short. Progress on a goal is only recorded when you call avatar_progress, and a memory "
             "only when you call avatar_note — never say you marked or remembered something without that call."]
    open_goals = [g for g in avatar.get("goals") or [] if g["status"] == "open"]
    if open_goals:
        lines.append("Your goals:")
        for g in open_goals:
            steps = "; ".join(("[x] " if s["done"] else "[ ] ") + s["text"] for s in g["steps"])
            lines.append(f"- ({g['id']}) {g['text']}" + (f" — plan: {steps}" if steps else "")
                         + (f" — so far: {g['progress']}" if g["progress"] else ""))
    if avatar.get("watches"):
        lines.append("You are watching: " + "; ".join(w["what"] for w in avatar["watches"]))
    if avatar.get("lessons"):
        lines.append("Tasks you were taught: " + "; ".join(l["name"] for l in avatar["lessons"]))
    if avatar.get("notes"):
        lines.append("What you remember: " + " | ".join(avatar["notes"][-15:]))
    return "\n".join(lines)


def _chat_turn(avatar: Dict[str, Any], text: str) -> str:
    """One turn in the avatar's own chat, behind its guard. Tests replace this."""
    import server

    store = server._shared_chat_store()
    with _lock:
        state = _load()
        rt = _runtime(state, avatar["id"])
        chat_id = rt["chat_id"]
        if not chat_id or not store.exists(chat_id):
            chat_id = store.create(title=f"Avatar · {avatar['name']}", activate=False)
            rt["chat_id"] = chat_id
            _save(state)
    from persona_scope import badge_avatar_chat

    # The badge is what makes the turn speak from this avatar's bank (persona_scope.prepare_turn) — and only here.
    badge_avatar_chat(store, chat_id, avatar)
    service = server._get_service(chat_id)
    guard_before = getattr(service, "tool_guard", None)
    service.tool_guard = AvatarGuard(avatar)
    try:
        service.set_turn_context("")
        result = service.chat_turn(text, sink=lambda _event: None, role="local", turn_id=uuid.uuid4().hex[:12],
                                   provider="ollama" if avatar.get("model") == "local" else None)
    finally:
        service.tool_guard = guard_before
    return str((result or {}).get("reply") or "") if isinstance(result, dict) else str(result or "")


_TURN: Callable[[Dict[str, Any], str], str] = _chat_turn


def run(avatar_id: str, text: str, kind: str = "talk", wait: float = 600) -> Dict[str, Any]:
    """Run one avatar turn and log it. One turn per avatar at a time; ``wait=0`` gives up at once if it is busy."""
    avatar = get(avatar_id)
    if avatar is None:
        raise AvatarError("No such avatar.")
    if getattr(_depth, "n", 0) >= 3:
        raise AvatarError("Avatars are handing this around too much — stopping here.")
    lock = _avatar_locks.setdefault(avatar_id, threading.Lock())
    got = lock.acquire(timeout=wait) if wait else lock.acquire(blocking=False)
    if not got:
        raise AvatarError(f"{avatar['name']} is busy with something else.")
    _busy.add(avatar_id)
    _publish(avatar_id)
    _depth.n = getattr(_depth, "n", 0) + 1
    started = time.time()
    ok = True
    try:
        reply = _TURN(avatar, text)
    except Exception as error:  # noqa: BLE001 - logged, shown, never raised into the scheduler
        ok, reply = False, f"{type(error).__name__}: {error}"
    finally:
        _depth.n -= 1
        _busy.discard(avatar_id)
        lock.release()
    entry = {"at": started, "kind": kind, "input": _text(text, 200), "reply": (reply or "")[:1500], "ok": ok,
             "seconds": round(time.time() - started, 1)}
    with _lock:
        state = _load()
        rt = _runtime(state, avatar_id)
        if rt["day"] != _today():
            rt["day"], rt["runs_today"] = _today(), 0
        rt["runs_today"] += 1
        rt["activity"] = (rt["activity"] + [entry])[-LIMITS["activity"]:]
        _save(state)
    _publish(avatar_id)
    return {"avatar": avatar["name"], "id": avatar_id, **entry}


def check_in_text(avatar: Dict[str, Any]) -> str:
    goals = any(g["status"] == "open" for g in avatar.get("goals") or [])
    return ("[Check-in] It is your scheduled time. Do your main job now, using your tools — check what it says to "
            "check: " + (avatar["does"] or "(no job written yet: ask the owner for one)")
            + (" Then work on the next step of your open goals and record it with avatar_progress." if goals else "")
            + " Finish with a two-line update for the owner. Reply only NOTHING TO DO when you checked and there is "
              "truly nothing new worth their attention.")


def watch_text(watch: Dict[str, Any]) -> str:
    return (f"[Watch] Check this now: {watch['what']}. Last time you found: {watch['last'] or '(first check)'}. "
            "If something changed that the owner would want to know, start your reply with ALERT: and say it in one "
            "or two lines. Otherwise reply only: NOTHING NEW.")


def lesson_text(lesson: Dict[str, Any]) -> str:
    steps = "\n".join(f"{n}. {s}" for n, s in enumerate(lesson["steps"], 1))
    return (f"[Lesson: {lesson['name']}] The owner taught you this task. Do it now, step by step, the way they "
            f"showed you:\n{steps}\nReport what you did in two lines. If a step is impossible, stop and say why.")


def run_watch(avatar_id: str, watch_id: str, wait: float = 600) -> Dict[str, Any]:
    avatar = get(avatar_id)
    watch = next((w for w in (avatar or {}).get("watches") or [] if w["id"] == watch_id), None)
    if avatar is None or watch is None:
        raise AvatarError("No such watch.")
    result = run(avatar_id, watch_text(watch), kind="watch", wait=wait)
    reply = result["reply"].strip()
    alert = reply.upper().startswith("ALERT")
    with _lock:
        record = _record(avatar_id)
        watches = [{**w, "last_at": time.time(), "last": reply[:400] if result["ok"] else w.get("last", "")}
                   if w["id"] == watch_id else w for w in record["watches"]]
        update(avatar_id, {"watches": watches})
    if alert:
        _alert(avatar, reply.split(":", 1)[-1].strip(), phone=watch.get("phone"))
    return {**result, "alert": alert}


def run_lesson(avatar_id: str, lesson_id: str, wait: float = 600) -> Dict[str, Any]:
    avatar = get(avatar_id)
    lesson = next((l for l in (avatar or {}).get("lessons") or [] if l["id"] == lesson_id), None)
    if avatar is None or lesson is None:
        raise AvatarError("No such lesson.")
    result = run(avatar_id, lesson_text(lesson), kind="lesson", wait=wait)
    with _lock:
        record = _record(avatar_id)
        update(avatar_id, {"lessons": [{**l, "last_at": time.time()} if l["id"] == lesson_id else l
                                       for l in record["lessons"]]})
    return result


def _alert(avatar: Dict[str, Any], text: str, phone: bool = False) -> None:
    try:
        from landscape_tools import tool_ui_notify

        tool_ui_notify(f"{avatar['name']}: {text[:240]}", "info")
    except Exception:  # noqa: BLE001
        pass
    if phone:
        try:
            import whatsapp_link

            current = whatsapp_link._LINK
            if current is not None and current.state.get("status") == "linked":
                threading.Thread(target=lambda: current.send(f"{avatar['name']}: {text[:600]}", origin="avatar"),
                                 daemon=True).start()
        except Exception:  # noqa: BLE001
            log.info("avatar phone alert not sent", exc_info=True)


def team(names: List[str], task: str) -> Dict[str, Any]:
    """Grok Bot's group chat: the first avatar leads (chief of staff), each next one adds its part with everything said
    so far, and the lead closes with the answer. At most six avatars, so at most seven turns."""
    found = []
    for n in names[:LIMITS["team"]]:
        a = find(n)
        if a and a["id"] not in {f["id"] for f in found}:
            found.append(a)
    if len(found) < 2:
        raise AvatarError("A team needs at least two avatars I can find by name.")
    lead, transcript = found[0], []
    plan = run(lead["id"], f"[Team lead] You lead {', '.join(a['name'] for a in found[1:])} on this task: {task}\n"
               "Split it: one line per teammate saying what they should do. Keep it short.", kind="team")
    transcript.append(plan)
    for member in found[1:]:
        said = "\n".join(f"{t['avatar']}: {t['reply'][:600]}" for t in transcript)
        transcript.append(run(member["id"], f"[Team] Task: {task}\nSo far:\n{said}\nDo your part now and say what "
                                            "you did in a few lines.", kind="team"))
    said = "\n".join(f"{t['avatar']}: {t['reply'][:600]}" for t in transcript)
    final = run(lead["id"], f"[Team wrap-up] Task: {task}\nWhat the team did:\n{said}\nGive the owner the final "
                            "answer in a few lines.", kind="team")
    transcript.append(final)
    return {"task": task, "lead": lead["name"], "turns": transcript, "answer": final["reply"]}


# ---------------------------------------------------------------------------
# The clock: check-ins, watches, lessons — only for avatars switched on
# ---------------------------------------------------------------------------


def _hm(value: str) -> tuple:
    hour, minute = value.split(":")
    return int(hour), int(minute)


def due_work(avatar: Dict[str, Any], now: Optional[datetime] = None, rt: Optional[Dict[str, Any]] = None) -> List[tuple]:
    """What is due for one avatar: ``[("checkin", ""), ("watch", id), ("lesson", id)]``. Pure, for the tests."""
    if not avatar.get("enabled"):
        return []
    now = now or datetime.now()
    stamp = now.timestamp()
    rt = rt or {}
    if rt.get("day") == now.strftime("%Y-%m-%d") and rt.get("runs_today", 0) >= avatar["max_runs_per_day"]:
        return []
    sched = avatar["schedule"]
    if now.weekday() not in sched["days"]:
        return []
    if sched["mode"] == "all_day" and not (_hm(sched["start"]) <= (now.hour, now.minute) < _hm(sched["end"])):
        return []
    work: List[tuple] = []
    if sched["mode"] != "on_call" and stamp - float(rt.get("last_tick") or 0) >= sched["every_minutes"] * 60:
        work.append(("checkin", ""))
    for w in avatar.get("watches") or []:
        if stamp - w["last_at"] >= w["every_minutes"] * 60:
            work.append(("watch", w["id"]))
    for lesson in avatar.get("lessons") or []:
        gap = {"daily": 86400, "weekly": 604800}.get(lesson["repeat"])
        if gap and stamp - lesson["last_at"] >= gap - 300:
            work.append(("lesson", lesson["id"]))
    return work


def tick(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """One pass of the clock. Busy avatars are skipped, not waited on."""
    done = []
    for avatar in list_avatars():
        with _lock:
            rt = dict(_runtime(_load(), avatar["id"]))
        for kind, item in due_work(avatar, now, rt):
            try:
                if kind == "checkin":
                    with _lock:
                        state = _load()
                        _runtime(state, avatar["id"])["last_tick"] = (now or datetime.now()).timestamp()
                        _save(state)
                    result = run(avatar["id"], check_in_text(avatar), kind="check-in", wait=0)
                    if result["ok"] and "NOTHING TO DO" not in result["reply"].upper():
                        _alert(avatar, result["reply"])
                elif kind == "watch":
                    result = run_watch(avatar["id"], item, wait=0)
                else:
                    result = run_lesson(avatar["id"], item, wait=0)
                done.append(result)
            except AvatarError:
                continue  # busy, or edited away meanwhile
            except Exception:  # noqa: BLE001 - the clock keeps going
                log.warning("avatar %s %s failed", avatar["id"], kind, exc_info=True)
    return done


_started = threading.Event()


def _loop() -> None:
    while True:
        try:
            tick()
        except Exception:  # noqa: BLE001
            log.warning("avatar clock failed", exc_info=True)
        time.sleep(60)


def start_in_background() -> None:
    if _started.is_set():
        return
    _started.set()
    threading.Thread(target=_loop, name="nyx-avatars", daemon=True).start()


# ---------------------------------------------------------------------------
# Normal chat's tools
# ---------------------------------------------------------------------------


def _who(avatar: str, fallback: str = "") -> Dict[str, Any]:
    """The named avatar; unnamed, the avatar whose turn this is, else ``fallback``."""
    speaking = _current_avatar_id()
    found = find(avatar) if avatar else get(speaking) if speaking else find(fallback) if fallback else None
    if found is None:
        names = ", ".join(a["name"] for a in list_avatars())
        raise AvatarError(f"No avatar called {avatar!r}. The avatars are: {names}.")
    return found


def _tool(fn: Callable[..., str]) -> Callable[..., str]:
    def wrapped(*args: Any, **kwargs: Any) -> str:
        try:
            return fn(*args, **kwargs)
        except AvatarError as error:
            return f"Error: {error}"
    wrapped.__name__ = fn.__name__
    wrapped.__doc__ = fn.__doc__
    return wrapped


@_tool
def tool_avatar_list() -> str:
    lines = []
    for a in list_avatars():
        state = "on" if a["enabled"] else "off"
        when = SCHEDULES[a["schedule"]["mode"]]
        if a["schedule"]["mode"] != "on_call":
            when += f", every {a['schedule']['every_minutes']} min"
        lines.append(f"- @{a['name']} ({state}; {MAIN_FUNCTIONS.get(a['main'], '')}; {when}): {a['does'][:140]}")
    return "Avatars (talk to one with avatar_ask, or the owner can write @Name):\n" + "\n".join(lines)


@_tool
def tool_avatar_ask(avatar: str, message: str) -> str:
    found = _who(avatar)
    if _current_avatar_id() == found["id"]:
        return "Error: that is you."
    result = run(found["id"], message, kind="talk")
    if not result["ok"]:
        return f"{found['name']} failed: {result['reply']}"
    # Relayed, not adopted: the avatar's voice stays in its own chat (persona_scope.py).
    return (f"{found['name']} answered in its own chat (quote or sum it up in your own voice; do not take on its "
            f"personality):\n{result['reply']}")


@_tool
def tool_avatar_team(avatars: str, task: str) -> str:
    result = team([n for n in re.split(r"[,\s]+", avatars) if n], task)
    return f"Team led by {result['lead']} ({len(result['turns'])} turns). Final answer:\n{result['answer']}"


@_tool
def tool_avatar_create(name: str, does: str, main_function: str = "custom", schedule: str = "on_call",
                       every_minutes: int = 60, functions: str = "web", copy_of: str = "", personality: str = "") -> str:
    rules = {}
    for key in re.split(r"[,\s]+", functions or ""):
        key = key.strip().lower()
        if key in FUNCTIONS:
            rules[key] = FUNCTIONS[key]["default"]
    raw: Dict[str, Any] = {"name": name, "does": does, "main": main_function if main_function in MAIN_FUNCTIONS else "custom",
                           "schedule": {"mode": schedule, "every_minutes": every_minutes}}
    if personality:
        preset = personality.strip().lower().replace(" ", "_")
        raw.update({"personality": preset} if preset in personality_options() else
                   {"personality": "custom", "personality_custom": personality})
    if rules or not copy_of:
        raw["functions"] = rules
    template = (find(copy_of) or {}).get("id", "") if copy_of else ""
    avatar = create(raw, template=template)
    _open()
    return (f"Made the avatar {avatar['name']} ({SCHEDULES[avatar['schedule']['mode']]}). It is switched OFF — the owner "
            "switches it on in Avatars, or you can with avatar_switch if they asked.")


@_tool
def tool_avatar_switch(avatar: str, on: bool = True) -> str:
    found = _who(avatar)
    update(found["id"], {"enabled": bool(on)})
    return f"{found['name']} is now {'on' if on else 'off'}."


@_tool
def tool_avatar_goal(goal: str, steps: str = "", avatar: str = "") -> str:
    found = _who(avatar)
    plan = [{"text": s.strip(" -•")} for s in re.split(r"\n|;", steps or "") if s.strip(" -•")]
    updated = add_item(found["id"], "goals", {"text": goal, "steps": plan})
    return f"{found['name']} now has the goal: {goal}" + ("" if updated["enabled"] else " (it is switched off, so it "
                                                           "works on it only when asked).")


@_tool
def tool_avatar_progress(goal: str, progress: str = "", step_done: str = "", finished: bool = False,
                         avatar: str = "") -> str:
    found = _who(avatar)
    with _lock:
        record = _record(found["id"])
        goals = record.get("goals") or []
        target = next((g for g in goals if g["id"] == goal or goal.lower() in g["text"].lower()), None)
        if target is None:
            return f"Error: {found['name']} has no goal matching {goal!r}."
        for step in target["steps"]:
            if step_done and step_done.lower() in step["text"].lower():
                step["done"] = True
        if progress:
            target["progress"] = progress
        if finished:
            target["status"] = "done"
        update(found["id"], {"goals": goals})
    return f"Recorded progress on '{target['text']}'."


@_tool
def tool_avatar_watch(what: str, every_minutes: int = 60, phone: bool = False, avatar: str = "") -> str:
    found = _who(avatar, "parallax")
    add_item(found["id"], "watches", {"what": what, "every_minutes": every_minutes, "phone": phone})
    extra = "" if found["enabled"] else f" {found['name']} is off — switch it on in Avatars for the watch to run."
    return f"{found['name']} will check '{what}' every {max(15, int(every_minutes or 60))} minutes.{extra}"


@_tool
def tool_avatar_teach(name: str, steps: str, repeat: str = "", avatar: str = "") -> str:
    found = _who(avatar, "quasar")
    lines = [s.strip(" -•") for s in re.split(r"\n|;", steps or "") if s.strip(" -•")]
    add_item(found["id"], "lessons", {"name": name, "steps": lines, "repeat": repeat if repeat in REPEATS else ""})
    return f"Taught {found['name']} '{name}' ({len(lines)} steps{', ' + repeat if repeat else ''})."


@_tool
def tool_avatar_note(note: str, avatar: str = "") -> str:
    found = _who(avatar)
    add_note(found["id"], note)
    return f"{found['name']} will remember that."


def _open() -> None:
    try:
        from agent_events import publish_ui

        publish_ui("ui.open_tab", tab_id="avatars")
    except Exception:  # noqa: BLE001
        pass


def register_avatar_tools(registry: Any) -> None:
    from tools import ToolParam

    who = ToolParam("avatar", "string", "Avatar name (default: the avatar speaking)", required=False)
    registry.register("avatar_list", "List the owner's avatars (always-on helpers like Orbit, Halo, Quasar, Vector, "
                      "Parallax, Lemma, Perigee and any they made): on/off, main function, schedule.", [],
                      tool_avatar_list, category="agents", label="Listing avatars")
    registry.register("avatar_ask", "Give a message or task to one avatar and get its answer. Use when the owner writes "
                      "'@Name …', 'ask Orbit…', 'have Halo…'. The avatar works in its own chat with its own allowed "
                      "functions.", [ToolParam("avatar", "string", "Avatar name, e.g. Orbit"),
                                     ToolParam("message", "string", "What to tell it")],
                      tool_avatar_ask, category="agents", label=lambda a: f"Asking {a.get('avatar', 'an avatar')}")
    registry.register("avatar_team", "Put 2–6 avatars in one group chat on a task: the first leads (chief of staff), "
                      "the others do their parts, the lead gives the final answer.",
                      [ToolParam("avatars", "string", "Names, comma separated; the first leads"),
                       ToolParam("task", "string", "The task")], tool_avatar_team, category="agents",
                      label="Avatar team at work")
    registry.register("avatar_create", "Make a new avatar from chat. functions: comma list of "
                      + ", ".join(FUNCTIONS) + ". main_function: " + ", ".join(MAIN_FUNCTIONS)
                      + ". schedule: on_call, all_day or all_year. It starts switched off.",
                      [ToolParam("name", "string", "Its name"), ToolParam("does", "string", "What it does"),
                       ToolParam("main_function", "string", "Main function", required=False,
                                 enum_values=list(MAIN_FUNCTIONS)),
                       ToolParam("schedule", "string", "When it runs", required=False, enum_values=list(SCHEDULES)),
                       ToolParam("every_minutes", "integer", "How often it checks in (15–1440)", required=False),
                       ToolParam("functions", "string", "What it may use, comma separated", required=False),
                       ToolParam("copy_of", "string", "Start from this avatar", required=False),
                       ToolParam("personality", "string", "A preset (" + ", ".join(k for k in personality_options()
                                 if k != "custom") + ") or the owner's own words", required=False)],
                      tool_avatar_create, category="agents", label="Making an avatar")
    registry.register("avatar_switch", "Switch an avatar on (it runs on its schedule) or off. Only when the owner asks.",
                      [ToolParam("avatar", "string", "Avatar name"),
                       ToolParam("on", "boolean", "true = on, false = off", required=False)],
                      tool_avatar_switch, category="agents", label="Switching an avatar")
    registry.register("avatar_goal", "Give an avatar a goal (with an optional plan, one step per line); it works on it "
                      "at each check-in. Default avatar: the one speaking.",
                      [ToolParam("goal", "string", "The goal"), ToolParam("steps", "string", "Plan steps", required=False),
                       who], tool_avatar_goal, category="agents", label="Setting a goal")
    registry.register("avatar_progress", "Record progress on an avatar's goal: what was done, a step finished, or the "
                      "goal finished.", [ToolParam("goal", "string", "Goal id or words from it"),
                                         ToolParam("progress", "string", "Where it stands", required=False),
                                         ToolParam("step_done", "string", "Words from the step finished", required=False),
                                         ToolParam("finished", "boolean", "The goal is done", required=False), who],
                      tool_avatar_progress, category="agents", label="Recording progress")
    registry.register("avatar_watch", "Have an avatar keep an eye on something (a price, a page, the weather, news) "
                      "and alert the owner only when it changes. Default: Parallax.",
                      [ToolParam("what", "string", "What to watch and what counts as news"),
                       ToolParam("every_minutes", "integer", "How often (15+)", required=False),
                       ToolParam("phone", "boolean", "Also text the owner's phone", required=False), who],
                      tool_avatar_watch, category="agents", label="Adding a watch")
    registry.register("avatar_teach", "Teach an avatar a task once (steps, one per line) so it can repeat it — daily, "
                      "weekly or when asked. Default: Quasar.",
                      [ToolParam("name", "string", "Name of the task"), ToolParam("steps", "string", "The steps"),
                       ToolParam("repeat", "string", "'', daily or weekly", required=False, enum_values=list(REPEATS)),
                       who], tool_avatar_teach, category="agents", label="Teaching an avatar")
    registry.register("avatar_note", "Have an avatar remember something about the owner or its work.",
                      [ToolParam("note", "string", "What to remember"), who], tool_avatar_note, category="agents",
                      label="Avatar remembers")
