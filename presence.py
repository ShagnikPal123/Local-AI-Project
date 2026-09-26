"""Is the owner here right now? One clock for "active" vs "away".

Fed by chat turns (``routes_live``) and by the web UI's heartbeat on real input
(``POST /api/presence``, throttled client-side). Read by the improvement
autopilot ("only work while I'm away"), the idle tab suggester, and the detox hour.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

_lock = threading.Lock()
_state: Dict[str, Any] = {"last_active": 0.0, "source": "", "tab": ""}


def mark_active(source: str = "input", tab: str = "", now: Optional[float] = None) -> None:
    with _lock:
        _state["last_active"] = now if now is not None else time.time()
        _state["source"] = source[:40]
        if tab:
            _state["tab"] = tab[:60]


def idle_seconds(now: Optional[float] = None) -> float:
    """Seconds since the owner last did anything; a large number if never seen this run."""
    with _lock:
        last = _state["last_active"]
    if not last:
        return 10 ** 9
    return max(0.0, (now if now is not None else time.time()) - last)


def snapshot(now: Optional[float] = None) -> Dict[str, Any]:
    with _lock:
        state = dict(_state)
    idle = idle_seconds(now)
    return {"last_active": state["last_active"] or None, "idle_seconds": None if idle >= 10 ** 9 else round(idle, 1),
            "source": state["source"], "tab": state["tab"]}


def reset() -> None:
    with _lock:
        _state.update(last_active=0.0, source="", tab="")
