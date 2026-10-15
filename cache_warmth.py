"""Is the local model still loaded? The "warm 3:12 / cold" chip in the chat (doc 2 item 2.3, the mod's cache tax).

Ollama keeps a model in memory for 5 minutes after its last answer (its keep_alive), then unloads it, and the next
answer pays the load time again (seconds to a minute on a big model). This notes when Ollama last answered and
says how long the model stays warm. Optional keep-warm (off by default, free because it is local) pings Ollama
every 4 minutes so the model never unloads while Ichos is running.

Cloud providers are not shown: Ichos sends them no prompt-cache marks, so there is no warmth to count.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Dict, Optional

from paths import data_path

TTL_SECONDS = 300          # Ollama's default keep_alive
PING_EVERY = 240           # inside the TTL, so the model never unloads
SETTINGS_FILE = "cache_warmth.json"

_lock = threading.Lock()
_last: Dict[str, float] = {}       # provider -> time of its last successful answer
_keeper: Optional[threading.Thread] = None


def note(provider: str, success: bool = True, now: Optional[float] = None) -> None:
    """Called for every model answer (metrics.record). Only Ollama is kept."""
    if not success or (provider or "").lower() != "ollama":
        return
    with _lock:
        _last["ollama"] = now if now is not None else time.time()


def keep_warm() -> bool:
    try:
        return bool(json.loads(data_path(SETTINGS_FILE).read_text(encoding="utf-8")).get("keep_warm", False))
    except (OSError, ValueError, AttributeError):
        return False


def set_keep_warm(on: bool) -> bool:
    data_path(SETTINGS_FILE).write_text(json.dumps({"keep_warm": bool(on)}), encoding="utf-8")
    if on:
        ensure_keeper()
    return bool(on)


def state(now: Optional[float] = None) -> Dict[str, Any]:
    """{"ollama": {"warm": bool, "seconds_left": int, "model": str}, "keep_warm": bool}."""
    now = now if now is not None else time.time()
    with _lock:
        last = _last.get("ollama")
    left = max(0, int(TTL_SECONDS - (now - last))) if last else 0
    try:
        from config import SETTINGS

        model = str(getattr(SETTINGS, "ollama_model", "") or "")
    except Exception:  # noqa: BLE001
        model = ""
    return {"ollama": {"warm": left > 0, "seconds_left": left, "used": last is not None, "model": model},
            "keep_warm": keep_warm(), "ttl_seconds": TTL_SECONDS}


def _ping(post: Optional[Callable[..., Any]] = None) -> bool:
    """Ask Ollama to keep the model loaded (an empty generate with keep_alive). Returns True when it answered."""
    try:
        import requests

        from config import SETTINGS

        model = str(getattr(SETTINGS, "ollama_model", "") or "")
        if not model:
            return False
        host = (SETTINGS.ollama_host or "http://127.0.0.1:11434").replace("//localhost:", "//127.0.0.1:")
        response = (post or requests.post)(f"{host}/api/generate", json={"model": model, "keep_alive": "5m"}, timeout=30)
        ok = getattr(response, "status_code", 500) < 400
        if ok:
            note("ollama")
        return ok
    except Exception:  # noqa: BLE001 - a missed ping only means the next answer loads the model
        return False


def _loop() -> None:
    while keep_warm():
        _ping()
        time.sleep(PING_EVERY)


def ensure_keeper() -> None:
    """Start the keep-warm pinger once, if the setting is on. It stops by itself when switched off."""
    global _keeper
    if not keep_warm():
        return
    with _lock:
        if _keeper is not None and _keeper.is_alive():
            return
        _keeper = threading.Thread(target=_loop, name="ollama-keep-warm", daemon=True)
        _keeper.start()
