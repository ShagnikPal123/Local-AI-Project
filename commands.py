"""Slash commands for the composer: the list, the ranking, and "what did you mean" (Request G5).

The owner: "a menu pops up above it so that I can see all commands and as I type
letters it finds the one I mean and if not found it uses a mini AI to predict
which one I could mean or make one on the spot or lead me to the skills create
menu."

Three kinds of command, all data (invariant 2 — nothing here is executed code):

* ``client`` — the chat panel does it itself (new chat, switch model, stop…).
* ``prompt`` — a template: ``/quiz cells`` sends "Make a 5-question practice quiz about cells…".
* ``skill`` — every enabled skill is also a command that asks Nyx to use it.

Owner-made commands (from the menu's "Make /xyz") are prompt templates kept in
``data_path("commands.json")``.
"""

from __future__ import annotations

import difflib
import json
import re
import threading
from typing import Any, Dict, List, Optional

from paths import data_path

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")

BUILTIN_COMMANDS: List[Dict[str, Any]] = [
    {"name": "new", "title": "New chat", "description": "Start one empty chat", "kind": "client", "action": "chat.new"},
    {"name": "duplicate", "title": "Duplicate chat", "description": "An exact copy of this chat", "kind": "client", "action": "chat.duplicate"},
    {"name": "branch", "title": "Branch chat", "description": "A linked copy to take a different direction", "kind": "client", "action": "chat.branch"},
    {"name": "fork", "title": "Fork chat", "description": "A linked chat that starts from a summary", "kind": "client", "action": "chat.fork"},
    {"name": "rename", "title": "Rename chat", "description": "Give this chat your own name", "args": "new name", "kind": "client", "action": "chat.rename"},
    {"name": "model", "title": "Switch model", "description": "Choose who answers from now on", "args": "gemini, nvidia, groq…", "kind": "client", "action": "model.switch"},
    # "/auto" is the Auto team (Update 1, U21); picking the model automatically is /automodel.
    {"name": "automodel", "title": "Auto model", "description": "Let Nyx pick the model for each message", "kind": "client", "action": "model.auto"},
    {"name": "stop", "title": "Stop answering", "description": "Stop the answer being written", "kind": "client", "action": "turn.stop"},
    {"name": "agent", "title": "Agent properties", "description": "Objective, model and tools of an agent", "args": "agent name", "kind": "client", "action": "agent.open"},
    {"name": "tab", "title": "Open a tab", "description": "Jump to Learn, Improve, Agents, Settings…", "args": "tab name", "kind": "client", "action": "tab.open"},
    {"name": "skill", "title": "Create a skill", "description": "Teach Nyx something it should be good at", "args": "what it should be good at", "kind": "client", "action": "skill.create"},
    {"name": "diagram", "title": "Draw a diagram", "description": "Nyx draws it and opens it over the chat — try “how you work”",
     "args": "what to draw", "kind": "client", "action": "diagram.open"},
    # Named after its tool (show_image). Not "/picture" or "/find…": "picture", "photo" and "find" already lead to
    # /image and /search, and people still type them that way.
    {"name": "showimage", "title": "Show a real image", "description": "From the free image libraries with its licence and source, or drawn when nothing fits",
     "args": "what to show", "kind": "client", "action": "diagram.picture"},
    {"name": "help", "title": "All commands", "description": "Show every command", "kind": "client", "action": "help"},
    {"name": "image", "title": "Generate an image", "description": "Draw a picture from a description", "args": "what to draw",
     "template": "Generate an image: {args}"},
    {"name": "search", "title": "Search the web", "description": "Look it up and answer with sources", "args": "what to look up",
     "template": "Search the web and answer with sources: {args}"},
    {"name": "explain", "title": "Explain step by step", "description": "Walk through it one step at a time", "args": "topic or question",
     "template": "Explain step by step, one idea per step, and check my understanding at the end: {args}"},
    {"name": "quiz", "title": "Practice quiz", "description": "Five questions with answers at the end", "args": "topic",
     "template": "Make a 5-question practice quiz about {args}. Mix question types and give the answers with short explanations at the end."},
    {"name": "flashcards", "title": "Flashcards", "description": "Term and definition cards to study", "args": "topic",
     "template": "Make 12 study flashcards (term — definition) about {args}."},
    {"name": "summarize", "title": "Summarize", "description": "Key points, short", "args": "text, link or file",
     "template": "Summarize clearly with the key points first: {args}"},
    {"name": "fresh", "title": "Answer fresh", "description": "Skip remembered answers and think again", "args": "message",
     "template": "[fresh] {args}"},
    {"name": "auto", "title": "Auto — the best team for the job",
     "description": "Nyx picks the skills, agents and connectors that fit (or makes the agent it needs) and runs them",
     "args": "the job", "kind": "auto"},
    {"name": "newagent", "title": "Make an agent", "description": "Add a specialist to the team", "args": "name — what it is for",
     "template": "Create an agent: {args}"},
    {"name": "intent", "title": "Write an intent.md", "description": "Capture the problem, outcome and limits before building",
     "args": "the idea", "template": "Help me write an intent.md for this idea. Ask me the analyst questions first, then write it: {args}"},
    {"name": "compact", "title": "Compact context", "description": "Summarize earlier messages so the chat has room again",
     "args": "what to keep exactly (optional)", "kind": "client", "action": "context.compact"},
    {"name": "improve", "title": "Improve Nyx", "description": "Start a self-improvement run", "args": "what to improve (optional)",
     "template": "improve {args}"},
    {"name": "handoff", "title": "Read the project handoff", "description": "What's being built for Nyx, what's next — and help with it",
     "args": "question (optional)", "template": "Read the project handoff with read_handoff and answer: {args}"},
]

#: Words people type for a command that do not share its letters.
SYNONYMS: Dict[str, List[str]] = {
    "image": ["picture", "draw", "img", "photo", "art", "generate", "paint"],
    "search": ["google", "lookup", "look", "find", "web", "browse"],
    "model": ["switch", "change", "provider", "llm", "use"],
    "duplicate": ["copy", "clone"],
    "branch": ["split", "alternative"],
    "rename": ["title", "name", "call"],
    "quiz": ["test", "exam", "questions", "practice", "study"],
    "flashcards": ["cards", "memorize", "revise", "study"],
    "summarize": ["tldr", "summary", "shorten", "brief"],
    "explain": ["teach", "how", "why", "understand", "steps"],
    "new": ["fresh", "start", "blank", "empty"],
    "stop": ["cancel", "halt", "abort", "quit"],
    "newagent": ["subagent", "agent", "helper", "specialist", "worker"],
    "skill": ["teach", "learn", "capability", "ability"],
    "tab": ["open", "go", "page", "settings"],
    "improve": ["upgrade", "better", "self"],
}

_lock = threading.Lock()


def _store_path():
    return data_path("commands.json")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:32]


def user_commands() -> List[Dict[str, Any]]:
    try:
        raw = json.loads(_store_path().read_text(encoding="utf-8")).get("commands", [])
    except (OSError, ValueError):
        return []
    return [dict(c, kind="prompt", origin="owner") for c in raw if isinstance(c, dict) and NAME_RE.match(str(c.get("name", "")))]


def skill_commands() -> List[Dict[str, Any]]:
    try:
        from skills import SKILL_STORE

        skills = SKILL_STORE.list_skills()
    except Exception:  # pragma: no cover - the skill store is optional here
        return []
    out = []
    taken = {c["name"] for c in BUILTIN_COMMANDS}
    for skill in skills:
        if not skill.get("enabled", True):
            continue
        name = _slug(skill.get("name", ""))
        if not name or name in taken:
            continue
        taken.add(name)
        out.append({"name": name, "title": skill.get("name", name), "description": str(skill.get("description", ""))[:120],
                    "args": "what to use it on", "kind": "skill", "skill_id": skill.get("id", ""),
                    "template": f"Use the “{skill.get('name', name)}” skill for this: {{args}}"})
    return out


def agent_commands() -> List[Dict[str, Any]]:
    """Every agent is a command (owner, 2026-09-16): ``/coder`` opens its box, ``/coder [3]`` three of them.

    Built from the roster each time, so an agent Nyx makes in chat is a command the moment it exists.
    """
    try:
        from agent_dispatch import agent_slug
        from agent_runtime import load_roster

        roster = load_roster()
    except Exception:  # pragma: no cover - the roster is optional here
        return []
    taken = {c["name"] for c in BUILTIN_COMMANDS}
    out = []
    for agent in roster:
        if agent.get("role") == "master":
            continue
        name = agent_slug(agent.get("name", ""))
        if not name or not NAME_RE.match(name):
            continue
        if name in taken:
            name = f"{name}-agent"[:32]
        taken.add(name)
        out.append({"name": name, "title": f"{agent.get('emoji', '')} {agent.get('name', name)}".strip(),
                    "description": str(agent.get("goal", ""))[:120], "args": "[how many] what each should do",
                    "kind": "agent", "agent": agent.get("name", ""), "emoji": agent.get("emoji", ""),
                    "made_by": agent.get("made_by") or ("nyx" if agent.get("created_in_chat") else
                                                        "builtin" if agent.get("origin", "roster") == "roster" else "owner")})
    return out


def all_commands() -> List[Dict[str, Any]]:
    builtin = [dict(c, kind=c.get("kind", "prompt"), origin="builtin") for c in BUILTIN_COMMANDS]
    names = {c["name"] for c in builtin}
    owner = [c for c in user_commands() if c["name"] not in names]
    names |= {c["name"] for c in owner}
    try:
        from mods import MOD_STORE

        modded = [c for c in MOD_STORE.commands() if c["name"] not in names]
    except Exception:  # pragma: no cover - a broken mods file must not empty the menu
        modded = []
    owner += modded
    names |= {c["name"] for c in modded}
    agents =[dict(c, origin="agent") for c in agent_commands() if c["name"] not in names]
    names |= {c["name"] for c in agents}
    skills = [c for c in skill_commands() if c["name"] not in names]
    return builtin + owner + agents + skills


def add_command(name: str, title: str, description: str, template: str) -> Dict[str, Any]:
    """Save an owner command. Raises ValueError with a sentence the menu can show."""
    clean = _slug(name.lstrip("/"))
    if not NAME_RE.match(clean):
        raise ValueError("Command names use letters, numbers and dashes, like /study-plan.")
    if any(c["name"] == clean for c in BUILTIN_COMMANDS):
        raise ValueError(f"/{clean} is already a built-in command.")
    template = (template or "").strip()
    if not template:
        raise ValueError("Say what the command should ask Nyx to do.")
    if "{args}" not in template:
        template = template.rstrip(" :") + ": {args}"
    entry = {"name": clean, "title": (title or clean).strip()[:60], "description": (description or "").strip()[:160],
             "args": "details", "template": template[:2000]}
    with _lock:
        try:
            data = json.loads(_store_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {"commands": []}
        data["commands"] = [c for c in data.get("commands", []) if c.get("name") != clean] + [entry]
        _store_path().parent.mkdir(parents=True, exist_ok=True)
        _store_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return dict(entry, kind="prompt", origin="owner")


def remove_command(name: str) -> bool:
    with _lock:
        try:
            data = json.loads(_store_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        before = len(data.get("commands", []))
        data["commands"] = [c for c in data.get("commands", []) if c.get("name") != name]
        _store_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return len(data["commands"]) < before


def score(query: str, command: Dict[str, Any]) -> float:
    """0..1: how likely ``query`` (what follows the slash) means ``command``."""
    q = query.lower().strip().lstrip("/")
    if not q:
        return 0.5
    name = command["name"]
    words = re.findall(r"[a-z0-9]+", q)
    if name == q:
        return 1.0
    if name.startswith(q):
        return 0.95 - 0.02 * max(0, len(name) - len(q)) / 10
    title = str(command.get("title", "")).lower()
    if title.startswith(q) or any(w.startswith(q) for w in title.split()):
        return 0.85
    if q in name or q in title:
        return 0.75
    best = difflib.SequenceMatcher(None, q, name).ratio()
    synonyms = SYNONYMS.get(name, [])
    if any(w in synonyms or any(s.startswith(w) for s in synonyms if len(w) >= 3) for w in words):
        best = max(best, 0.7)
    haystack = f"{title} {command.get('description', '')}".lower()
    overlap = sum(1 for w in words if len(w) > 2 and w in haystack)
    if overlap:
        best = max(best, min(0.68, 0.4 + 0.14 * overlap))
    return round(best, 3)


def rank(query: str, commands: Optional[List[Dict[str, Any]]] = None, limit: int = 8, floor: float = 0.35) -> List[Dict[str, Any]]:
    pool = commands if commands is not None else all_commands()
    scored = sorted(((score(query, c), c) for c in pool), key=lambda pair: -pair[0])
    return [dict(c, score=s) for s, c in scored if s >= floor][:limit]


def _ask_model(text: str, commands: List[Dict[str, Any]], budget_seconds: float) -> Optional[Dict[str, Any]]:
    """A small, fast model call: pick a command, or propose a new one. None on timeout or failure."""
    # Names and titles only: a short prompt keeps the small model fast.
    catalog = ", ".join(f"/{c['name']} ({c.get('title', '')})" for c in commands[:80])
    prompt = (
        "The user typed a slash command that does not exist in Nyx Ichos. Decide what they meant.\n"
        f"They typed: {text!r}\nCommands: {catalog}\n"
        'Reply with JSON only: {"match": "<existing command name or null>", "confidence": 0-1, '
        '"new": null or {"name": "short-dashed-name", "title": "Title", "description": "one line", '
        '"template": "what to ask Nyx, with {args} where the user\'s words go"}}. '
        "Prefer an existing command when it plausibly fits; propose a new one only when none does."
    )

    from mini_model import quick_text
    from tools import _loads_lenient

    reply = quick_text(prompt, budget_seconds=budget_seconds) or ""
    if "{" not in reply:
        return None
    data = _loads_lenient(reply[reply.find("{"): reply.rfind("}") + 1])
    return data if isinstance(data, dict) else None


def guess(text: str, use_model: bool = True, budget_seconds: float = 4.0) -> Dict[str, Any]:
    """What an unknown ``/something`` probably meant — and a command to make if nothing fits."""
    query = (text or "").strip().lstrip("/")
    head = query.split(" ", 1)[0]
    commands = all_commands()
    matches = rank(head, commands, limit=5, floor=0.5) or rank(query, commands, limit=5, floor=0.5)
    result: Dict[str, Any] = {"query": query, "matches": matches, "suggestion": None, "source": "fuzzy"}
    if matches and matches[0]["score"] >= 0.75:
        return result
    if use_model and query:
        answer = _ask_model(query, commands, budget_seconds)
        if answer:
            result["source"] = "model"
            picked = str(answer.get("match") or "").lstrip("/")
            found = next((c for c in commands if c["name"] == picked), None)
            if found and not any(m["name"] == picked for m in matches):
                result["matches"] = [dict(found, score=float(answer.get("confidence") or 0.6))] + matches[:4]
            new = answer.get("new")
            if isinstance(new, dict) and new.get("template"):
                result["suggestion"] = {
                    "name": _slug(str(new.get("name") or head)) or _slug(head) or "my-command",
                    "title": str(new.get("title") or head)[:60],
                    "description": str(new.get("description") or "")[:160],
                    "template": str(new.get("template"))[:2000],
                }
    if result["suggestion"] is None and head and not any(c["name"] == _slug(head) for c in commands):
        result["suggestion"] = {"name": _slug(head), "title": head.replace("-", " ").title()[:60],
                                "description": f"Made from “/{query}”", "template": f"{query.replace('-', ' ')}: {{args}}"}
        if result["source"] == "fuzzy":
            result["source"] = "offline"
    return result



# --- several commands anywhere in a message (Request H13) --------------------------------------
#
# "When I do the / command allow me to do multiple and I can add it anywhere in the text. So in the
# middle or even at the end. The AI reads the skills first."

#: A command token: "/name" at the start or after whitespace, not part of a path or URL.
_INLINE_RE = re.compile(r"(?:(?<=\s)|^)/([a-z0-9][a-z0-9-]{0,31})(?=$|[\s.,;:!?)])", re.IGNORECASE)
PREFIX = "[Commands the user wrote]"


def find_inline(text: str, commands: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Every known /command in the text, in order, once each. Unknown ones (and paths) are ignored."""
    known = {c["name"]: c for c in (commands if commands is not None else all_commands())}
    found: List[Dict[str, Any]] = []
    seen = set()
    for match in _INLINE_RE.finditer(text or ""):
        name = match.group(1).lower()
        if name in known and name not in seen:
            seen.add(name)
            found.append({**known[name], "position": match.start()})
    return found


def brief_for(text: str, commands: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """What the model must read before anything else: each skill in full, and what each prompt command means.

    Client commands (/new, /model…) are actions the chat panel takes; written mid-message they are
    named so the model does not treat them as words, and nothing is run.
    """
    found = find_inline(text, commands)
    if not found:
        return {"found": [], "skills": [], "context": ""}
    try:
        from skills import SKILL_STORE
    except Exception:  # pragma: no cover
        SKILL_STORE = None  # type: ignore[assignment]
    lines = [PREFIX, "The user put these / commands in their message. Read them before anything else and apply "
             "every one of them to the parts of the message they belong to:"]
    skills: List[Dict[str, Any]] = []
    agent_found = [c for c in found if c.get("kind") == "agent"]
    if agent_found:
        try:
            import agent_dispatch

            names = {c["name"]: c["agent"] for c in agent_found}
            parsed = agent_dispatch.parse_invocations(text, names)
            for inv in parsed["invocations"]:
                copies = f"{inv['count']} copies of " if inv["count"] > 1 else ""
                lines.append(f"\n/{inv['slug']}" + (f" [{inv['count']}]" if inv["count"] > 1 else "")
                             + f" — the user wants {copies}the {inv['agent']} agent on: {inv['task'][:600]}")
            lines.append("\nCall dispatch_agents for these (agent + count, and tasks = one distinct part of the work per "
                         "copy when there are several; agents=[...] for a mix), then combine their reports in your answer.")
        except Exception:  # pragma: no cover
            pass
    for command in found:
        name = command["name"]
        if command.get("kind") == "agent":
            continue
        if command.get("kind") == "skill" and SKILL_STORE is not None:
            skill = SKILL_STORE.get(command.get("skill_id", ""))
            if skill is not None:
                lines.append(f"\n/{name} — skill “{skill.name}”. Follow these instructions:\n{skill.instructions}")
                skills.append({"id": skill.skill_id, "name": skill.name, "source": skill.source, "why": f"/{name}"})
                continue
        if command.get("kind") == "client":
            lines.append(f"\n/{name} — {command.get('title', name)}: an app action, not part of the request. Ignore the word.")
            continue
        if command.get("kind") == "auto":
            # The picks and how to run them arrive as their own "[Auto team]" brief (auto_team.py).
            lines.append(f"\n/{name} — Auto: run the team described under [Auto team] for the rest of the message.")
            continue
        template = str(command.get("template") or "")
        meaning = template.replace("{args}", "the part of the message it applies to").strip()
        lines.append(f"\n/{name} — {command.get('title', name)}: {meaning}")
    return {"found": [c["name"] for c in found], "skills": skills, "context": "\n".join(lines)}
