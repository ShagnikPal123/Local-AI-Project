"""Commander: one chat hands work to threads ("divisions") and keeps track of every one of them.

The owner (Fixer Upper, 2026-10-13): "the main chat we type in is the delegator and sends to the different threads",
"on the right we can see the divisions", and for the Commander: "in a single chat I can send a prompt and it auto sends
to the chats that can do it ... while this chat stays clean ... It handles how much token and context use they have
while if one is started fresh it gives a quick summary of its use and sends what it needs to do." He pointed at
Claude's Projects for the look (images p16 and p27), so the shape copies it:

* A **delegator** is a chat whose job is handing work out: a project's main chat (``delegator_for_project``), or any
  chat switched to Commander. Each turn there gets the Commander brief (through ``command_zone.brief_for_chat``, the
  hook the turn runner already calls), so it starts and steers threads instead of doing the work itself.
* A **thread** is an ordinary chat in the chat list, plus a record here: whose thread it is, which project, its sector
  ("Updates", "Fixes", "Questions", "Research"), the kind of model, real model and effort it was given and why.
* **Status is read live, never guessed from a timer**: a turn running in the thread's chat is *Working*; an approval
  waiting, an unanswered question card or a "Waiting on you:" line is *Needs you*; otherwise *Idle* until it is
  *Resolved*. The same reading works for any chat (``attention``), so every chat can show when it needs the owner.
* **Context care**: before a thread gets more work its use is measured (``context_budget.measure``). Past
  ``REFRESH_AT`` of what its model reads at once, a fresh thread starts with a short summary of the old one plus the new
  work, and the old one is resolved with a link forward.

Everything here is data plus calls into the existing turn pipeline; nothing runs generated code (invariant 2).
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

from paths import atomic_replace, data_path

#: The Command Zone's prefix, so the turn runner drops the last turn's brief before adding this turn's.
BRIEF_PREFIX = "[Command Zone]"
#: A thread past this share of what its model reads at once gets a fresh start before more work.
REFRESH_AT = 0.7
#: Statuses in the order the panel shows them. Short names, as the owner asked (1–2 words, not "Waiting on you").
STATUS_LABELS = {"needs_you": "Needs you", "working": "Working", "idle": "Idle", "resolved": "Resolved"}
#: How hard a thread's turn works until the lineup's effort reaches the turn itself: from High up it gets Co-work's
#: room (more tool steps, a checklist) instead of Normal's quick path (chat_modes).
EFFORT_MODE = {"low": "normal", "mid": "normal", "normal": "normal", "high": "cowork", "higher": "cowork",
               "super": "cowork", "aleph": "cowork"}

DONE_RE = re.compile(r"^\s*(?:\*\*)?done:(?:\*\*)?\s*(.+)$", re.IGNORECASE | re.MULTILINE)
WAITING_RE = re.compile(r"^\s*(?:\*\*)?waiting on you:(?:\*\*)?\s*(.+)$", re.IGNORECASE | re.MULTILINE)

_LOCK = threading.RLock()


class CommanderError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def _path():
    return data_path("commander.json")


def _blank() -> Dict[str, Any]:
    return {"delegators": {}, "threads": {}, "asks": {},
            "settings": {"divisions_in_chat": False, "auto_pick": True}}


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("threads"), dict):
            blank = _blank()
            for key, value in blank.items():
                data.setdefault(key, value)
            data["settings"] = {**blank["settings"], **(data.get("settings") or {})}
            return data
    except (OSError, ValueError):
        pass
    return _blank()


def _save(state: Dict[str, Any]) -> None:
    target = _path()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    atomic_replace(tmp, target)


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _publish() -> None:
    try:
        from agent_events import publish_ui

        publish_ui("commander.changed")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# The rest of the app, reached through small seams so tests can stand in for them
# ---------------------------------------------------------------------------

def _store() -> Any:
    import server

    return server._shared_chat_store()


def _run(chat_id: str, text: str, provider: str, mode: str, role: str) -> str:
    """Start one turn in a thread's chat and return its id. The turn runs on its own worker, like any chat turn."""
    from routes_live import StreamRequest, start_turn

    turn_id, _chat = start_turn(StreamRequest(message=text, chat_id=chat_id, provider=provider or None, mode=mode),
                                SimpleNamespace(role=role or "local"))
    return turn_id


def _running(chat_id: str) -> Any:
    try:
        from turn_registry import TURNS

        return TURNS.running_for_chat(chat_id)
    except Exception:
        return None


def _decide(approval_id: str, approve: bool) -> bool:
    from permissions import resolve_approval

    return bool(resolve_approval(approval_id, approve))


def _approvals() -> List[Dict[str, Any]]:
    try:
        from permissions import pending_approvals

        return pending_approvals()
    except Exception:
        return []


def _measure(messages: List[Dict[str, Any]], provider: str, model: str) -> Dict[str, Any]:
    """Tokens used against what the thread's model reads at once (the whole chat window when that is unknown)."""
    try:
        import context_budget

        found = context_budget.measure(messages, provider, model)
        limit = int(found.get("model_window") or found.get("window") or 0)
        used = int(found.get("used") or 0)
    except Exception:
        used = sum(len(str(m.get("content", ""))) for m in messages) // 4
        limit = 0
    return {"used": used, "window": limit, "share": round(used / limit, 3) if limit else 0.0}


def _summary_of(messages: List[Dict[str, Any]]) -> str:
    """What a full thread did, for the fresh one. No model call: what was asked, and the first line of each answer."""
    try:
        import context_budget

        return context_budget.offline_summary("", [m for m in messages if m.get("role") in ("user", "assistant")])
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Reading a chat: does it need the owner, is it working, what is its latest line
# ---------------------------------------------------------------------------

def _last(messages: List[Dict[str, Any]], role: str) -> Optional[Dict[str, Any]]:
    return next((m for m in reversed(messages) if m.get("role") == role), None)


def read_chat(chat_id: str, messages: Optional[List[Dict[str, Any]]] = None,
              approvals: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The live state of one chat: ``status`` (needs_you / working / idle), the reason, and a one-line status."""
    if messages is None:
        messages = _store().messages(chat_id)
    talk = [m for m in messages if m.get("role") in ("user", "assistant")]
    record = _running(chat_id)
    if record is not None:
        turn_id = getattr(record, "turn_id", "")
        waiting = [a for a in (approvals if approvals is not None else _approvals()) if a.get("turn_id") == turn_id]
        if waiting:
            return {"status": "needs_you", "kind": "approval", "line": _clean(waiting[0].get("summary"), 160),
                    "turn_id": turn_id, "approval_id": waiting[0].get("id", "")}
        return {"status": "working", "kind": "", "line": _clean(getattr(record, "status", "") or "Working", 160),
                "turn_id": turn_id}
    last = talk[-1] if talk else None
    if last is None:
        return {"status": "idle", "kind": "", "line": "No messages yet"}
    if last.get("role") == "assistant":
        text = str(last.get("content") or "")
        try:
            from question_cards import find_all

            cards = find_all(text)
        except Exception:
            cards = []
        if cards:
            return {"status": "needs_you", "kind": "question", "line": _clean(cards[0]["question"], 160)}
        waiting = WAITING_RE.findall(text)
        if waiting:
            return {"status": "needs_you", "kind": "blocked", "line": _clean(waiting[-1], 160)}
        done = DONE_RE.findall(text)
        line = done[-1] if done else next((ln for ln in text.splitlines() if ln.strip() and not ln.startswith("```")), "")
        return {"status": "idle", "kind": "finished", "line": _clean(re.sub(r"[*_#`>]+", "", line), 160)}
    return {"status": "idle", "kind": "", "line": _clean(f"You: {last.get('content', '')}", 160)}


def attention() -> List[Dict[str, Any]]:
    """Every chat that needs the owner or is working, so any chat (normal, project, code) can show it next to its name."""
    store = _store()
    approvals = _approvals()
    with _LOCK:
        by_chat = {t["chat_id"]: t for t in _load()["threads"].values()}
    out = []
    for chat in store.summaries():
        state = read_chat(chat["id"], store.messages(chat["id"]), approvals)
        if state["status"] == "idle":
            continue
        thread = by_chat.get(chat["id"])
        out.append({"chat_id": chat["id"], "title": chat.get("title", ""), **state,
                    "label": STATUS_LABELS[state["status"]], "thread_id": thread["id"] if thread else ""})
    out.sort(key=lambda row: (row["status"] != "needs_you", row["title"].lower()))
    return out


# ---------------------------------------------------------------------------
# Delegators
# ---------------------------------------------------------------------------

def is_delegator(chat_id: str) -> bool:
    if not chat_id:
        return False
    with _LOCK:
        return chat_id in _load()["delegators"]


def make_delegator(chat_id: str, project_id: str = "") -> Dict[str, Any]:
    """Switch a chat to Commander: from its next message it hands work to threads."""
    if not chat_id:
        raise CommanderError("Which chat?")
    with _LOCK:
        state = _load()
        if any(t["chat_id"] == chat_id for t in state["threads"].values()):
            raise CommanderError("A thread cannot be a Commander itself. Use the main chat.")
        row = state["delegators"].setdefault(chat_id, {"project_id": "", "created": time.time()})
        if project_id:
            row["project_id"] = project_id
        _save(state)
    _publish()
    return {"chat_id": chat_id, **row}


def drop_delegator(chat_id: str) -> bool:
    """Back to a normal chat. Its threads stay where they are, and come back if Commander is switched on again."""
    with _LOCK:
        state = _load()
        if chat_id not in state["delegators"]:
            return False
        del state["delegators"][chat_id]
        _save(state)
    _publish()
    return True


def delegator_for_project(project_id: str, project_name: str = "") -> str:
    """A project's main chat, made the first time it is needed and again if it was deleted."""
    store = _store()
    with _LOCK:
        state = _load()
        for chat_id, row in state["delegators"].items():
            if row.get("project_id") == project_id and row.get("main") and store.exists(chat_id):
                return chat_id
    title = f"{project_name or 'Project'} · Commander"
    try:
        chat_id = store.create(title, activate=False)
    except RuntimeError as error:
        raise CommanderError(f"{error} The project needs a main chat of its own.") from error
    with _LOCK:
        state = _load()
        state["delegators"][chat_id] = {"project_id": project_id, "created": time.time(), "main": True}
        _save(state)
    _publish()
    return chat_id


def move_to_project(chat_id: str, project_id: str) -> Dict[str, Any]:
    """A Commander chat and all its threads join a project (the owner's "move into projects")."""
    with _LOCK:
        state = _load()
        row = state["delegators"].get(chat_id)
        if row is None:
            raise CommanderError("That chat is not a Commander.")
        row["project_id"] = project_id
        for thread in state["threads"].values():
            if thread["delegator"] == chat_id:
                thread["project_id"] = project_id
        _save(state)
    _publish()
    return {"chat_id": chat_id, **row}


def settings() -> Dict[str, Any]:
    with _LOCK:
        return dict(_load()["settings"])


def save_settings(**changes: Any) -> Dict[str, Any]:
    with _LOCK:
        state = _load()
        for key in ("divisions_in_chat", "auto_pick"):
            if key in changes and changes[key] is not None:
                state["settings"][key] = bool(changes[key])
        _save(state)
        return dict(state["settings"])


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------

THREAD_TAIL = (
    "[Thread brief] You are the thread “{title}”{where}, handed this work by the Commander chat. You do not see that "
    "chat, so everything you need is above.{note} Do the work fully with your tools, and do not stop to check in unless "
    "you are truly blocked.\n"
    "End your answer with one line that starts “Done:” and says the result in a sentence. If something only the owner "
    "can decide or do is in the way, end instead with one line that starts “Waiting on you:” saying exactly what you "
    "need, or ask it as a question card."
)


def _where(project_id: str) -> str:
    if not project_id:
        return ""
    try:
        import projects

        project = projects.get(project_id)
        return f" in the project “{project['name']}”" if project else ""
    except Exception:
        return ""


def _note(project_id: str) -> str:
    if not project_id:
        return ""
    try:
        import projects

        note = projects.project_note(project_id)
        return f" {note}" if note else ""
    except Exception:
        return ""


def _brief_message(thread: Dict[str, Any], task: str) -> str:
    tail = THREAD_TAIL.format(title=thread["title"], where=_where(thread["project_id"]), note=_note(thread["project_id"]))
    return f"{task.strip()}\n\n{tail}"


def _find(state: Dict[str, Any], ref: str, delegator: str = "") -> Optional[Dict[str, Any]]:
    """A thread by id, chat id or title (the delegator's model names threads by title)."""
    ref = (ref or "").strip()
    threads = [t for t in state["threads"].values() if not delegator or t["delegator"] == delegator]
    exact = next((t for t in threads if ref in (t["id"], t["chat_id"])), None)
    if exact:
        return exact
    lowered = ref.lower()
    live = [t for t in threads if not t.get("resolved")] or threads
    return (next((t for t in live if t["title"].lower() == lowered), None)
            or next((t for t in live if lowered and lowered in t["title"].lower()), None))


def start_thread(delegator: str, title: str, task: str, *, tier: str = "", effort: str = "", provider: str = "",
                 model: str = "", sector: str = "", role: str = "local", refreshed_from: str = "",
                 opening: str = "") -> Dict[str, Any]:
    """Make a thread's chat, pick its model and effort (unless given), brief it, and start it working."""
    import commander_pick

    title, task = _clean(title, 80), str(task or "").strip()[:8000]
    if not title or not task:
        raise CommanderError("A thread needs a short title and the task.")
    with _LOCK:
        row = _load()["delegators"].get(delegator)
    if row is None:
        raise CommanderError("Only a Commander chat hands out threads.")
    chosen = commander_pick.pick(f"{title}. {task}", with_model=not provider)
    tier = tier if tier in commander_pick.TIERS else chosen["tier"]
    effort = effort if effort in commander_pick.EFFORTS else chosen["effort"]
    sector = sector if sector in commander_pick.SECTORS else chosen["sector"]
    if provider:
        chosen.update(provider=provider, model=model, model_label=f"{provider}{' · ' + model if model else ''}",
                      why="the Commander chose it for this task")
    try:
        chat_id = _store().create(title, activate=False)
    except RuntimeError as error:
        raise CommanderError(f"{error} Resolve or delete an old thread to make room.") from error
    now = time.time()
    thread = {
        "id": f"th-{uuid.uuid4().hex[:8]}", "chat_id": chat_id, "delegator": delegator,
        "project_id": row.get("project_id", ""), "title": title, "task": task[:2000], "sector": sector,
        "tier": tier, "effort": effort, "provider": chosen["provider"], "model": chosen["model"],
        "model_label": chosen.get("model_label") or "", "why": chosen["why"], "source": chosen.get("source", "rules"),
        "pinned": False, "resolved": False, "created": now, "updated": now, "refreshed_from": refreshed_from,
        "refreshed_to": "", "turns": [],
    }
    with _LOCK:
        state = _load()
        state["threads"][thread["id"]] = thread
        _save(state)
    commander_pick.PICKER.learn(f"{title}. {task}", tier, effort, sector, title=title)
    message = opening or _brief_message(thread, task)
    turn_id = _run(chat_id, message, thread["provider"], EFFORT_MODE.get(effort, "normal"), role)
    _remember_turn(thread["id"], turn_id)
    _publish()
    return view(thread)


def _remember_turn(thread_id: str, turn_id: str) -> None:
    with _LOCK:
        state = _load()
        thread = state["threads"].get(thread_id)
        if thread is not None and turn_id:
            thread["turns"] = (thread.get("turns", []) + [turn_id])[-10:]
            thread["updated"] = time.time()
            _save(state)


def message_thread(ref: str, text: str, *, delegator: str = "", role: str = "local") -> Dict[str, Any]:
    """Send a thread more work. A thread that is too full is refreshed first: the new one gets a summary and the work."""
    text = str(text or "").strip()[:8000]
    if not text:
        raise CommanderError("What should the thread do?")
    with _LOCK:
        state = _load()
        thread = _find(state, ref, delegator)
        if thread is None:
            raise CommanderError(f"No thread called {ref!r}. list_threads shows them.")
        thread = dict(thread)
    if _running(thread["chat_id"]) is not None:
        raise CommanderError(f"“{thread['title']}” is still working. Wait for it, or start another thread.")
    messages = _store().messages(thread["chat_id"])
    use = _measure(messages, thread["provider"], thread["model"])
    if use["share"] >= REFRESH_AT:
        return refresh_thread(thread["id"], text, role=role, messages=messages, use=use)
    with _LOCK:
        state = _load()
        state["threads"][thread["id"]]["resolved"] = False
        _save(state)
    turn_id = _run(thread["chat_id"], text, thread["provider"], EFFORT_MODE.get(thread["effort"], "normal"), role)
    _remember_turn(thread["id"], turn_id)
    _publish()
    return view(get(thread["id"]) or thread)


def refresh_thread(thread_id: str, task: str, *, role: str = "local", messages: Optional[List[Dict[str, Any]]] = None,
                   use: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Start a fresh thread from a full one: a short summary of what it did, then the new work."""
    old = get(thread_id)
    if old is None:
        raise CommanderError("No such thread.")
    if messages is None:
        messages = _store().messages(old["chat_id"])
    use = use or _measure(messages, old["provider"], old["model"])
    summary = _summary_of(messages) or "(nothing worth carrying over)"
    fresh_title = re.sub(r"\s*\(fresh\)$", "", old["title"]) + " (fresh)"
    pct = round(use["share"] * 100)
    opening = (f"[Fresh start] This continues the thread “{old['title']}”, which was {pct}% full of what its model "
               f"reads at once. What happened there:\n{summary}\n\nNow: {task.strip()}\n\n"
               + THREAD_TAIL.format(title=fresh_title, where=_where(old["project_id"]), note=_note(old["project_id"])))
    new = start_thread(old["delegator"], fresh_title, task, tier=old["tier"], effort=old["effort"],
                       provider=old["provider"], model=old["model"], sector=old["sector"], role=role,
                       refreshed_from=old["id"], opening=opening)
    with _LOCK:
        state = _load()
        if old["id"] in state["threads"]:
            state["threads"][old["id"]].update(resolved=True, refreshed_to=new["id"], updated=time.time())
        _save(state)
    _publish()
    return new


def get(thread_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        thread = _load()["threads"].get(thread_id)
        return dict(thread) if thread else None


def _change(thread_id: str, **changes: Any) -> Dict[str, Any]:
    with _LOCK:
        state = _load()
        thread = state["threads"].get(thread_id)
        if thread is None:
            raise CommanderError("No such thread.")
        thread.update(changes, updated=time.time())
        _save(state)
        result = dict(thread)
    _publish()
    return view(result)


def resolve_thread(thread_id: str, resolved: bool = True) -> Dict[str, Any]:
    return _change(thread_id, resolved=bool(resolved))


def pin_thread(thread_id: str, pinned: bool = True) -> Dict[str, Any]:
    return _change(thread_id, pinned=bool(pinned))


def set_pick(thread_id: str, *, tier: str = "", effort: str = "", sector: str = "", provider: Optional[str] = None,
             model: Optional[str] = None) -> Dict[str, Any]:
    """The owner overrides a thread's model, effort or sector. That correction teaches the picker (counted 3×)."""
    import commander_pick

    thread = get(thread_id)
    if thread is None:
        raise CommanderError("No such thread.")
    changes: Dict[str, Any] = {}
    if tier:
        if tier not in commander_pick.TIERS:
            raise CommanderError(f"Kinds are {', '.join(commander_pick.TIERS)}.")
        changes["tier"] = tier
        if provider is None:
            found = commander_pick.model_for(tier)
            changes.update(provider=found["provider"], model=found["model"], model_label=found["label"])
    if effort:
        if effort not in commander_pick.EFFORTS:
            raise CommanderError(f"Effort is {', '.join(commander_pick.EFFORTS)}.")
        changes["effort"] = effort
    if sector:
        if sector not in commander_pick.SECTORS:
            raise CommanderError(f"Sectors are {', '.join(commander_pick.SECTORS)}.")
        changes["sector"] = sector
    if provider is not None:
        changes.update(provider=_clean(provider, 40), model=_clean(model, 120),
                       model_label=_clean(f"{provider}{' · ' + model if model else ''}", 160))
    if not changes:
        return view(thread)
    changes.update(why="you chose it", source="owner")
    merged = {**thread, **changes}
    commander_pick.PICKER.learn(f"{thread['title']}. {thread['task']}", merged["tier"], merged["effort"],
                                merged["sector"], by_owner=True, title=thread["title"])
    return _change(thread_id, **changes)


def delete_thread(thread_id: str) -> bool:
    """Forget the thread record. Its chat stays in the chat list, so nothing the owner made is lost."""
    with _LOCK:
        state = _load()
        if thread_id not in state["threads"]:
            return False
        del state["threads"][thread_id]
        _save(state)
    _publish()
    return True


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def view(thread: Dict[str, Any], *, messages: Optional[List[Dict[str, Any]]] = None,
         approvals: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """A thread as the panel shows it: live status, one-line status, and how full its context is."""
    import commander_pick

    if messages is None:
        try:
            messages = _store().messages(thread["chat_id"])
        except Exception:
            messages = []
    live = read_chat(thread["chat_id"], messages, approvals)
    status = "resolved" if thread.get("resolved") and live["status"] != "working" else live["status"]
    use = _measure(messages, thread.get("provider", ""), thread.get("model", ""))
    return {
        **{k: v for k, v in thread.items() if k != "turns"},
        "status": status, "status_label": STATUS_LABELS[status], "kind": live.get("kind", ""),
        "line": live["line"], "turn_id": live.get("turn_id", ""), "approval_id": live.get("approval_id", ""),
        "tier_label": commander_pick.TIER_LABELS.get(thread.get("tier", ""), thread.get("tier", "")),
        "tokens": use, "fresh_soon": use["share"] >= REFRESH_AT,
        "messages": sum(1 for m in messages if m.get("role") in ("user", "assistant")),
    }


def threads(*, delegator: str = "", project_id: str = "") -> List[Dict[str, Any]]:
    with _LOCK:
        rows = [dict(t) for t in _load()["threads"].values()
                if (not delegator or t["delegator"] == delegator) and (not project_id or t["project_id"] == project_id)]
    approvals = _approvals()
    store = _store()
    out = []
    for row in rows:
        try:
            messages = store.messages(row["chat_id"])
        except Exception:
            messages = []
        out.append(view(row, messages=messages, approvals=approvals))
    return sorted(out, key=lambda t: -t.get("updated", 0))


def _done(thread: Dict[str, Any]) -> bool:
    return thread["status"] == "resolved" or (thread["status"] == "idle" and thread.get("kind") == "finished")


def task_counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """Tasks done out of all, for "Tasks 3/7". A thread restarted fresh is one task, counted once in its fresh thread."""
    tasks = [t for t in rows if not t.get("refreshed_to")]
    return {"done": sum(1 for t in tasks if _done(t)), "total": len(tasks)}


def board(*, delegator: str = "", project_id: str = "") -> Dict[str, Any]:
    """The right-hand panel (image p27): Pinned, Needs you, Working, Idle and Resolved, newest first in each. For one
    main chat it also brings that chat's asks up to date (``sync_asks``), from the same reading of its threads."""
    everything = threads(delegator=delegator)
    rows = [t for t in everything if not project_id or t["project_id"] == project_id]
    asks = sync_asks(delegator, everything) if delegator else []
    projects: Dict[str, List[Dict[str, Any]]] = {}
    for t in rows:
        projects.setdefault(t.get("project_id") or "", []).append(t)
    groups = [{"id": "pinned", "label": "Pinned", "threads": [t for t in rows if t.get("pinned")]}]
    for status in ("needs_you", "working", "idle", "resolved"):
        groups.append({"id": status, "label": STATUS_LABELS[status],
                       "threads": [t for t in rows if t["status"] == status and not t.get("pinned")]})
    used = sum(t["tokens"]["used"] for t in rows)
    return {"groups": groups, "total": len(rows), "needs_you": sum(1 for t in rows if t["status"] == "needs_you"),
            "working": sum(1 for t in rows if t["status"] == "working"), "tokens": used,
            "sectors": sorted({t["sector"] for t in rows if t.get("sector")}),
            "tasks": task_counts(rows), "by_project": {pid: task_counts(ts) for pid, ts in projects.items() if pid},
            "asks": asks}


# ---------------------------------------------------------------------------
# The relay: threads post their questions, approvals and results up to their main chat
# ---------------------------------------------------------------------------
# Owner request (2026-10-14): like this Claude project, threads send their asks and results to the main chat, where the
# owner mainly looks, and he can answer in either place. Asks are not written into the main chat's history: that would
# cost the delegator a model turn per answer and fill its context. They are kept here, each anchored after the main
# chat message it arrived behind (``after``), and drawn in place by CommanderView. Each read of the board reconciles
# them with the threads' live state, so an answer given in the thread closes the ask in the main chat too.

MAX_ASKS = 300


def _ask_key(thread: Dict[str, Any]) -> str:
    """One key per thing a thread asked or reported, so polling the board never posts it twice."""
    if thread.get("refreshed_to"):
        return ""
    if thread["status"] == "needs_you":
        return f"{thread['kind']}:{thread['id']}:{thread.get('approval_id') or thread['messages']}"
    if thread["status"] == "idle" and thread.get("kind") == "finished":
        return f"result:{thread['id']}:{thread['messages']}"
    return ""


def _card_source(chat_id: str) -> str:
    """The question card a thread asked, as written, so the main chat can show the same card."""
    try:
        from question_cards import BLOCK_RE

        last = _last(_store().messages(chat_id), "assistant")
        found = BLOCK_RE.search(str((last or {}).get("content") or ""))
        return found.group(0) if found else ""
    except Exception:
        return ""


def _short_answer(text: str) -> str:
    """A card's answer is "**Question?**" then "→ choice" lines; the main chat shows only the choices."""
    picked = [ln.strip().lstrip("→").strip() for ln in text.splitlines() if ln.strip().startswith("→")]
    return _clean("; ".join(picked) if picked else text, 200)


def sync_asks(delegator: str, rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Post each thread's new question, approval or result to its main chat, close the asks that were answered in
    the thread, and return the main chat's asks, oldest first."""
    if not delegator:
        return []
    rows = threads(delegator=delegator) if rows is None else rows
    try:
        anchor = sum(1 for m in _store().messages(delegator) if m.get("role") in ("user", "assistant"))
    except Exception:
        anchor = 0
    now = time.time()
    changed = False
    with _LOCK:
        state = _load()
        asks = state.setdefault("asks", {})
        mine = {a["key"]: a for a in asks.values() if a["delegator"] == delegator}
        live = {}
        for t in rows:
            key = _ask_key(t)
            if not key:
                continue
            live[t["id"]] = key
            if key in mine:
                continue
            kind = "result" if key.startswith("result:") else t["kind"]
            ask = {"id": f"ask-{uuid.uuid4().hex[:8]}", "key": key, "delegator": delegator, "thread_id": t["id"],
                   "title": t["title"], "kind": kind, "line": t["line"], "approval_id": t.get("approval_id", ""),
                   "card": _card_source(t["chat_id"]) if kind == "question" else "", "after": anchor,
                   "created": now, "open": kind != "result", "answer": "", "where": ""}
            asks[ask["id"]] = mine[key] = ask
            changed = True
        for ask in mine.values():
            if ask["open"] and live.get(ask["thread_id"]) != ask["key"]:
                ask.update(open=False, where=ask["where"] or "thread", closed=now)
                changed = True
        if changed:
            if len(asks) > MAX_ASKS:
                oldest = sorted((a for a in asks.values() if not a["open"]), key=lambda a: a["created"])
                for old in oldest[:len(asks) - MAX_ASKS]:
                    asks.pop(old["id"], None)
            _save(state)
        out = sorted((dict(a) for a in asks.values() if a["delegator"] == delegator), key=lambda a: a["created"])
    if changed:
        _publish()
    return out[-60:]


def answer_ask(ask_id: str, *, text: str = "", approve: Optional[bool] = None, role: str = "local") -> Dict[str, Any]:
    """The owner answers a thread from the main chat. The answer goes to the thread as his message (or decides its
    approval), and the ask shows as answered in both places."""
    with _LOCK:
        ask = dict((_load().get("asks") or {}).get(ask_id) or {})
    if not ask:
        raise CommanderError("No such question.")
    if not ask["open"]:
        raise CommanderError("That was already answered.")
    if ask["kind"] == "approval":
        if approve is None:
            raise CommanderError("Approve or deny it.")
        if not _decide(ask["approval_id"], bool(approve)):
            raise CommanderError("That request was already answered or timed out.")
        answer = "Approved" if approve else "Denied"
    else:
        answer = str(text or "").strip()
        if not answer:
            raise CommanderError("Type an answer.")
        message_thread(ask["thread_id"], answer, delegator=ask["delegator"], role=role)
    with _LOCK:
        state = _load()
        row = state.get("asks", {}).get(ask_id)
        if row is not None:
            row.update(open=False, where="main", answer=_short_answer(answer), closed=time.time())
            _save(state)
            ask = dict(row)
    _publish()
    return ask


def brief(chat_id: str) -> str:
    """This turn's Commander brief for a delegator chat, with its threads as they stand. Empty for any other chat."""
    with _LOCK:
        row = _load()["delegators"].get(chat_id or "")
    if row is None:
        return ""
    where = _where(row.get("project_id", ""))
    mine = [t for t in threads(delegator=chat_id) if t["status"] != "resolved"][:20]
    listing = "\n".join(
        f"- {t['title']} · {t['status_label']} · {t['tier_label']}/{t['effort']} · "
        f"{round(t['tokens']['share'] * 100)}% full · {t['line'][:90]}" for t in mine) or "- none yet"
    return (
        f"{BRIEF_PREFIX} Commander{where}\n"
        "This chat is the delegator. Keep it clean: hand the work to threads instead of doing it here.\n"
        "- Each separate piece of work gets its own thread: start_thread with a short title (a few plain words) and a "
        "full brief, because threads do not see this chat. Leave model_kind and effort empty so Nyx picks them, unless "
        "the owner named them.\n"
        "- More work for something that already has a thread goes to it with message_thread, not a new thread. A thread "
        "that is too full is restarted fresh with a summary for you automatically.\n"
        "- read_thread shows what a thread said; resolve_thread when its work is done and nothing is owed.\n"
        "- A small question you can answer from what you already know gets a one-line answer here, no thread.\n"
        "- Threads' questions, approvals and results show up in this chat by themselves, and the owner can answer them "
        "there; do not repeat them. When he answers one in his own words here, pass it on with message_thread.\n"
        "Reply in two to four short lines: which threads got what, and what (if anything) needs the owner.\n"
        f"Threads now:\n{listing}"
    )


# ---------------------------------------------------------------------------
# Tools for the delegator chat
# ---------------------------------------------------------------------------

def _context() -> tuple:
    try:
        from tool_context import current

        ctx = current()
    except Exception:
        ctx = None
    return (getattr(ctx, "chat_id", "") if ctx else ""), (getattr(ctx, "role", "local") if ctx else "local")


def _short(thread: Dict[str, Any]) -> str:
    return (f"“{thread['title']}” ({thread['status_label']}, {thread['tier_label']} model"
            f"{' ' + thread['model_label'] if thread.get('model_label') else ''}, {thread['effort']} effort, "
            f"{thread['sector']})")


def tool_start_thread(title: str, task: str, model_kind: str = "", effort: str = "", provider: str = "") -> str:
    chat_id, role = _context()
    if not is_delegator(chat_id):
        return "Error: only a Commander chat hands out threads. Do this work here instead."
    try:
        thread = start_thread(chat_id, title, task, tier=model_kind, effort=effort, provider=provider, role=role)
    except CommanderError as error:
        return f"Error: {error}"
    return f"Started {_short(thread)} because {thread['why']}. It is working now."


def tool_message_thread(thread: str, text: str) -> str:
    chat_id, role = _context()
    if not is_delegator(chat_id):
        return "Error: only a Commander chat sends work to threads."
    try:
        result = message_thread(thread, text, delegator=chat_id, role=role)
    except CommanderError as error:
        return f"Error: {error}"
    if result.get("refreshed_from"):
        return f"That thread was too full, so {_short(result)} took over with a summary of it and the new work."
    return f"Sent to {_short(result)}."


def tool_list_threads() -> str:
    chat_id, _role = _context()
    rows = threads(delegator=chat_id) if is_delegator(chat_id) else []
    if not rows:
        return "No threads yet."
    return "\n".join(f"- {_short(t)}: {t['line']} · {round(t['tokens']['share'] * 100)}% full" for t in rows[:40])


def tool_read_thread(thread: str, last: int = 4) -> str:
    chat_id, _role = _context()
    if not is_delegator(chat_id):
        return "Error: only a Commander chat reads its threads."
    with _LOCK:
        found = _find(_load(), thread, chat_id)
    if found is None:
        return f"Error: no thread called {thread!r}."
    talk = [m for m in _store().messages(found["chat_id"]) if m.get("role") in ("user", "assistant")]
    keep = talk[-max(1, min(int(last or 4), 12)):]
    return "\n\n".join(f"{m['role']}: {str(m.get('content', ''))[:1500]}" for m in keep) or "Nothing said yet."


def tool_resolve_thread(thread: str) -> str:
    chat_id, _role = _context()
    if not is_delegator(chat_id):
        return "Error: only a Commander chat resolves its threads."
    with _LOCK:
        found = _find(_load(), thread, chat_id)
    if found is None:
        return f"Error: no thread called {thread!r}."
    resolve_thread(found["id"])
    return f"Resolved “{found['title']}”."


def register_commander_tools(registry: Any) -> None:
    from tools import ToolParam as P

    registry.register(
        "start_thread",
        "Commander chats only: hand one separate piece of work to a new thread. Nyx picks the model and effort "
        "unless the owner named them. The thread does not see this chat, so the task must say everything.",
        [P("title", "string", "A few plain words naming the work"),
         P("task", "string", "The full brief: what to do, what done looks like, any facts it needs"),
         P("model_kind", "string", "Only if the owner asked: pico (light), monolith (general), crescendo (heavy) or "
           "zencode (code)", required=False, enum_values=["pico", "monolith", "crescendo", "zencode"]),
         P("effort", "string", "Only if the owner asked: low, mid, normal, high, higher, super or aleph", required=False,
           enum_values=["low", "mid", "normal", "high", "higher", "super", "aleph"]),
         P("provider", "string", "Only if the owner named a provider", required=False)],
        tool_start_thread, category="agents", label=lambda a: f"Starting a thread: {str(a.get('title', ''))[:50]}")
    registry.register(
        "message_thread",
        "Commander chats only: send more work or an answer to an existing thread (by its title).",
        [P("thread", "string", "The thread's title"), P("text", "string", "What it should do next")],
        tool_message_thread, category="agents", label=lambda a: f"Messaging the thread {str(a.get('thread', ''))[:40]}")
    registry.register(
        "list_threads", "Commander chats only: the threads with status, model, effort and how full each is.", [],
        tool_list_threads, category="general", label="Checking the threads")
    registry.register(
        "read_thread", "Commander chats only: the last few messages of one thread.",
        [P("thread", "string", "The thread's title"),
         P("last", "integer", "How many messages (default 4)", required=False)],
        tool_read_thread, category="general", label=lambda a: f"Reading the thread {str(a.get('thread', ''))[:40]}")
    registry.register(
        "resolve_thread", "Commander chats only: mark a thread done when its work is finished and nothing is owed.",
        [P("thread", "string", "The thread's title")],
        tool_resolve_thread, category="general", label=lambda a: f"Resolving {str(a.get('thread', ''))[:40]}")
