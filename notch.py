"""The desktop notch: the Equalize assistant at the top of the screen, outside the browser (owner, 2026-10-10:
"make sure it is separate from the chrome tab or the browser tab and instead can be on top of the screen like a notch
separated from apps"; 2026-10-11: "make it basically this exactly … the notch needs to look the exact same").

The window itself is ``notch_window.py`` — its own process (WebView2 through pywebview needs the main thread, which
the engine's server owns), showing ``/notch``. This module starts and stops it, keeps the voice state the app's page
reports (the notch reads it to animate Io and the sound notch), and carries the notch's "Back to chat" to the app.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

_state: Dict[str, Any] = {"state": "idle", "text": "", "voice": False, "at": 0.0}
_process: Optional[subprocess.Popen] = None
_lock = threading.Lock()

WORDS = {"idle": "Ichos", "listening": "Listening…", "thinking": "Thinking…", "speaking": "Speaking"}


def set_state(state: str, text: str = "", voice: bool = False) -> None:
    with _lock:
        _state.update(state=state if state in WORDS else "idle", text=str(text or "")[:160], voice=bool(voice),
                      at=time.time())


def running() -> bool:
    return _process is not None and _process.poll() is None


def status() -> Dict[str, Any]:
    with _lock:
        return {"running": running(), **_state}


def _python() -> str:
    """pythonw beside the running interpreter, so no console window opens (and it is signed — Smart App Control)."""
    exe = Path(sys.executable)
    windowless = exe.with_name("pythonw.exe")
    return str(windowless if windowless.is_file() else exe)


def _owner_token() -> str:
    """A session for the window when the engine starts it by itself (no page asked)."""
    try:
        from server_auth import AUTH_STORE, is_claimed

        if not is_claimed():
            return ""
        owner = next((u for u in AUTH_STORE.users.values() if getattr(u.role, "value", u.role) == "owner"), None)
        return AUTH_STORE._issue_session(owner.email) if owner is not None else ""
    except Exception:  # noqa: BLE001
        return ""


def start(token: str = "", port: Optional[int] = None) -> Dict[str, Any]:
    """Open the notch window (once). ``token`` is the session of whoever turned it on."""
    global _process
    with _lock:
        if running():
            return {"running": True, **_state}
        port = port or int(os.environ.get("NYX_PORT", "8000"))
        env = dict(os.environ, ICHOS_NOTCH_TOKEN=token or _owner_token())
        script = Path(__file__).resolve().with_name("notch_window.py")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        _process = subprocess.Popen([_python(), str(script), f"http://127.0.0.1:{port}/notch"], env=env,
                                    cwd=str(script.parent), creationflags=flags)
    _remember(True)
    return status()


def stop() -> Dict[str, Any]:
    global _process
    with _lock:
        if running():
            _process.terminate()
            try:
                _process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                _process.kill()
        _process = None
    _remember(False)
    return status()


def _remember(on: bool) -> None:
    try:
        import equalize_assistant

        settings = equalize_assistant.settings()
        if settings["notch"]["enabled"] != on:
            equalize_assistant.update({"notch": {**settings["notch"], "enabled": on}})
    except Exception:  # noqa: BLE001
        pass


def start_if_enabled() -> None:
    """At engine start: bring the notch back if the owner left it on."""
    try:
        import equalize_assistant

        if equalize_assistant.settings()["notch"]["enabled"] and sys.platform == "win32":
            threading.Timer(4.0, start).start()
    except Exception:  # noqa: BLE001
        pass


def open_app(tab: str = "chat") -> Dict[str, Any]:
    """Back to chat / Open Equalize: an open app page switches tab; with none open, a browser opens on the app."""
    tab = str(tab or "chat")[:40]
    listening = 0
    try:
        from agent_events import BUS, publish_ui

        listening = BUS.subscriber_count("ui")
        publish_ui("notch.open-tab", tab=tab)
    except Exception:  # noqa: BLE001
        pass
    if not listening:
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{os.environ.get('NYX_PORT', '8000')}/app")
    return {"ok": True, "tab": tab, "page_open": bool(listening)}


# ── What is waiting on the owner: the notch pops open for it ──────────────────
# Fixer Upper (WS7, left open by the rebuild): "agents' approvals and questions don't pop the notch open yet";
# Drive document 1: "when a question card or approval is waiting, pop the notch open".

QUESTION_WINDOW_S = 6 * 3600  # a question older than this is not news any more


def open_questions(store: Any = None, now: Optional[float] = None) -> list:
    """Chats whose last word is a question card from the assistant, not answered yet (newest first)."""
    from datetime import datetime

    import question_cards

    if store is None:
        from server import _shared_chat_store

        store = _shared_chat_store()
    now = time.time() if now is None else now
    items = []
    for chat in store.summaries()[:30]:
        try:
            when = datetime.fromisoformat(str(chat.get("updated_at") or "")).timestamp()
        except ValueError:
            continue
        if now - when > QUESTION_WINDOW_S:
            break  # summaries are newest first
        messages = [m for m in store.messages(chat["id"]) if m.get("role") in ("user", "assistant")]
        if not messages or messages[-1]["role"] != "assistant":
            continue
        cards = question_cards.find_all(str(messages[-1].get("content") or ""))
        if not cards:
            continue
        card = cards[0]
        items.append({"kind": "question", "id": f"q:{chat['id']}:{len(messages)}", "title": card["question"],
                      "detail": str(chat.get("title") or ""), "where": "chat", "chat_id": chat["id"], "since": when,
                      "card": card})
    return items


def waiting(store: Any = None, now: Optional[float] = None) -> list:
    """Approvals, trades and Claude Code sessions that need the owner, plus unanswered question cards. Never raises."""
    items: list = []
    try:
        from routes_equalize import needs_you

        items.extend(needs_you())
    except Exception:  # noqa: BLE001
        pass
    try:
        items.extend(open_questions(store, now))
    except Exception:  # noqa: BLE001
        pass
    return sorted(items, key=lambda i: -float(i.get("since") or 0))
