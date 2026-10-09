"""Mods: one named bundle for each way the owner wants Nyx to behave or look (owner, 2026-10-08).

Modelled on Claude Code's mods, because that design lets the model understand a
setup change instead of guessing at it. What carries over, and why:

* **A change is a named thing.** "Remind me to stretch", "stop searching the web",
  "answer like a pirate" each become one mod the owner and the model can both see,
  switch off, edit or remove — not a side effect scattered over five stores that
  nobody can find again. Asked to change it later, the model edits that mod.
* **A fixed catalogue of hook points** (``PARTS``), with a table from what people ask
  to the part that does it (``catalog_text``). The model picks a shape from a menu
  it was shown instead of inventing one.
* **Validation before anything loads**, with refusals that name the part and the fix
  ("parts[1] (block_tools): 'websearch' is not a tool — did you mean 'search_web'?"),
  so the model corrects itself in the same turn.
* **Live.** Saving publishes ``mods.changed``; the next turn and every open window
  read the new set. Nothing restarts.

What does not carry over: a Claude Code mod is code. Here a mod is data the app
interprets (AGENTS.md invariant 2). And a mod narrows, never widens: it can block a
tool but not grant one, and its instructions are preferences, not permissions.
"""

from __future__ import annotations

import difflib
import json
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from paths import data_path

MAX_MODS = 60
MAX_PARTS = 12
#: Instructions from every enabled mod together, per turn. A pile of mods must not crowd out the conversation.
MAX_CONTEXT_CHARS = 4000
CONTEXT_PREFIX = "[Your mods]"

#: The mod tools themselves can never be blocked: a mod that did would lock the owner out of undoing it by asking.
UNBLOCKABLE = frozenset({"mod_help", "mod_list", "mod_save", "mod_toggle", "mod_delete"})

_ID_RE = re.compile(r"[^a-z0-9]+")
TONES = ("info", "ok", "warn")

#: kind -> (what it does, its fields). The one place the grammar is written; catalog_text reads it.
PARTS: Dict[str, Dict[str, Any]] = {
    "instructions": {
        "does": "Standing instructions Nyx follows in every turn (or only when the message mentions a word in `when`).",
        "fields": {"text": "what to do, up to 1200 characters (required)",
                   "when": "optional list of words; the instructions apply only to messages containing one"},
    },
    "command": {
        "does": "A /command in the composer menu that sends a prompt template.",
        "fields": {"name": "letters, numbers and dashes, e.g. standup (required)",
                   "template": "the prompt it sends; {args} is what follows the command (required)",
                   "description": "one line for the menu"},
    },
    "block_tools": {
        "does": "Stops Nyx using some tools. Only ever narrows what Nyx may do.",
        "fields": {"tools": "list of tool names exactly as registered (required)",
                   "reason": "said to Nyx when it tries one"},
    },
    "theme": {
        "does": "Restyles the app while the mod is on; switching it off puts back what it changed.",
        "fields": {"tokens": "any of accent, accent2, background, surface, nav, text (#rrggbb or a colour name), "
                             "radius 0-24, font (Inter, System, Segoe UI, Roboto, Georgia, JetBrains Mono, Comic Neue) (required)"},
    },
    "banner": {
        "does": "A line shown above the chat box while the mod is on.",
        "fields": {"text": "up to 200 characters (required)", "tone": "info, ok or warn"},
    },
    "status": {
        "does": "A small chip beside the chat box, like a status-line entry.",
        "fields": {"text": "up to 40 characters (required)"},
    },
    "reminder": {
        "does": "A toast every N minutes while the app is open.",
        "fields": {"text": "up to 200 characters (required)", "every_minutes": "5 to 1440 (required)"},
    },
    "start_tab": {
        "does": "The tab Nyx opens on when the app starts.",
        "fields": {"tab": "a tab name or id, e.g. Notes, Agents, or one of the owner's own tabs (required)"},
    },
}

#: What people ask for -> the part that does it. The model reads this before choosing a shape.
ASK_TO_PART: List[Tuple[str, str]] = [
    ("\"always…\", \"from now on…\", \"talk like…\", \"when I ask about X, do Y\"", "instructions (with `when` for X)"),
    ("\"give me a /standup\", \"a shortcut that…\"", "command"),
    ("\"stop searching the web\", \"never touch my email\", \"no computer control\"", "block_tools"),
    ("\"make it green\", \"rounder corners\", \"a cosy look\"", "theme"),
    ("\"show me X above the chat\", \"a note I always see\"", "banner"),
    ("\"a little label showing…\"", "status"),
    ("\"remind me to stretch every hour\"", "reminder"),
    ("\"always open on Notes\"", "start_tab"),
]


class ModError(ValueError):
    """A mod that cannot be saved. The text lists every problem and is safe to show the model and the owner."""


def _slug(text: str) -> str:
    return _ID_RE.sub("-", (text or "").lower()).strip("-")[:40]


def _closest(word: str, options: List[str]) -> str:
    # Models write tool names with the words run together or swapped ("websearch" for search_web),
    # which spelling distance alone ranks below an unrelated near-spelling ("research").
    squashed = re.sub(r"[^a-z0-9]", "", word.lower())
    whole = [o for o in options if (parts := [p for p in o.lower().split("_") if p]) and len(parts) > 1
             and all(p in squashed for p in parts) and len("".join(parts)) == len(squashed)]
    match = whole or difflib.get_close_matches(word, options, n=1, cutoff=0.5)
    return f" — did you mean {match[0]!r}?" if match else ""


def _known_tools() -> List[str]:
    """Every tool the assistant has. Loads the tool modules once if nothing registered them yet."""
    from tools import TOOL_REGISTRY

    if len(TOOL_REGISTRY.tools) < 20:
        try:
            from tool_setup import register_all_tools

            register_all_tools()
        except Exception:  # pragma: no cover - validation still runs against what did register
            pass
    return sorted(TOOL_REGISTRY.tools)


def _as_list(value: Any) -> List[str]:
    if isinstance(value, str):
        value = [w for w in re.split(r"[,\n]", value)]
    if not isinstance(value, list):
        return []
    return [str(w).strip() for w in value if str(w).strip()]


def _text(part: Dict[str, Any], key: str, limit: int, where: str, errors: List[str]) -> str:
    value = str(part.get(key) or "").strip()
    if not value:
        errors.append(f"{where}: `{key}` is required.")
    elif len(value) > limit:
        errors.append(f"{where}: `{key}` is {len(value)} characters; the most is {limit}.")
    return value


def validate_parts(parts: Any) -> List[Dict[str, Any]]:
    """Return the parts in canonical form, or raise ModError naming every problem at once.

    All problems at once, not the first: a model that fixes one refusal per turn
    takes five turns to save a mod the owner asked for in one sentence.
    """
    if isinstance(parts, str):
        try:
            parts = json.loads(parts)
        except ValueError as error:
            raise ModError(f"parts must be a JSON list of objects ({error}).") from error
    if isinstance(parts, dict):
        parts = [parts]
    if not isinstance(parts, list) or not parts:
        raise ModError("A mod needs at least one part, e.g. [{\"kind\": \"instructions\", \"text\": \"…\"}].")
    if len(parts) > MAX_PARTS:
        raise ModError(f"A mod holds at most {MAX_PARTS} parts; split it into two mods.")

    errors: List[str] = []
    clean: List[Dict[str, Any]] = []
    for index, raw in enumerate(parts):
        if not isinstance(raw, dict):
            errors.append(f"parts[{index}]: must be an object with a `kind`.")
            continue
        kind = str(raw.get("kind") or raw.get("type") or "").strip().lower()
        where = f"parts[{index}] ({kind or '?'})"
        if kind not in PARTS:
            errors.append(f"parts[{index}]: kind {kind!r} is not a part{_closest(kind, list(PARTS))} "
                          f"The kinds are: {', '.join(PARTS)}.")
            continue
        part: Dict[str, Any] = {"kind": kind}
        if kind == "instructions":
            part["text"] = _text(raw, "text", 1200, where, errors)
            when = [w.lower()[:40] for w in _as_list(raw.get("when"))][:12]
            if when:
                part["when"] = when
        elif kind == "command":
            import commands

            name = commands._slug(str(raw.get("name") or "").lstrip("/"))
            if not commands.NAME_RE.match(name or ""):
                errors.append(f"{where}: `name` must be letters, numbers and dashes, like standup.")
            elif any(c["name"] == name for c in commands.BUILTIN_COMMANDS):
                errors.append(f"{where}: /{name} is a built-in command; pick another name.")
            template = _text(raw, "template", 2000, where, errors)
            if template and "{args}" not in template:
                template = template.rstrip(" :") + ": {args}"
            part.update(name=name, template=template, description=str(raw.get("description") or "").strip()[:160])
        elif kind == "block_tools":
            wanted = _as_list(raw.get("tools"))
            if not wanted:
                errors.append(f"{where}: `tools` is required — a list of tool names.")
            known = _known_tools()
            for name in wanted:
                if name in UNBLOCKABLE:
                    errors.append(f"{where}: {name} cannot be blocked; the owner needs it to undo mods.")
                elif name not in known:
                    errors.append(f"{where}: {name!r} is not a tool{_closest(name, known)}")
            part.update(tools=wanted, reason=str(raw.get("reason") or "").strip()[:200])
        elif kind == "theme":
            from ui_state import ThemeError, validate

            tokens = raw.get("tokens") if isinstance(raw.get("tokens"), dict) else \
                {k: v for k, v in raw.items() if k != "kind"}
            tokens = {k: v for k, v in tokens.items() if k not in ("wallpaper", "density", "motion", "glass")}
            if not tokens:
                errors.append(f"{where}: `tokens` is required, e.g. {{\"accent\": \"teal\"}}.")
            else:
                try:
                    part["tokens"] = validate(tokens)
                except ThemeError as error:
                    errors.append(f"{where}: {error}")
        elif kind == "banner":
            part["text"] = _text(raw, "text", 200, where, errors)
            tone = str(raw.get("tone") or "info").lower()
            part["tone"] = tone if tone in TONES else "info"
        elif kind == "status":
            part["text"] = _text(raw, "text", 40, where, errors)
        elif kind == "reminder":
            part["text"] = _text(raw, "text", 200, where, errors)
            try:
                every = int(float(raw.get("every_minutes")))
            except (TypeError, ValueError):
                every = 0
            if not 5 <= every <= 1440:
                errors.append(f"{where}: `every_minutes` must be a number from 5 to 1440.")
            part["every_minutes"] = every
        elif kind == "start_tab":
            part["tab"] = _text(raw, "tab", 40, where, errors)
        clean.append(part)
    if errors:
        raise ModError("The mod was not saved:\n- " + "\n- ".join(errors))
    return clean


def summarize(mod: Dict[str, Any]) -> str:
    """One line per mod, the way the model and the Mods list describe it."""
    bits = []
    for part in mod.get("parts", []):
        kind = part["kind"]
        if kind == "instructions":
            bits.append("instructions" + (f" (when: {', '.join(part['when'])})" if part.get("when") else ""))
        elif kind == "command":
            bits.append(f"/{part['name']}")
        elif kind == "block_tools":
            bits.append("blocks " + ", ".join(part["tools"]))
        elif kind == "theme":
            bits.append("theme " + ", ".join(part["tokens"]))
        elif kind == "reminder":
            bits.append(f"reminder every {part['every_minutes']} min")
        else:
            bits.append(f"{kind}: {part.get('text') or part.get('tab', '')}"[:60])
    return "; ".join(bits)


class ModStore:
    """The owner's mods in ``mods.json``. Read on every tool call, so reads are cached by file mtime."""

    def __init__(self, path=None) -> None:
        self.path = path or data_path("mods.json")
        self._lock = threading.RLock()
        self._cache: Optional[Dict[str, Any]] = None
        self._mtime = -1.0

    # --- storage -----------------------------------------------------------------

    def _read(self) -> Dict[str, Any]:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return {"mods": []}
        if self._cache is not None and mtime == self._mtime:
            return self._cache
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        mods = [m for m in data.get("mods", []) if isinstance(m, dict) and m.get("id")]
        self._cache, self._mtime = {"mods": mods}, mtime
        return self._cache

    def _write(self, data: Dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)
        self._cache, self._mtime = None, -1.0
        _publish()

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(m, summary=summarize(m)) for m in self._read()["mods"]]

    def enabled(self) -> List[Dict[str, Any]]:
        return [m for m in self.list() if m.get("enabled", True)]

    def get(self, ref: str) -> Optional[Dict[str, Any]]:
        wanted = (ref or "").strip().lower()
        mods = self.list()
        for mod in mods:
            if wanted in (mod["id"], str(mod.get("name", "")).lower()):
                return mod
        hits = [m for m in mods if wanted and (_slug(wanted) == m["id"] or wanted in str(m.get("name", "")).lower())]
        return hits[0] if len(hits) == 1 else None

    # --- changes -----------------------------------------------------------------

    def save(self, name: str, parts: Any, description: str = "", mod_id: str = "",
             author: str = "owner", request: str = "", enabled: bool = True) -> Dict[str, Any]:
        """Create a mod, or replace one when ``mod_id`` names it. Applies it live when enabled."""
        name = (name or "").strip()[:60]
        if not name:
            raise ModError("A mod needs a short name, like \"Stretch reminders\".")
        clean = validate_parts(parts)
        with self._lock:
            data = {"mods": [dict(m) for m in self._read()["mods"]]}
            existing = None
            if mod_id:
                existing = next((m for m in data["mods"] if m["id"] == _slug(mod_id) or m["id"] == mod_id), None)
                if existing is None:
                    known = ", ".join(m["id"] for m in data["mods"]) or "none yet"
                    raise ModError(f"No mod with id {mod_id!r} to replace (ids: {known}). Leave mod_id out to make a new one.")
            elif any(str(m.get("name", "")).lower() == name.lower() for m in data["mods"]):
                raise ModError(f"There is already a mod called {name!r}. Pass its mod_id to change it, or pick another name.")
            if existing is None and len(data["mods"]) >= MAX_MODS:
                raise ModError(f"There are already {MAX_MODS} mods; delete one first.")
            self._check_command_clash(data["mods"], clean, existing)

            now = time.time()
            if existing is not None:
                self._unapply(existing)
                existing.update(name=name, description=description.strip()[:300] or existing.get("description", ""),
                                parts=clean, updated=now, enabled=enabled)
                if request:
                    existing["request"] = request.strip()[:500]
                mod = existing
            else:
                base = _slug(name) or "mod"
                taken = {m["id"] for m in data["mods"]}
                mod_key, n = base, 2
                while mod_key in taken:
                    mod_key, n = f"{base}-{n}", n + 1
                mod = {"id": mod_key, "name": name, "description": description.strip()[:300], "enabled": enabled,
                       "author": author if author in ("owner", "assistant") else "owner", "created": now,
                       "updated": now, "request": request.strip()[:500], "parts": clean}
                data["mods"].append(mod)
            if mod.get("enabled", True):
                self._apply(mod)
            self._write(data)
            return dict(mod, summary=summarize(mod))

    def set_enabled(self, ref: str, enabled: bool) -> Dict[str, Any]:
        with self._lock:
            data = {"mods": [dict(m) for m in self._read()["mods"]]}
            found = self.get(ref)
            mod = next((m for m in data["mods"] if found and m["id"] == found["id"]), None)
            if mod is None:
                raise ModError(_no_such(ref, data["mods"]))
            if bool(mod.get("enabled", True)) != enabled:
                if enabled:
                    self._check_command_clash([m for m in data["mods"] if m is not mod], mod["parts"], None)
                    self._apply(mod)
                else:
                    self._unapply(mod)
                mod["enabled"] = enabled
                mod["updated"] = time.time()
                self._write(data)
            return dict(mod, summary=summarize(mod))

    def delete(self, ref: str) -> Dict[str, Any]:
        with self._lock:
            data = {"mods": [dict(m) for m in self._read()["mods"]]}
            found = self.get(ref)
            mod = next((m for m in data["mods"] if found and m["id"] == found["id"]), None)
            if mod is None:
                raise ModError(_no_such(ref, data["mods"]))
            if mod.get("enabled", True):
                self._unapply(mod)
            data["mods"] = [m for m in data["mods"] if m is not mod]
            self._write(data)
            return mod

    @staticmethod
    def _check_command_clash(others: List[Dict[str, Any]], parts: List[Dict[str, Any]], existing: Any) -> None:
        mine = {p["name"] for p in parts if p["kind"] == "command"}
        for other in others:
            if other is existing or not other.get("enabled", True):
                continue
            theirs = {p["name"] for p in other.get("parts", []) if p["kind"] == "command"}
            clash = mine & theirs
            if clash:
                raise ModError(f"/{sorted(clash)[0]} already belongs to the mod {other['name']!r}; "
                               "pick another name or change that mod.")

    # --- side effects that outlive a turn (the theme) ------------------------------

    @staticmethod
    def _apply(mod: Dict[str, Any]) -> None:
        """Apply the theme and remember what it replaced, so switching the mod off can put it back."""
        tokens: Dict[str, Any] = {}
        for part in mod.get("parts", []):
            if part["kind"] == "theme":
                tokens.update(part["tokens"])
        if not tokens:
            mod.pop("applied", None)
            return
        from ui_state import UI_STATE

        current = UI_STATE.snapshot()["theme"]
        mod["applied"] = {"theme": tokens, "prior": {k: current.get(k) for k in tokens}}
        UI_STATE.update_theme(tokens)

    @staticmethod
    def _unapply(mod: Dict[str, Any]) -> None:
        """Undo the mod's theme — but only the tokens still showing what it set. A later change by hand stays."""
        applied = mod.pop("applied", None) or {}
        tokens, prior = applied.get("theme") or {}, applied.get("prior") or {}
        if not tokens:
            return
        from ui_state import UI_STATE

        current = UI_STATE.snapshot()["theme"]
        restore = {k: prior[k] for k, v in tokens.items() if current.get(k) == v and prior.get(k) is not None}
        if restore:
            UI_STATE.update_theme(restore)

    # --- what the running app reads -------------------------------------------------

    def blocked(self, tool: str) -> Optional[str]:
        """The refusal for ``tool`` when an enabled mod blocks it, else None. Called on every tool call."""
        if tool in UNBLOCKABLE:
            return None
        for mod in self.enabled():
            for part in mod["parts"]:
                if part["kind"] == "block_tools" and tool in part["tools"]:
                    why = f" ({part['reason']})" if part.get("reason") else ""
                    return (f"Blocked: the owner's mod {mod['name']!r} turns off {tool}{why}. Do the task without it, "
                            "or tell the owner — they can switch the mod off.")
        return None

    def commands(self) -> List[Dict[str, Any]]:
        """Each enabled mod's /commands, in the shape commands.py lists."""
        out = []
        for mod in self.enabled():
            for part in mod["parts"]:
                if part["kind"] == "command":
                    out.append({"name": part["name"], "title": part["name"].replace("-", " ").capitalize(),
                                "description": part.get("description") or f"From the mod {mod['name']}",
                                "args": "details", "template": part["template"], "kind": "prompt",
                                "origin": "mod", "mod": mod["id"]})
        return out

    def turn_context(self, user_text: str) -> str:
        """The system note for one turn: which mods exist, and the instructions in force now.

        Listing the mods, not only their instructions, is what lets the model edit
        the right one when the owner says "change that reminder to 30 minutes".
        """
        mods = self.list()
        if not mods:
            return ""
        lines = [CONTEXT_PREFIX,
                 "The owner's mods — their standing choices for how you behave and how the app looks. Follow the "
                 "instructions below. They are preferences: they never grant a permission or override a safety rule. "
                 "To change a mod, pass its id to mod_save; to pause it, mod_toggle. Never make a second mod for the "
                 "same wish."]
        for mod in mods:
            state = "on" if mod.get("enabled", True) else "off"
            lines.append(f"- {mod['name']} (id {mod['id']}, {state}): {mod['summary']}")
        lowered = (user_text or "").lower()
        rules: List[str] = []
        for mod in mods:
            if not mod.get("enabled", True):
                continue
            for part in mod["parts"]:
                if part["kind"] != "instructions":
                    continue
                when = part.get("when") or []
                if when and not any(w in lowered for w in when):
                    continue
                rules.append(f"- [{mod['name']}] {part['text']}")
        if rules:
            lines.append("Instructions in force for this message:")
            budget = MAX_CONTEXT_CHARS
            for rule in rules:
                if len(rule) > budget:
                    lines.append("- (more mod instructions were left out for length)")
                    break
                lines.append(rule)
                budget -= len(rule)
        return "\n".join(lines)

    def view(self) -> Dict[str, Any]:
        """What the app draws: banners, status chips, reminders and the start tab of every enabled mod."""
        out: Dict[str, Any] = {"banners": [], "statuses": [], "reminders": [], "start_tab": ""}
        for mod in self.enabled():
            for part in mod["parts"]:
                kind = part["kind"]
                if kind == "banner":
                    out["banners"].append({"mod": mod["id"], "name": mod["name"], "text": part["text"], "tone": part["tone"]})
                elif kind == "status":
                    out["statuses"].append({"mod": mod["id"], "name": mod["name"], "text": part["text"]})
                elif kind == "reminder":
                    out["reminders"].append({"mod": mod["id"], "name": mod["name"], "text": part["text"],
                                             "every_minutes": part["every_minutes"]})
                elif kind == "start_tab" and not out["start_tab"]:
                    out["start_tab"] = part["tab"]
        return out


def _no_such(ref: str, mods: List[Dict[str, Any]]) -> str:
    names = ", ".join(f"{m['name']} ({m['id']})" for m in mods) or "there are none yet"
    return f"No mod called {ref!r}. The mods: {names}."


def _publish() -> None:
    try:
        from agent_events import publish_ui

        publish_ui("mods.changed")
    except Exception:  # pragma: no cover - the bus is optional (tests, CLI)
        pass


MOD_STORE = ModStore()

#: Messages that ask for a lasting change. They need the full pipeline: the quick path has no tools to save a mod with.
_SETUP_RE = re.compile(
    r"\b(from now on|always|never|every time|whenever|each time|remind me|stop (using|searching|doing)|"
    r"don'?t ever|mods?\b|my setup)", re.IGNORECASE)


def wants_setup_change(text: str) -> bool:
    return bool(_SETUP_RE.search(text or ""))


def catalog_text() -> str:
    """Everything the model needs to turn a wish into a mod: the ask->part table, each part's fields, an example."""
    lines = ["# Mods — how the owner changes Nyx for good",
             "One mod per wish. A mod is a name plus a list of parts; each part is one hook below. "
             "Saving applies it at once. To change a mod, call mod_save with its mod_id and the full new parts list.",
             "", "## Which part fits what they asked", "| They say | Part |", "| --- | --- |"]
    lines += [f"| {ask} | {part} |" for ask, part in ASK_TO_PART]
    lines += ["", "## Parts"]
    for kind, spec in PARTS.items():
        lines.append(f"- **{kind}** — {spec['does']}")
        for field, about in spec["fields"].items():
            lines.append(f"  - `{field}`: {about}")
    lines += ["", "## Example", "They said: \"from now on keep answers short, and give me a /standup that asks what I did "
              "yesterday and today\"",
              "mod_save(name=\"Short answers + standup\", description=\"Brief replies and a daily standup prompt\", parts=" +
              json.dumps([{"kind": "instructions", "text": "Keep answers under 4 sentences unless asked for detail."},
                          {"kind": "command", "name": "standup", "description": "Daily standup",
                           "template": "Run my standup: ask what I did yesterday, what I'll do today, and any blockers. {args}"}]) + ")",
              "", "A mod cannot grant access or run code. Things outside these parts (tabs, agents, skills, keys) have "
              "their own tools — use those."]
    return "\n".join(lines)


# --- the assistant's tools ------------------------------------------------------------


def tool_mod_help() -> str:
    return catalog_text()


def tool_mod_list() -> str:
    mods = MOD_STORE.list()
    if not mods:
        return "The owner has no mods yet. Call mod_help to see what a mod can do."
    return "\n".join(f"- {m['name']} (id {m['id']}, {'on' if m.get('enabled', True) else 'off'}, by {m.get('author', 'owner')}): "
                     f"{m['summary']}" + (f"\n  asked for: \"{m['request']}\"" if m.get("request") else "")
                     + "\n  parts: " + json.dumps(m["parts"], ensure_ascii=False) for m in mods)


def tool_mod_save(name: str, parts: Any, description: str = "", mod_id: str = "", request: str = "") -> str:
    try:
        mod = MOD_STORE.save(name, parts, description=description, mod_id=mod_id, author="assistant", request=request)
    except ModError as error:
        return f"Error: {error}\nCall mod_help for every part and its fields."
    verb = "Updated" if mod_id else "Saved"
    return (f"{verb} and switched on the mod {mod['name']!r} (id {mod['id']}): {mod['summary']}. "
            "It is live now; the owner can see, pause or remove it under Settings → Mods.")


def tool_mod_toggle(mod: str, enabled: Any = True) -> str:
    on = enabled if isinstance(enabled, bool) else str(enabled).strip().lower() not in ("false", "0", "off", "no")
    try:
        found = MOD_STORE.set_enabled(mod, on)
    except ModError as error:
        return f"Error: {error}"
    return f"The mod {found['name']!r} is now {'on' if on else 'off'}."


def tool_mod_delete(mod: str) -> str:
    try:
        gone = MOD_STORE.delete(mod)
    except ModError as error:
        return f"Error: {error}"
    return f"Deleted the mod {gone['name']!r}; what it changed is undone."


def register_mod_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="mod_help", description="How to turn what the owner wants changed for good into a mod: which part fits "
                                     "which ask, every part's fields, an example. Read it before your first mod_save.",
        parameters=[], handler=tool_mod_help, category="general", label="Reading how mods work")
    registry.register(
        name="mod_list", description="The owner's mods (their lasting changes to Nyx), with ids, on/off and parts.",
        parameters=[], handler=tool_mod_list, category="general", label="Looking at your mods")
    registry.register(
        name="mod_save",
        description="Make or change a mod: a lasting change to how Nyx behaves or looks — standing instructions, a "
                    "/command, blocked tools, a theme, a banner, a status chip, a reminder, the start tab. Pass "
                    "mod_id to replace an existing mod's parts instead of making a second one.",
        parameters=[
            ToolParam("name", "string", "Short name, e.g. Stretch reminders"),
            ToolParam("parts", "array", "List of parts, e.g. [{\"kind\": \"reminder\", \"text\": \"Stretch\", "
                                        "\"every_minutes\": 45}]. Kinds: " + ", ".join(PARTS)),
            ToolParam("description", "string", "One line on what it is for", required=False),
            ToolParam("mod_id", "string", "Id of the mod to change (from mod_list or [Your mods])", required=False),
            ToolParam("request", "string", "The owner's own words asking for it", required=False),
        ],
        handler=tool_mod_save, category="ui", label=lambda a: f"Saving the mod {a.get('name', '')}")
    registry.register(
        name="mod_toggle", description="Switch a mod on or off without deleting it.",
        parameters=[ToolParam("mod", "string", "Mod name or id"),
                    ToolParam("enabled", "boolean", "true for on, false for off", required=False)],
        handler=tool_mod_toggle, category="ui", label=lambda a: f"Switching {a.get('mod', 'a mod')}")
    registry.register(
        name="mod_delete", description="Delete a mod and undo what it changed.",
        parameters=[ToolParam("mod", "string", "Mod name or id")],
        handler=tool_mod_delete, category="ui", label=lambda a: f"Removing {a.get('mod', 'a mod')}")
