"""Focus mode — *"It started by asking if they can shut everything down and only run this tab. After the tab
finishes everything else resumes automatically."*

Nyx runs a lot of work by itself: self-improvement, absorption, predictions, Big Kahuna's training jobs. An
office wants the machine. So the tab asks once, and if the owner says yes the office holds a **pause token** for
exactly as long as it is working, and releases it the moment the last job finishes — including when the job
fails, when the owner halts the office, and when the engine noticed the office has been sitting idle.

The pausing itself belongs to ``background_jobs`` (the module that knows every background job). This wrapper
exists so the office never depends on it: if that module is not installed yet, focus mode still "works" — it
simply reports that nothing was paused, which is the honest answer.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

#: How long a held token may survive with nothing running before it is released on its own.
IDLE_RELEASE_SECONDS = 600

#: Stands in for a real pause token when there is nothing on this install that knows how to pause anything.
NO_BACKGROUND_TOKEN = "no-background-jobs"

_lock = threading.RLock()
_state: Dict[str, Any] = {"token": "", "since": 0.0, "office_id": "", "reason": "", "paused": [], "kept": [],
                          "last_active": 0.0, "note": "", "pinned_by": ""}


def _module() -> Any:
    try:
        import background_jobs  # type: ignore

        return background_jobs
    except Exception:  # noqa: BLE001 - optional by contract
        return None


def available() -> bool:
    return _module() is not None


def status() -> Dict[str, Any]:
    """What is running, what focus mode would pause, and whether the office holds it right now."""
    module = _module()
    live: Dict[str, Any] = {}
    if module is not None:
        try:
            live = dict(module.status() or {})
        except Exception:  # noqa: BLE001
            live = {}
    with _lock:
        held = bool(_state["token"])
        return {
            "held": held,
            "available": module is not None,
            "office_id": _state["office_id"],
            "since": _state["since"],
            "reason": _state["reason"],
            "paused": list(_state["paused"]),
            "kept_running": list(_state["kept"]),
            "note": _state["note"],
            "pinned_by": _state["pinned_by"],
            "background": live,
        }


def enter(office_id: str, reason: str = "") -> Dict[str, Any]:
    """Pause Nyx's background work for this office. Safe to call again — one token is held at a time."""
    with _lock:
        if _state["token"]:
            _state["last_active"] = time.time()
            _state["office_id"] = office_id or _state["office_id"]
            return status()
    module = _module()
    token, paused, kept, note = "", [], [], ""
    if module is None:
        # Focus mode is still *on* — the owner asked for it and the office behaves accordingly (it takes the
        # bigger concurrency). It is simply honest about having found nothing to pause.
        token = NO_BACKGROUND_TOKEN
        note = ("Nyx's background work could not be paused from here yet (the background job list is not "
                "installed), so the office simply has the machine to itself.")
    else:
        try:
            token = str(module.pause_all(reason or f"Office Space: {office_id}", by="office") or "")
            info = module.status() or {}
            paused = [str(x) for x in (info.get("paused") or info.get("held") or [])][:20]
            kept = [str(x) for x in (info.get("not_paused") or info.get("kept_running") or [])][:20]
        except Exception as error:  # noqa: BLE001 - never let this stop an office starting
            note = f"Could not pause the background work ({type(error).__name__}); the office is sharing the machine."
    with _lock:
        _state.update(token=token, since=time.time(), office_id=office_id, reason=reason, paused=paused,
                      kept=kept, note=note, last_active=time.time())
    _announce(True)
    return status()


def pin(holder: str) -> None:
    """Keep the token across jobs: an AI Environment world runs one office job after another for hours, and the
    rest of Nyx must not wake up in the gaps (the owner: "All tasks shut down before this is run"). While pinned,
    only ``leave(force=True)`` — or :func:`unpin` followed by ``leave`` — lets go."""
    with _lock:
        _state["pinned_by"] = str(holder or "")


def unpin() -> None:
    with _lock:
        _state["pinned_by"] = ""


def pinned() -> str:
    with _lock:
        return str(_state["pinned_by"])


def leave(*, force: bool = False) -> Dict[str, Any]:
    """Let everything resume. Called when the office finishes, is halted, or has been idle too long."""
    with _lock:
        token = _state["token"]
        if not token and not force:
            return status()
        if _state["pinned_by"] and not force:
            _state["last_active"] = time.time()
            return status()
        _state.update(token="", since=0.0, office_id="", reason="", paused=[], kept=[], last_active=0.0,
                      pinned_by="")
    module = _module()
    if module is not None and token and token != NO_BACKGROUND_TOKEN:
        try:
            module.resume(token)
        except Exception:  # noqa: BLE001 - a token that cannot be resumed is the other module's problem to log
            pass
    _announce(False)
    return status()


def touch() -> None:
    """The office is still working — used by the idle watchdog."""
    with _lock:
        if _state["token"]:
            _state["last_active"] = time.time()


def release_if_idle(*, running: bool) -> bool:
    """Release a token that is being held with nothing to show for it. Returns True when it let go."""
    with _lock:
        if not _state["token"]:
            return False
        if running or _state["pinned_by"]:
            _state["last_active"] = time.time()
            return False
        idle_for = time.time() - float(_state["last_active"] or _state["since"] or time.time())
        if idle_for < IDLE_RELEASE_SECONDS:
            return False
    leave()
    return True


def held_by(office_id: str) -> bool:
    with _lock:
        return bool(_state["token"]) and _state["office_id"] == office_id


def _announce(on: bool) -> None:
    try:
        from agent_events import publish_ui

        publish_ui("office.focus", **status(), on=on)
    except Exception:  # noqa: BLE001
        pass


def reset_for_tests() -> None:
    with _lock:
        _state.update(token="", since=0.0, office_id="", reason="", paused=[], kept=[], last_active=0.0, note="",
                      pinned_by="")
