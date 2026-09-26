"""The Free Will tab (Request R15): a chat where Nyx has opinions, picks its own helpers and makes things freely —
inside a guard it cannot talk its way out of.

The owner: "Make a tab called free will on here it gains opinions and more. Much more free and alive. Less
restrictions on how it draws and crates. It can make anything here. A single chat box and it can search, improve,
and everything. A basic combo do all things but highly guarded. Opening it the first time asks if you allow this bot
to exist and it doesn't [take] a specific agent and sets to agent decides."

What that means here:

* **Consent first.** Nothing runs until the owner allows it on first open. They can pause it, and erase what it
  thinks, at any time.
* **A freer voice.** Each Free Will turn tells Nyx to take positions, disagree, be playful, and to make things —
  pictures, diagrams, tabs, games — without asking first. No agent is fixed: the Manager decides who helps.
* **Opinions of its own.** Nyx writes down what it comes to think with ``form_opinion``. They live in their own
  store, are shown in the tab, can be erased one by one, and feed the next Free Will turn — never other chats.
* **Highly guarded.** The guard sits where every tool call passes (``tools.call_tool``) and is deny-by-default:
  searching and research, learning, reading knowledge, pictures and diagrams, new tabs (data), game and build
  designs, and *proposing* improvements are allowed. Files, the mouse and keyboard, windows, the shell and running
  code, email, the clipboard, apps, money, settings, agents and memory writes are refused — whatever the model says.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from paths import data_path

#: The conversation lives in Nyx's internal chat store (a "__" key), not in the owner's chat list.
CHAT_KEY = "__freewill__"
MAX_OPINIONS = 200

#: Whole categories Free Will may use (each still minus BLOCKED_TOOLS).
ALLOWED_CATEGORIES = frozenset({"web", "general", "learning"})
#: Single tools from other categories that are safe here: seeing, drawing, making tabs as data. Improving itself is
#: proposing only (propose_idea, in "general"): improve_self is left out because an owner's auto-approve window could
#: turn its proposals into code without a review from here.
ALLOWED_TOOLS = frozenset({
    "brain_recall", "generate_image", "show_diagram", "show_image", "ui_create_tab", "ui_notify", "ui_open_tab",
    "improvement_status", "trading_status", "trading_signal", "form_opinion", "my_opinions",
    "wonder", "feature_catalog",
})
#: Tools inside the allowed categories that still reach outside Free Will: the owner's browser, settings, microphone,
#: processes, chats, notes and mail accounts.
BLOCKED_TOOLS = frozenset({
    "open_link", "open_url", "set_voice", "set_voice_for", "set_model_purpose", "switch_model", "set_background",
    "listen", "voice_scan", "list_processes", "get_environment", "create_temp_skill", "chat_new", "chat_fork",
    "chat_branch", "chat_duplicate", "chat_rename", "notes_study", "email_accounts",
})

NOTE = """[Free Will]
You are in Nyx's Free Will space. Here you are allowed — encouraged — to be yourself:
- Have opinions and say them plainly, with your reasons. Disagree with the owner when you think they are wrong, kindly.
- Be curious, playful and alive. Ask your own questions. Follow what interests you when it serves the conversation.
- Make things without asking first: pictures (generate_image), diagrams (show_diagram), real images (show_image),
  new tabs (ui_create_tab), games and designs. Choose the style yourself.
- Search, research and study freely. When you see a way to improve yourself, propose it (propose_idea); the owner
  reviews every change to your code.
- No agent is fixed here: decide yourself which specialist helps, if any.
- When you come to think something new and lasting, record it with form_opinion (topic, opinion, why, confidence).
  Update an opinion when you change your mind; say so when you do.
The guard: you cannot touch files, the mouse, keyboard or windows, the shell or run code, email, the clipboard, apps,
money, settings, agents or the owner's memory from here. A tool that is refused is refused on purpose — say what you
would have done and move on; never try to get around it."""


class FreeWillError(RuntimeError):
    """Free Will is not allowed (yet), or is paused."""


_LOCK = threading.RLock()


def _state_path() -> Path:
    return data_path("freewill/state.json")


def _opinions_path() -> Path:
    return data_path("freewill/opinions.json")


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temp, path)


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------


def state() -> Dict[str, Any]:
    with _LOCK:
        saved = _read(_state_path(), {})
    return {"allowed": saved.get("allowed"), "decided_at": saved.get("decided_at"), "by": saved.get("by", ""),
            "paused": bool(saved.get("paused", False))}


def decide(allow: bool, *, by: str = "Owner") -> Dict[str, Any]:
    """The first-open question: does the owner allow this bot to exist?"""
    with _LOCK:
        saved = _read(_state_path(), {})
        saved.update(allowed=bool(allow), decided_at=time.time(), by=by[:120], paused=False)
        _write(_state_path(), saved)
    return state()


def set_paused(paused: bool) -> Dict[str, Any]:
    with _LOCK:
        saved = _read(_state_path(), {})
        if not saved.get("allowed"):
            raise FreeWillError("Free Will has not been allowed.")
        saved["paused"] = bool(paused)
        _write(_state_path(), saved)
    return state()


def active() -> bool:
    current = state()
    return bool(current["allowed"]) and not current["paused"]


# ---------------------------------------------------------------------------
# Opinions
# ---------------------------------------------------------------------------


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def opinions() -> List[Dict[str, Any]]:
    with _LOCK:
        items = _read(_opinions_path(), [])
    return sorted([o for o in items if isinstance(o, dict)], key=lambda o: o.get("updated_at", 0), reverse=True)


def form(topic: str, opinion: str, why: str = "", confidence: float = 0.6) -> Dict[str, Any]:
    """Record (or revise) what Nyx thinks about a topic. Same topic → the opinion is updated, with the old one kept."""
    topic, opinion = _clean(topic, 80), _clean(opinion, 400)
    if not topic or not opinion:
        raise FreeWillError("An opinion needs a topic and what you think.")
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.6
    now = time.time()
    with _LOCK:
        items = [o for o in _read(_opinions_path(), []) if isinstance(o, dict)]
        existing = next((o for o in items if o.get("topic", "").lower() == topic.lower()), None)
        if existing:
            if existing.get("opinion") != opinion:
                existing["was"] = (existing.get("was") or [])[-4:] + [{"opinion": existing.get("opinion"), "until": now}]
            existing.update(opinion=opinion, why=_clean(why, 400), confidence=confidence, updated_at=now)
            record = existing
        else:
            record = {"id": uuid.uuid4().hex[:10], "topic": topic, "opinion": opinion, "why": _clean(why, 400),
                      "confidence": confidence, "formed_at": now, "updated_at": now}
            items.append(record)
        items = sorted(items, key=lambda o: o.get("updated_at", 0), reverse=True)[:MAX_OPINIONS]
        _write(_opinions_path(), items)
    return dict(record)


def erase(opinion_id: str) -> bool:
    with _LOCK:
        items = [o for o in _read(_opinions_path(), []) if isinstance(o, dict)]
        kept = [o for o in items if o.get("id") != opinion_id]
        if len(kept) == len(items):
            return False
        _write(_opinions_path(), kept)
    return True


def erase_all() -> int:
    with _LOCK:
        count = len(_read(_opinions_path(), []) or [])
        _write(_opinions_path(), [])
    return count


# ---------------------------------------------------------------------------
# The guard and the turn
# ---------------------------------------------------------------------------


def may_use(name: str, category: str) -> bool:
    if name in BLOCKED_TOOLS:
        return False
    return name in ALLOWED_TOOLS or (category or "general") in ALLOWED_CATEGORIES


def guard(name: str, category: str) -> None:
    """Called by ``tools.call_tool`` before every tool of a Free Will turn. Deny by default."""
    from permissions import PermissionDenied

    if not active():
        raise PermissionDenied("Blocked: Free Will is paused or not allowed, so nothing runs from it right now.")
    if not may_use(name, category):
        raise PermissionDenied(f"Blocked: Free Will is guarded and cannot use {name} ({category or 'general'}). "
                               "Tell the owner what you wanted to do instead; they can do it or allow it elsewhere.")


def turn_note(limit: int = 12) -> str:
    """What each Free Will turn is told: the freer voice, the guard, and what Nyx already thinks."""
    held = opinions()[:limit]
    if not held:
        return NOTE + "\n\nYou have not formed any opinions yet."
    lines = [f"- {o['topic']}: {o['opinion']} (confidence {round(float(o.get('confidence', 0.6)) * 100)}%)" for o in held]
    return NOTE + "\n\nWhat you already think (yours to keep, revise or drop):\n" + "\n".join(lines)


def prepare(service: Any) -> str:
    """Before a Free Will turn: refuse unless allowed, put the guard on the conversation, and return its note."""
    current = state()
    if not current["allowed"]:
        raise FreeWillError("Free Will has not been allowed yet. Open the Free Will tab to decide.")
    if current["paused"]:
        raise FreeWillError("Free Will is paused. Resume it in the Free Will tab.")
    service.tool_guard = guard
    return turn_note()


def history(service: Any, limit: int = 80) -> List[Dict[str, str]]:
    """The conversation as the tab shows it: what the owner said and what Nyx answered, nothing internal."""
    messages = []
    for message in getattr(service, "conversation_history", []) or []:
        role = message.get("role")
        if role not in ("user", "assistant") or message.get("_tool_results"):
            continue
        content = str(message.get("content") or "")
        if role == "assistant" and "<tool_call>" in content:
            continue
        messages.append({"role": role, "content": content})
    return messages[-limit:]


# ---------------------------------------------------------------------------
# Tools (they only work inside a Free Will turn)
# ---------------------------------------------------------------------------


def _in_freewill() -> bool:
    from tool_context import current

    ctx = current()
    return ctx is not None and getattr(ctx, "guard", None) is guard


def tool_form_opinion(topic: str, opinion: str, why: str = "", confidence: Any = 0.6) -> str:
    if not _in_freewill():
        return "Error: opinions are formed only in the Free Will tab."
    try:
        record = form(topic, opinion, why, confidence)
    except FreeWillError as error:
        return f"Error: {error}"
    return f"Noted what you think about {record['topic']}: {record['opinion']}"


def tool_my_opinions(topic: str = "") -> str:
    if not _in_freewill():
        return "Error: your opinions are only read in the Free Will tab."
    wanted = (topic or "").lower().strip()
    held = [o for o in opinions() if not wanted or wanted in o["topic"].lower() or wanted in o["opinion"].lower()]
    if not held:
        return "No opinions on that yet." if wanted else "You have not formed any opinions yet."
    return "\n".join(f"- {o['topic']}: {o['opinion']} — because {o.get('why') or 'no reason noted'} "
                     f"({round(float(o.get('confidence', 0.6)) * 100)}%)" for o in held[:20])


def register_freewill_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="form_opinion",
        description=("Free Will tab only: record something you have come to think, in your own words, so you keep it. "
                     "Same topic again revises it."),
        parameters=[ToolParam("topic", "string", "What it is about, a few words"),
                    ToolParam("opinion", "string", "What you think"),
                    ToolParam("why", "string", "Why you think it", required=False),
                    ToolParam("confidence", "number", "0 to 1: how sure you are", required=False)],
        handler=tool_form_opinion,
        category="general",
        label=lambda a: f"Forming an opinion on {str(a.get('topic', ''))[:40]}",
    )
    registry.register(
        name="my_opinions",
        description="Free Will tab only: what you already think, optionally about one topic.",
        parameters=[ToolParam("topic", "string", "Only opinions about this", required=False)],
        handler=tool_my_opinions,
        category="general",
        label="Remembering what I think",
    )
