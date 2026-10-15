"""User hooks, like Claude Code's: your own commands that run when something happens in a chat (Drive doc 1, 1.29).

Each hook names an event, an optional tool pattern, and a command. The command gets the event as JSON on stdin.

* ``before_tool``: runs before a matching tool. Exit code 2 stops the tool, and what the command printed to
  stderr is the reason the AI is given.
* ``after_tool``: runs after a matching tool, in the background. Its output is only logged.
* ``prompt``: runs when you send a message. What it prints to stdout is added to that turn as context.
* ``reply_done``: runs in the background when a reply has finished.

Only the owner can add hooks (the routes are owner-only), every command runs with no console window, and a hook
that fails or times out never breaks a chat: it is logged and skipped.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import subprocess
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from paths import data_path

EVENTS = ("before_tool", "after_tool", "prompt", "reply_done")
BLOCK_EXIT = 2
MAX_TIMEOUT = 60
MAX_CONTEXT_CHARS = 2000
_LOG = logging.getLogger("nyx.user_hooks")
_LOCK = threading.Lock()
_RECENT: List[Dict[str, Any]] = []


def _path():
    return data_path("user_hooks.json")


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: Dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def enabled() -> bool:
    return bool(_load().get("enabled", True))


def set_enabled(on: bool) -> None:
    with _LOCK:
        data = _load()
        data["enabled"] = bool(on)
        _save(data)


def list_hooks() -> List[Dict[str, Any]]:
    return [h for h in _load().get("hooks", []) if isinstance(h, dict)]


def add_hook(event: str, command: str, match: str = "*", timeout: int = 10, name: str = "") -> Dict[str, Any]:
    if event not in EVENTS:
        raise ValueError(f"Event must be one of: {', '.join(EVENTS)}")
    command = (command or "").strip()
    if not command:
        raise ValueError("A hook needs a command to run.")
    hook = {
        "id": "hook_" + uuid.uuid4().hex[:8], "name": (name or "").strip()[:60], "event": event,
        "match": (match or "*").strip() or "*", "command": command,
        "timeout": max(1, min(int(timeout or 10), MAX_TIMEOUT)), "enabled": True,
    }
    with _LOCK:
        data = _load()
        data.setdefault("hooks", []).append(hook)
        _save(data)
    return hook


def update_hook(hook_id: str, **changes: Any) -> Optional[Dict[str, Any]]:
    with _LOCK:
        data = _load()
        for hook in data.get("hooks", []):
            if hook.get("id") != hook_id:
                continue
            if "enabled" in changes and changes["enabled"] is not None:
                hook["enabled"] = bool(changes["enabled"])
            for key in ("name", "match", "command"):
                if changes.get(key) is not None:
                    hook[key] = str(changes[key]).strip() or hook[key]
            if changes.get("timeout") is not None:
                hook["timeout"] = max(1, min(int(changes["timeout"]), MAX_TIMEOUT))
            _save(data)
            return hook
    return None


def remove_hook(hook_id: str) -> bool:
    with _LOCK:
        data = _load()
        hooks = data.get("hooks", [])
        kept = [h for h in hooks if h.get("id") != hook_id]
        if len(kept) == len(hooks):
            return False
        data["hooks"] = kept
        _save(data)
    return True


def recent(limit: int = 20) -> List[Dict[str, Any]]:
    return list(reversed(_RECENT[-limit:]))


def _matching(event: str, tool: str = "") -> List[Dict[str, Any]]:
    if not enabled():
        return []
    found = []
    for hook in list_hooks():
        if hook.get("event") != event or not hook.get("enabled", True):
            continue
        if tool and not fnmatch.fnmatch(tool, hook.get("match") or "*"):
            continue
        found.append(hook)
    return found


def _run(hook: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    import quiet_windows

    started = time.perf_counter()
    outcome: Dict[str, Any] = {"hook": hook.get("id"), "name": hook.get("name") or hook.get("command", "")[:40],
                               "event": hook.get("event"), "at": time.time()}
    try:
        done = subprocess.run(
            hook["command"], shell=True, input=json.dumps(payload, default=str), capture_output=True, text=True,
            timeout=int(hook.get("timeout") or 10), **quiet_windows.popen_kwargs(),
        )
        outcome.update(code=done.returncode, stdout=(done.stdout or "")[:MAX_CONTEXT_CHARS],
                       stderr=(done.stderr or "")[:500])
    except subprocess.TimeoutExpired:
        outcome.update(code=None, stdout="", stderr="timed out")
    except Exception as error:  # noqa: BLE001 - a broken hook is logged, never raised into a chat
        outcome.update(code=None, stdout="", stderr=str(error)[:500])
    outcome["ms"] = round((time.perf_counter() - started) * 1000)
    _RECENT.append({k: v for k, v in outcome.items() if k != "stdout"})
    del _RECENT[:-50]
    if outcome.get("code") not in (0, BLOCK_EXIT):
        _LOG.info("hook %s failed: %s", outcome["name"], outcome.get("stderr"))
    return outcome


def before_tool(tool: str, category: str, args: Dict[str, Any], chat_id: str = "") -> Optional[str]:
    """The reason to stop this tool, or None. Only exit code 2 stops it."""
    for hook in _matching("before_tool", tool):
        outcome = _run(hook, {"event": "before_tool", "tool": tool, "category": category, "args": args,
                              "chat_id": chat_id})
        if outcome.get("code") == BLOCK_EXIT:
            reason = (outcome.get("stderr") or outcome.get("stdout") or "").strip()
            return f"Blocked by your hook \"{outcome['name']}\"" + (f": {reason}" if reason else ".")
    return None


def _in_background(event: str, payload: Dict[str, Any], tool: str = "") -> None:
    hooks = _matching(event, tool)
    if not hooks:
        return
    threading.Thread(target=lambda: [_run(h, payload) for h in hooks], daemon=True, name=f"hook-{event}").start()


def after_tool(tool: str, category: str, args: Dict[str, Any], ok: bool, result: str, chat_id: str = "") -> None:
    _in_background("after_tool", {"event": "after_tool", "tool": tool, "category": category, "args": args,
                                  "ok": ok, "result": (result or "")[:4000], "chat_id": chat_id}, tool)


def reply_done(chat_id: str, message: str, reply: str) -> None:
    _in_background("reply_done", {"event": "reply_done", "chat_id": chat_id, "message": message[:4000],
                                   "reply": (reply or "")[:8000]})


def prompt_context(message: str, chat_id: str = "") -> str:
    """What the prompt hooks printed, to add to this turn. Empty when none ran or none printed."""
    notes = []
    for hook in _matching("prompt"):
        outcome = _run(hook, {"event": "prompt", "message": message, "chat_id": chat_id})
        text = (outcome.get("stdout") or "").strip()
        if outcome.get("code") == 0 and text:
            notes.append(text)
    return "\n".join(notes)[:MAX_CONTEXT_CHARS]
