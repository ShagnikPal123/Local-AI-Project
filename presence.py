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
# What the owner last dragged onto a tab or app (S23): the assistant reads it so "help me with this" has an object.
_DROP_KINDS = {"avatar", "chat", "assistant", "agent", "calendar", "item"}
_DROP_MAX_AGE = 300.0
_drop: Dict[str, Any] = {}


def mark_active(source: str = "input", tab: str = "", now: Optional[float] = None) -> None:
    with _lock:
        _state["last_active"] = now if now is not None else time.time()
        _state["source"] = source[:40]
        if tab:
            _state["tab"] = tab[:60]


def note_drop(kind: str, item_id: str, label: str, tab: str = "", now: Optional[float] = None) -> Dict[str, Any]:
    """Remember the latest drag-and-drop. Values are trimmed and the kind is from a fixed list: this text goes into a prompt."""
    clean = {"kind": kind if kind in _DROP_KINDS else "item", "id": " ".join(str(item_id).split())[:80],
             "label": " ".join(str(label).split())[:80], "tab": " ".join(str(tab).split())[:60],
             "at": now if now is not None else time.time()}
    with _lock:
        _drop.clear()
        _drop.update(clean)
    mark_active("drop", tab=clean["tab"], now=now)
    return clean


def recent_drop(now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """The last drop if it was within five minutes, else None (an old drop no longer says what they want)."""
    with _lock:
        drop = dict(_drop)
    if not drop or ((now if now is not None else time.time()) - drop["at"]) > _DROP_MAX_AGE:
        return None
    return drop


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
        _drop.clear()
