"""Equalize — the assistant that lives in the notch (owner, 2026-10-11, verbatim in AI_HANDOFF/01_GOALS.md).

The owner asked for Coucou's notch, exactly, with Ichos's own character and more: agents you can drop in, pick, give a
task and watch work live (code as it is written, an email as it is drafted), files that are read at once and acted on
("send it to …"), a three-part notch when things build up (a pinned app's work · the clock and timers · the sound
playing), and a setup page for talking to it: whether to talk at all, the gesture that wakes it, the voice, the
personality and the avatar.

This module is the state behind all of that. The notch window and the Equalize tab are two views of it:

* ``settings()`` / ``update()`` — everything the owner sets, one JSON file.
* ``agents()`` — who is working right now: Ichos itself, the owner's avatars, Claude Code sessions on this PC and
  anything started from the notch; ``work(agent_id)`` — the live steps behind one of them.
* ``start_task()`` — give an agent (or a brand-new one) a task; its tool calls stream in as steps, with diffs for
  code and the draft for email.
* ``read_file()`` — the fast read of a dropped file (no model): what it is, the numbers that matter, what to do next.
* ``intent()`` — "send it to sam@…" said with a file attached becomes a ready email; nothing is sent until the owner
  presses Send (``send_mail``).
* timers, the pinned apps, voice from a description or a sample, the avatar and whose personality to keep.
"""

from __future__ import annotations

import csv
import io
import json
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from paths import atomic_replace, data_path, project_path

STORE = data_path("equalize_assistant.json")
JOBS_FILE = data_path("equalize_jobs.json")

#: Agent colours, in order (Coucou's palette for "other" agents).
COLORS = ["#F472B6", "#34D399", "#FB923C", "#60A5FA", "#E879F9", "#38BDF8", "#F7B32B", "#A78BFA"]
APP_COLORS = {"github": "#F4505E", "vscode": "#F5F6F8", "claude": "#FF6B5B", "vercel": "#8B5CF6", "n8n": "#F7B32B",
              "stripe": "#3B82F6", "gmail": "#EA4335", "notion": "#E6E9EE", "figma": "#A259FF", "slack": "#4A154B"}

GESTURES = {
    "clap": "Clap twice — heard from the shape of the sound, works offline.",
    "snap": "A finger snap — a short, sharp click; teach it once so it knows yours.",
    "whistle": "A whistle — a steady single tone.",
    "phrase": "Say your wake phrase — any words you choose, matched on this PC.",
    "knock": "Knock on the desk — taught once, like the snap.",
    "hotkey": "A keyboard shortcut — Ctrl+Alt+Space by default.",
    "hover": "Move the mouse to the top centre of the screen.",
}

DEFAULTS: Dict[str, Any] = {
    "talk": False,                      # owner chose to talk to it (voice) or not
    "activation": {"gestures": ["hotkey", "hover"], "phrase": "", "hotkey": "Ctrl+Alt+Space", "sensitivity": 0.6},
    "voice": {"mode": "default", "description": "", "voice_id": "", "rate": "+0%", "pitch": "+0Hz", "sample": None,
              "name": ""},
    "personality": {"source": "normal", "text": ""},  # normal | custom | avatar
    "avatar": {"id": "", "name": "Io", "image": "", "personality": "", "keep_personality": False},
    "sound": {"muted": False, "volume": 0.6, "mode": "ai"},  # ai = Ichos's own voice; system = everything playing
    "notch": {"enabled": False, "open_on_hover": True, "autoclose_s": 60, "hide_after_min": 3, "trio": True,
              "effects": True},
    "pinned": [],                       # specialty apps on the left notch: {id, name, kind, target, color}
    "timers": [],                       # {id, label, started, ends}
    "ultrafast": False,
    "dropped": [],                      # agents/avatars dragged into the notch, in order
}

_lock = threading.RLock()
_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_loaded = False


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def _merge(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    out = json.loads(json.dumps(base))
    for key, value in (extra or {}).items():
        if key not in out:
            continue
        if isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = {**out[key], **{k: v for k, v in value.items() if k in out[key]}}
        else:
            out[key] = value
    return out


def _load() -> Dict[str, Any]:
    try:
        return _merge(DEFAULTS, json.loads(STORE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return _merge(DEFAULTS, {})


def _save(state: Dict[str, Any]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    atomic_replace(tmp, STORE)


def _check(state: Dict[str, Any]) -> Dict[str, Any]:
    """Keep every value inside what the notch can show."""
    act = state["activation"]
    act["gestures"] = [g for g in dict.fromkeys(act.get("gestures") or []) if g in GESTURES]
    act["phrase"] = str(act.get("phrase") or "")[:60]
    act["hotkey"] = str(act.get("hotkey") or "Ctrl+Alt+Space")[:40]
    act["sensitivity"] = max(0.1, min(1.0, float(act.get("sensitivity") or 0.6)))
    sound = state["sound"]
    sound["volume"] = max(0.0, min(1.0, float(sound.get("volume") if sound.get("volume") is not None else 0.6)))
    sound["mode"] = sound.get("mode") if sound.get("mode") in ("ai", "system") else "ai"
    sound["muted"] = bool(sound.get("muted"))
    if state["personality"].get("source") not in ("normal", "custom", "avatar"):
        state["personality"]["source"] = "normal"
    state["personality"]["text"] = str(state["personality"].get("text") or "")[:1200]
    notch = state["notch"]
    notch["autoclose_s"] = max(5, min(600, int(notch.get("autoclose_s") or 60)))
    notch["hide_after_min"] = max(1, min(120, int(notch.get("hide_after_min") or 3)))
    pinned = []
    for item in state.get("pinned") or []:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            continue
        kind = str(item.get("kind") or "app").lower()
        pinned.append({"id": str(item.get("id") or uuid.uuid4().hex[:8])[:24], "name": str(item["name"])[:40],
                       "kind": kind, "target": str(item.get("target") or "")[:300],
                       "color": str(item.get("color") or APP_COLORS.get(kind, COLORS[len(pinned) % len(COLORS)]))[:16]})
    state["pinned"] = pinned[:4]
    state["dropped"] = [str(d)[:64] for d in dict.fromkeys(state.get("dropped") or [])][:8]
    state["talk"], state["ultrafast"] = bool(state.get("talk")), bool(state.get("ultrafast"))
    return state


def settings() -> Dict[str, Any]:
    with _lock:
        state = _load()
    state["timers"] = [t for t in state["timers"] if t.get("ends", 0) > time.time() - 3600]
    state["gesture_help"] = GESTURES
    return state


def update(changes: Dict[str, Any]) -> Dict[str, Any]:
    with _lock:
        state = _load()
        for key, value in (changes or {}).items():
            if key not in DEFAULTS or key == "timers":
                continue
            if isinstance(DEFAULTS[key], dict) and isinstance(value, dict):
                state[key].update({k: v for k, v in value.items() if k in DEFAULTS[key]})
            elif not isinstance(DEFAULTS[key], dict):
                state[key] = value
        _save(_check(state))
    return settings()


# ---------------------------------------------------------------------------
# Timers (the middle notch)
# ---------------------------------------------------------------------------

def add_timer(seconds: float, label: str = "") -> Dict[str, Any]:
    seconds = max(1.0, min(24 * 3600.0, float(seconds)))
    timer = {"id": uuid.uuid4().hex[:8], "label": str(label or "Timer")[:40], "started": time.time(),
             "ends": time.time() + seconds}
    with _lock:
        state = _load()
        state["timers"] = [t for t in state["timers"] if t.get("ends", 0) > time.time()][-5:] + [timer]
        _save(state)
    return timer


def remove_timer(timer_id: str) -> bool:
    with _lock:
        state = _load()
        before = len(state["timers"])
        state["timers"] = [t for t in state["timers"] if t.get("id") != timer_id]
        _save(state)
    return len(state["timers"]) < before


def parse_timer(text: str) -> Optional[float]:
    """'set a timer for 5 minutes' / '90 seconds' / '1h 30m' -> seconds."""
    text = str(text or "").lower()
    if not re.search(r"\b(timer|remind|countdown|alarm)\b", text):
        return None
    total = 0.0
    for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hours?|m|min|mins|minutes?|s|sec|secs|seconds?)\b", text):
        total += float(amount) * (3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1)
    if not total:
        words = {"a minute": 60, "half an hour": 1800, "an hour": 3600, "a second": 1}
        total = next((v for k, v in words.items() if k in text), 0)
    return total or None


# ---------------------------------------------------------------------------
# Agents and their work
# ---------------------------------------------------------------------------

def _load_jobs() -> None:
    global _jobs_loaded
    if _jobs_loaded:
        return
    _jobs_loaded = True
    try:
        for job in json.loads(JOBS_FILE.read_text(encoding="utf-8")):
            if job.get("status") == "running":
                job["status"] = "stopped"  # the engine restarted under it
            _jobs[job["id"]] = job
    except (OSError, ValueError, KeyError, TypeError):
        pass


def _save_jobs() -> None:
    rows = sorted(_jobs.values(), key=lambda j: j.get("started", 0))[-30:]
    JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = JOBS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows), encoding="utf-8")
    atomic_replace(tmp, JOBS_FILE)


def _color(key: str) -> str:
    return COLORS[sum(map(ord, key)) % len(COLORS)]


def catalog() -> List[Dict[str, Any]]:
    """Everyone the owner can drag into the notch or hand a task to: avatars, the agent roster, Claude Code."""
    rows: List[Dict[str, Any]] = [{"id": "claude", "name": "Claude Code", "kind": "claude", "color": "#FF6B5B",
                                   "about": "Writes and edits code in a folder on this PC"}]
    try:
        import avatars

        for a in avatars.list_avatars():
            rows.append({"id": f"avatar:{a['id']}", "name": a.get("name", "Avatar"), "kind": "avatar",
                         "color": _color(a["id"]), "about": str(a.get("main_function") or a.get("what") or "")[:120],
                         "personality": avatars.personality_text(a)[:300], "enabled": bool(a.get("enabled"))})
    except Exception:  # noqa: BLE001 - avatars are optional here
        pass
    try:
        roster = json.loads(Path(project_path("agent_roster.json")).read_text(encoding="utf-8"))
        for agent in (roster.get("agents") if isinstance(roster, dict) else roster) or []:
            name = str(agent.get("name") or "").strip()
            if name:
                rows.append({"id": f"agent:{name}", "name": name, "kind": "agent",
                             "color": str(agent.get("color") or _color(name))[:16],
                             "about": str(agent.get("goal") or agent.get("role") or "")[:120]})
    except (OSError, ValueError, AttributeError):
        pass
    return rows


def _claude_live() -> List[Dict[str, Any]]:
    try:
        import claude_sessions

        rows = claude_sessions.sessions()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for row in rows[:6]:
        if row.get("state") not in ("working", "needs_you") and time.time() - float(row.get("last") or 0) > 1800:
            continue
        state = {"working": "working", "needs_you": "approval", "your_turn": "finished"}.get(row.get("state"), "idle")
        out.append({"id": f"session:{row['id']}", "name": row.get("project") or "Claude Code", "kind": "claude",
                    "sub": "Claude Code", "color": "#FF6B5B", "state": state,
                    "step": str(row.get("why") or row.get("title") or "")[:90], "last": row.get("last")})
    return out


def agents() -> List[Dict[str, Any]]:
    """Who is in the notch: Ichos first, then running jobs, Claude Code sessions, then the dropped-in agents."""
    _load_jobs()
    state = _load()
    rows: List[Dict[str, Any]] = [{"id": "ichos", "name": state["avatar"].get("name") or "Io", "kind": "ichos",
                                   "sub": "Ichos", "color": "#A594FF", "state": "idle", "step": ""}]
    seen = {"ichos"}
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: -j.get("started", 0))
    for job in jobs:
        agent = job["agent"]
        if agent["id"] in seen or (job["status"] != "running" and time.time() - job.get("ended", 0) > 900):
            continue
        seen.add(agent["id"])
        last = job["steps"][-1] if job["steps"] else {}
        rows.append({**agent, "state": {"running": "working", "done": "finished", "error": "error"}.get(job["status"], "idle"),
                     "step": last.get("title", "Starting"), "job": job["id"], "count": len(job["steps"]),
                     "kind_of_work": job.get("work", "general")})
    for row in _claude_live():
        if row["id"] not in seen:
            seen.add(row["id"])
            rows.append(row)
    known = {c["id"]: c for c in catalog()}
    for dropped in state["dropped"]:
        if dropped not in seen and dropped in known:
            seen.add(dropped)
            rows.append({**known[dropped], "state": "idle", "step": known[dropped].get("about", "")})
    return rows


def _diff(old: str, new: str, start: int = 1) -> List[Dict[str, Any]]:
    """A small line diff for the live code card: removed lines, then added ones, with line numbers."""
    import difflib

    lines: List[Dict[str, Any]] = []
    old_lines, new_lines = (old or "").splitlines(), (new or "").splitlines()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_lines, new_lines).get_opcodes():
        if tag == "equal":
            for offset, text in enumerate(old_lines[i1:i2][:3]):
                lines.append({"sym": " ", "no": start + j1 + offset, "text": text})
            continue
        for offset, text in enumerate(old_lines[i1:i2]):
            lines.append({"sym": "-", "no": start + i1 + offset, "text": text})
        for offset, text in enumerate(new_lines[j1:j2]):
            lines.append({"sym": "+", "no": start + j1 + offset, "text": text})
    return lines[:120]


def step_from_tool(name: str, args: Dict[str, Any], label: str = "") -> Dict[str, Any]:
    """One readable step from a tool call: what kind it is, its title, and the code or email behind it."""
    name = str(name or "")
    if name.startswith("mcp__"):  # mcp__Claude_Browser__browser_batch -> "browser batch"
        name = name.rsplit("__", 1)[-1]
    low = name.lower()
    args = args if isinstance(args, dict) else {}
    path = str(args.get("file_path") or args.get("path") or args.get("filename") or "")
    short = Path(path).name if path else ""
    step: Dict[str, Any] = {"at": time.time(), "tool": name, "kind": "tool", "title": label or name.replace("_", " ")}
    if "email" in low or "mail" in low and ("send" in low or "reply" in low or "draft" in low):
        step.update(kind="email", title=f"Email to {args.get('to') or 'someone'}",
                    email={"to": str(args.get("to") or ""), "subject": str(args.get("subject") or ""),
                           "body": str(args.get("body") or "")[:4000]})
    elif low in ("edit", "multiedit", "edit_file", "replace_in_file", "str_replace", "apply_patch") or "edit" in low:
        step.update(kind="edit", title=f"Edit {short or 'a file'}", file=path,
                    diff=_diff(str(args.get("old_string") or args.get("old") or ""),
                               str(args.get("new_string") or args.get("new") or args.get("content") or "")))
    elif low in ("write", "write_file", "create_file", "save_file") or low.startswith("write"):
        content = str(args.get("content") or args.get("text") or "")
        step.update(kind="edit", title=f"Write {short or 'a file'}", file=path, diff=_diff("", content))
    elif low in ("read", "read_file", "file_excerpt", "read_document", "view") or low.startswith("read"):
        step.update(kind="read", title=f"Read {short or args.get('query') or 'a file'}", file=path)
    elif low in ("bash", "run_command", "powershell", "shell", "run_python") or "command" in low:
        command = str(args.get("command") or args.get("code") or "")
        step.update(kind="bash", title=f"Run {command[:60]}" if command else "Run a command", command=command[:400])
    elif "search" in low or "fetch" in low or "web" in low:
        step.update(kind="search", title=label or f"Search {str(args.get('query') or args.get('url') or '')[:60]}")
    return step


def _job(agent: Dict[str, Any], task: str, work: str) -> Dict[str, Any]:
    job = {"id": uuid.uuid4().hex[:10], "agent": agent, "task": task[:2000], "work": work, "status": "running",
           "started": time.time(), "ended": 0, "steps": [], "result": ""}
    with _lock:
        _load_jobs()
        _jobs[job["id"]] = job
    _publish(job)
    return job


def _publish(job: Dict[str, Any]) -> None:
    try:
        from agent_events import publish_ui

        publish_ui("equalize.job", id=job["id"], agent=job["agent"]["id"], status=job["status"],
                   steps=len(job["steps"]))
    except Exception:  # noqa: BLE001
        pass


def _add_step(job: Dict[str, Any], step: Dict[str, Any]) -> None:
    with _lock:
        job["steps"].append(step)
        del job["steps"][:-80]
        if step.get("kind") == "email":
            job["work"] = "email"
        elif step.get("kind") == "edit" and job["work"] == "general":
            job["work"] = "code"
    _publish(job)


def _finish(job: Dict[str, Any], ok: bool, result: str) -> None:
    with _lock:
        job.update(status="done" if ok else "error", ended=time.time(), result=str(result or "")[:6000])
        job["steps"].append({"at": time.time(), "kind": "done" if ok else "error",
                             "title": "Done" if ok else "Stopped with an error"})
        _save_jobs()
    _publish(job)


def _looks_like_code(task: str) -> bool:
    return bool(re.search(r"\b(code|repo|repository|bug|fix|refactor|function|file|commit|build|test|deploy|component"
                          r"|script|github|pull request|pr\b|merge|branch)\b", task, re.I))


def _claude_events(line: str, job: Dict[str, Any]) -> Optional[str]:
    """One line of `claude -p --output-format stream-json`: tool calls become steps; returns the final text."""
    try:
        event = json.loads(line)
    except ValueError:
        return None
    if event.get("type") == "assistant":
        for part in (event.get("message") or {}).get("content") or []:
            if part.get("type") == "tool_use":
                _add_step(job, step_from_tool(part.get("name", ""), part.get("input") or {}))
            elif part.get("type") == "text" and part.get("text", "").strip():
                _add_step(job, {"at": time.time(), "kind": "note", "title": part["text"].strip()[:140]})
    if event.get("type") == "result":
        return str(event.get("result") or "")
    return None


def _run_claude(job: Dict[str, Any], task: str, folder: str, runner: Any = None) -> None:
    import claude_bridge

    exe = claude_bridge.find_claude()
    if not exe:
        _finish(job, False, "Claude Code is not installed on this PC.")
        return
    where = Path(folder).expanduser() if folder else Path(project_path("."))
    command = [exe, "-p", task, "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits"]
    popen = runner or subprocess.Popen
    result = ""
    try:
        process = popen(command, cwd=str(where), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                        encoding="utf-8", errors="replace", creationflags=getattr(claude_bridge, "_NO_WINDOW", 0))
        with _lock:
            job["pid"] = getattr(process, "pid", 0)
        for line in process.stdout:
            text = _claude_events(line, job)
            if text is not None:
                result = text
        process.wait(timeout=30)
        _finish(job, process.returncode == 0, result or "Finished.")
    except Exception as error:  # noqa: BLE001
        _finish(job, False, f"{type(error).__name__}: {error}")


def _run_chat(job: Dict[str, Any], agent: Dict[str, Any], task: str, turn: Optional[Callable] = None) -> None:
    """An avatar or roster agent works in its own chat; every tool call it makes arrives as a step."""
    text_parts: List[str] = []

    def sink(event: Dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "tool.start":
            _add_step(job, step_from_tool(event.get("name", ""), event.get("args") or {}, event.get("label", "")))
        elif kind == "answer.delta":
            text_parts.append(str(event.get("text") or ""))

    try:
        reply = (turn or _chat_turn)(agent, task, sink)
        _finish(job, True, reply or "".join(text_parts))
    except Exception as error:  # noqa: BLE001
        _finish(job, False, f"{type(error).__name__}: {error}")


def _chat_turn(agent: Dict[str, Any], task: str, sink: Callable[[Dict[str, Any]], None]) -> str:
    import server

    store = server._shared_chat_store()
    chat_id = store.create(title=f"Equalize · {agent['name']}", activate=False)
    service = server._get_service(chat_id)
    guard_before = getattr(service, "tool_guard", None)
    note = f"You are {agent['name']}, working for the owner from the Ichos notch. Do the task, then say what you did."
    if agent.get("kind") == "avatar":
        import avatars

        from persona_scope import badge_avatar_chat

        record = avatars.get(agent["id"].split(":", 1)[1])
        if record is not None:
            service.tool_guard = avatars.AvatarGuard(record)
            badge_avatar_chat(store, chat_id, record)  # its bank comes from the badge (persona_scope.prepare_turn)
            note = ""
    # The notch's own voice only when the owner picked one for it ("selected as main"), for this task only.
    service.turn_persona = None
    if agent.get("kind") == "ichos" and personality_note():
        service.turn_persona = {"display_name": agent["name"], "system_guidance": personality_note()}
    try:
        service.set_turn_context(note)
        result = service.chat_turn(task, sink=sink, role="local", turn_id=uuid.uuid4().hex[:12])
    finally:
        service.tool_guard = guard_before
    return str((result or {}).get("reply") or "") if isinstance(result, dict) else str(result or "")


def start_task(agent_id: str, task: str, folder: str = "", new_name: str = "", app: str = "",
               background: bool = True) -> Dict[str, Any]:
    """Hand ``task`` to an agent (or a new one called ``new_name``) and return the job it runs as."""
    task = str(task or "").strip()
    if not task:
        raise ValueError("Say what the agent should do.")
    known = {c["id"]: c for c in catalog()}
    if new_name.strip():
        agent = {"id": f"agent:{new_name.strip()[:40]}", "name": new_name.strip()[:40], "kind": "agent",
                 "color": _color(new_name)}
    elif agent_id in known:
        agent = {k: known[agent_id][k] for k in ("id", "name", "kind", "color")}
    elif agent_id == "ichos":
        agent = {"id": "ichos", "name": _load()["avatar"].get("name") or "Io", "kind": "ichos", "color": "#A594FF"}
    else:
        raise ValueError("No such agent.")
    pinned = next((p for p in _load()["pinned"] if p["id"] == app), None)
    if pinned:
        agent = {**agent, "app": pinned["id"]}
        task = f"Using {pinned['name']}" + (f" ({pinned['target']})" if pinned["target"] else "") + f": {task}"
        if pinned["kind"] == "github" and not folder and Path(pinned["target"]).expanduser().is_dir():
            folder = pinned["target"]
    coding = agent["kind"] == "claude" or (pinned is not None and pinned["kind"] in ("github", "vscode") and _looks_like_code(task))
    job = _job(agent, task, "code" if coding else "general")
    _add_step(job, {"at": time.time(), "kind": "note", "title": "Starting: " + task[:120]})
    target = (lambda: _run_claude(job, task, folder)) if coding else (lambda: _run_chat(job, agent, task))
    if background:
        threading.Thread(target=target, name=f"equalize-{job['id']}", daemon=True).start()
    else:
        target()
    return job


def work(agent_id: str) -> Dict[str, Any]:
    """The live view behind one agent: its latest job, or the tail of a Claude Code session."""
    _load_jobs()
    with _lock:
        jobs = sorted((j for j in _jobs.values() if j["agent"]["id"] == agent_id), key=lambda j: -j["started"])
    if jobs:
        return {"agent_id": agent_id, **jobs[0]}
    if agent_id.startswith("session:"):
        return _session_work(agent_id.split(":", 1)[1])
    return {"agent_id": agent_id, "steps": [], "status": "idle", "task": "", "work": "general"}


def job(job_id: str) -> Optional[Dict[str, Any]]:
    _load_jobs()
    with _lock:
        found = _jobs.get(job_id)
        return json.loads(json.dumps(found)) if found else None


def _session_work(session_id: str) -> Dict[str, Any]:
    """Steps from a Claude Code session already running on this PC (its transcript file, read-only)."""
    try:
        import claude_sessions

        path = next(claude_sessions.root().glob(f"*/{session_id}.jsonl"), None)
        entries = claude_sessions._lines(path, head=False) if path else []
    except Exception:  # noqa: BLE001
        entries = []
    fake = {"steps": [], "work": "general", "status": "running"}
    for entry in entries[-60:]:
        for part in ((entry.get("message") or {}).get("content") or []) if isinstance((entry.get("message") or {}).get("content"), list) else []:
            if isinstance(part, dict) and part.get("type") == "tool_use":
                step = step_from_tool(part.get("name", ""), part.get("input") or {})
                fake["steps"].append(step)
                if step["kind"] == "edit":
                    fake["work"] = "code"
    return {"agent_id": f"session:{session_id}", "task": "", "id": "", **fake, "steps": fake["steps"][-40:]}


def stop_job(job_id: str) -> bool:
    found = job(job_id)
    if not found or found["status"] != "running":
        return False
    pid = found.get("pid")
    if pid:
        try:
            import psutil

            psutil.Process(pid).kill()
        except Exception:  # noqa: BLE001
            pass
    with _lock:
        _jobs[job_id].update(status="stopped", ended=time.time())
        _save_jobs()
    return True


def drop_agent(agent_id: str, remove: bool = False) -> Dict[str, Any]:
    """An agent or avatar dragged into (or out of) the notch."""
    with _lock:
        state = _load()
        dropped = [d for d in state["dropped"] if d != agent_id]
        if not remove:
            dropped.append(agent_id)
        state["dropped"] = dropped[-8:]
        _save(_check(state))
    return settings()


# ---------------------------------------------------------------------------
# Files — the fast read
# ---------------------------------------------------------------------------

_MONEY = re.compile(r"(?<![\w.])(?:[$€£¥]\s?)?-?\d{1,3}(?:[,\s]\d{3})*(?:\.\d{2})(?![\d])|(?<![\w.])[$€£¥]\s?-?\d+(?:\.\d{1,2})?")
_CATEGORIES = {
    "Food": r"restaurant|cafe|coffee|starbucks|mcdonald|uber ?eats|doordash|grocer|supermarket|food|pizza|lunch|dinner",
    "Transport": r"uber|lyft|taxi|fuel|gas station|shell|bp|train|metro|parking|airline|flight",
    "Bills": r"rent|electric|water|internet|phone|utility|insurance|mortgage",
    "Shopping": r"amazon|store|shop|mall|clothing|target|walmart|ikea",
    "Subscriptions": r"netflix|spotify|subscription|apple\.com|google|adobe|prime|youtube",
    "Health": r"pharmacy|doctor|clinic|hospital|gym|fitness",
}


def _amount(text: str) -> Optional[float]:
    cleaned = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return None


def _category(text: str) -> str:
    low = text.lower()
    return next((name for name, pattern in _CATEGORIES.items() if re.search(pattern, low)), "Other")


def _money_rows(text: str, table: Optional[List[List[str]]] = None) -> List[Dict[str, Any]]:
    rows = []
    if table:
        header = [h.strip().lower() for h in table[0]] if table else []
        amount_col = next((i for i, h in enumerate(header) if re.search(r"amount|total|price|debit|cost|spent", h)), None)
        label_col = next((i for i, h in enumerate(header) if re.search(r"desc|merchant|name|payee|item|memo", h)), None)
        category_col = next((i for i, h in enumerate(header) if re.search(r"categ|type", h)), None)
        if amount_col is not None:
            for line in table[1:]:
                if amount_col >= len(line):
                    continue
                value = _amount(line[amount_col])
                if value is None:
                    continue
                label = line[label_col] if label_col is not None and label_col < len(line) else " ".join(line)[:60]
                category = line[category_col] if category_col is not None and category_col < len(line) else _category(label)
                rows.append({"label": label.strip()[:60], "amount": abs(value), "category": category.strip() or "Other"})
            return rows
    for line in text.splitlines():
        found = _MONEY.findall(line)
        if not found:
            continue
        value = _amount(found[-1])
        if value is None or abs(value) > 10_000_000:
            continue
        label = _MONEY.sub("", line).strip(" -:|\t")[:60] or "Item"
        rows.append({"label": label, "amount": abs(value), "category": _category(label)})
    return rows


def read_file(upload_id: str) -> Dict[str, Any]:
    """What a dropped file is and what matters in it, in milliseconds (no model). The chat answers deeper questions."""
    import uploads

    started = time.perf_counter()
    record = uploads.get_upload(upload_id)
    if record is None:
        raise ValueError("No such file.")
    path = Path(record.get("path") or "")
    name = str(record.get("name") or path.name)
    data = path.read_bytes() if path.is_file() else b""
    kind = str(record.get("kind") or uploads.kind_for(name, str(record.get("mime") or "")))
    text, table, facts = "", None, []
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv"):
        decoded = data.decode("utf-8-sig", errors="replace")
        table = list(csv.reader(io.StringIO(decoded), delimiter="\t" if suffix == ".tsv" else ","))[:20000]
        text = decoded
        facts.append(f"{max(0, len(table) - 1):,} rows · {len(table[0]) if table else 0} columns")
    elif kind == "image":
        facts.append("A picture — ask about it and Ichos will look at it")
    else:
        try:
            text = uploads.extract_document_text(data, name) or ""
        except Exception:  # noqa: BLE001 - an unreadable file still gets a card
            text = ""
        if text:
            facts.append(f"{len(text.split()):,} words")
    money = _money_rows(text, table)
    summary, report = "", None
    spending = len(money) >= 4 and (table is not None or re.search(r"spend|expense|transaction|statement|receipt|invoice|budget|total", text[:4000], re.I))
    if spending:
        total = sum(r["amount"] for r in money)
        by_category: Dict[str, float] = {}
        for row in money:
            by_category[row["category"]] = by_category.get(row["category"], 0.0) + row["amount"]
        top = sorted(money, key=lambda r: -r["amount"])[:3]
        report = {"total": round(total, 2), "count": len(money),
                  "categories": sorted(({"name": k, "amount": round(v, 2)} for k, v in by_category.items()),
                                       key=lambda c: -c["amount"])[:6],
                  "biggest": [{"label": r["label"], "amount": round(r["amount"], 2)} for r in top]}
        biggest = top[0]
        summary = (f"Spending report: {len(money)} items, {total:,.2f} in total. Biggest: {biggest['label']} "
                   f"({biggest['amount']:,.2f}). Most goes to {report['categories'][0]['name']}.")
    elif text:
        first = re.sub(r"\s+", " ", text).strip()
        summary = first[:220] + ("…" if len(first) > 220 else "")
    return {"upload_id": upload_id, "name": name, "kind": "spending" if spending else kind, "size": len(data),
            "facts": facts, "summary": summary, "report": report,
            "actions": ["ask", "email"] + (["summarize"] if text else []),
            "ms": round((time.perf_counter() - started) * 1000, 1)}


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def intent(text: str, has_file: bool = False) -> Dict[str, Any]:
    """What the owner wants done right now, when it is something the notch does itself."""
    text = str(text or "").strip()
    low = text.lower()
    seconds = parse_timer(text)
    if seconds:
        label = re.sub(r".*\bfor\b", "", low).strip() or "Timer"
        return {"action": "timer", "seconds": seconds, "label": label[:40]}
    if re.search(r"\b(send|email|e-mail|mail|forward)\b", low) and (has_file or re.search(r"\b(it|this|that|file|report|pdf|document)\b", low)):
        address = _EMAIL.search(text)
        subject = ""
        match = re.search(r"\b(?:subject|titled|called)\s+[\"“]?([^\"”]+)[\"”]?", text, re.I)
        if match:
            subject = match.group(1).strip()[:120]
        return {"action": "email", "to": address.group(0) if address else "", "subject": subject}
    return {"action": "chat"}


def send_mail(to: str, subject: str, body: str, upload_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Only ever called by the owner's own Send click in the notch."""
    import email_client
    import uploads

    files = []
    for upload_id in upload_ids or []:
        record = uploads.get_upload(upload_id)
        if record and Path(record.get("path") or "").is_file():
            files.append(str(record["path"]))
    return email_client.send_email(to, subject or "(no subject)", body or "", attachments=files)


# ---------------------------------------------------------------------------
# Voice, personality, avatar
# ---------------------------------------------------------------------------

_ACCENTS = {"british": "en-GB", "english accent": "en-GB", "uk": "en-GB", "australian": "en-AU", "aussie": "en-AU",
            "indian": "en-IN", "irish": "en-IE", "scottish": "en-GB", "canadian": "en-CA", "american": "en-US",
            "south african": "en-ZA", "new zealand": "en-NZ", "french": "fr-FR", "spanish": "es-ES", "german": "de-DE"}


def voice_from_description(description: str, voices: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """'a calm, deep British man' -> a neural voice plus rate and pitch. Words only; nothing is generated."""
    low = str(description or "").lower()
    gender = "Female" if re.search(r"\b(woman|female|girl|lady|her|she)\b", low) else \
        "Male" if re.search(r"\b(man|male|guy|boy|him|he|gentleman)\b", low) else ""
    locale = next((code for word, code in _ACCENTS.items() if word in low), "en-US")
    rate, pitch = 0, 0
    for word, (r, p) in {"calm": (-8, 0), "slow": (-15, 0), "relaxed": (-6, 0), "fast": (12, 0), "energetic": (10, 2),
                         "excited": (12, 4), "cheerful": (6, 3), "deep": (-4, -8), "low": (0, -6), "high": (0, 6),
                         "soft": (-5, 0), "warm": (-3, -2), "young": (4, 5), "old": (-8, -4), "robot": (0, -10)}.items():
        if word in low:
            rate, pitch = rate + r, pitch + p
    if voices is None:
        try:
            import tts

            voices = tts.neural_voices(locale)
        except Exception:  # noqa: BLE001
            voices = []
    pool = [v for v in voices if v.get("locale") == locale] or voices
    if gender:
        pool = [v for v in pool if v.get("gender") == gender] or pool
    wanted = [s for s in ("cheerful", "friendly", "calm", "warm", "excited") if s in low]
    pool.sort(key=lambda v: -sum(1 for s in v.get("styles") or [] if s.lower() in wanted))
    chosen = pool[0] if pool else {"id": "", "name": "Default"}
    return {"voice_id": chosen.get("id", ""), "name": chosen.get("name", ""), "locale": locale, "gender": gender,
            "rate": f"{max(-40, min(40, rate)):+d}%", "pitch": f"{max(-20, min(20, pitch)):+d}Hz"}


def set_voice(mode: str, description: str = "", sample: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Describe it, drop a voice file, or record one. A sample is matched by its pitch to the closest voice."""
    if mode == "described":
        picked = voice_from_description(description)
    elif mode in ("file", "recorded"):
        sample = sample or {}
        hz = float(sample.get("pitch_hz") or 0)
        gender = "male" if 0 < hz < 165 else "female" if hz >= 165 else ""
        picked = voice_from_description(f"{gender} {description}")
        if hz:
            target = 120 if gender == "male" else 210
            picked["pitch"] = f"{max(-20, min(20, round((hz - target) / 4))):+d}Hz"
        picked["sample"] = {"upload_id": str(sample.get("upload_id") or ""), "pitch_hz": round(hz, 1),
                            "seconds": round(float(sample.get("seconds") or 0), 1), "name": str(sample.get("name") or "")[:80]}
    else:
        picked = {"voice_id": "", "name": "", "rate": "+0%", "pitch": "+0Hz"}
    voice = {"mode": mode if mode in ("described", "file", "recorded") else "default", "description": description[:300],
             "voice_id": picked.get("voice_id", ""), "rate": picked.get("rate", "+0%"),
             "pitch": picked.get("pitch", "+0Hz"), "sample": picked.get("sample"), "name": picked.get("name", "")}
    if voice["voice_id"]:
        try:
            import tts

            tts.set_role_voice("reply", voice["voice_id"])
        except Exception:  # noqa: BLE001 - the choice is still saved
            pass
    with _lock:
        state = _load()
        state["voice"] = voice
        _save(_check(state))
    return voice


def set_avatar(name: str = "", image: str = "", avatar_id: str = "", personality: str = "",
               keep_personality: Optional[bool] = None) -> Dict[str, Any]:
    """A dropped avatar: a picture (upload id) or one of the owner's avatars. It comes with a personality; the owner
    keeps it or stays with the normal Ichos one."""
    if avatar_id:
        try:
            import avatars

            record = avatars.get(avatar_id.split(":", 1)[-1])
            if record:
                name = name or record.get("name", "")
                personality = personality or avatars.personality_text(record)
        except Exception:  # noqa: BLE001
            pass
    with _lock:
        state = _load()
        avatar = state["avatar"]
        if name or image or avatar_id:
            avatar.update(id=avatar_id, name=(name or "Io")[:40], image=image[:64])
            avatar["personality"] = (personality or "Warm, quick and curious; speaks plainly and kindly.")[:1200]
        if keep_personality is not None:
            avatar["keep_personality"] = bool(keep_personality)
            state["personality"]["source"] = "avatar" if keep_personality else (
                "custom" if state["personality"].get("text") else "normal")
        _save(_check(state))
    return settings()


def reset_avatar() -> Dict[str, Any]:
    with _lock:
        state = _load()
        state["avatar"] = dict(DEFAULTS["avatar"])
        if state["personality"]["source"] == "avatar":
            state["personality"]["source"] = "normal"
        _save(state)
    return settings()


def voice_personality() -> str:
    """Who answers when the owner talks out loud, while Equalize's "Talk: yes" is on.

    Spoken turns land in whatever chat the owner last used, so they took that chat's character instead of the one
    picked for Equalize (Fixer Upper S34: "make sure I can choose the avatar it uses"). The chosen avatar's
    personality, or the owner's own words, comes back here; "" leaves the chat's own personality alone.
    """
    state = _load()
    if not state.get("talk"):
        return ""
    source = state["personality"]["source"]
    if source == "avatar" and state["avatar"].get("personality"):
        return f"You are {state['avatar'].get('name') or 'Io'}. {state['avatar']['personality']}"
    if source == "custom" and state["personality"].get("text"):
        return state["personality"]["text"]
    return ""


def personality_note() -> str:
    """The guidance the chat adds for the notch's turns: the avatar's, the owner's own words, or nothing."""
    state = _load()
    source = state["personality"]["source"]
    if source == "avatar" and state["avatar"].get("personality"):
        return f"[Personality — {state['avatar']['name']}] {state['avatar']['personality']}"
    if source == "custom" and state["personality"].get("text"):
        return f"[Personality the owner asked for] {state['personality']['text']}"
    return ""
