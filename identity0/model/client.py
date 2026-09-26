"""Talk to Identity 0's own model from the app — over HTTP to its serve process, never importing torch.

The serve process (``python -m identity0.model.serve``) holds the weights on the GPU and speaks the
OpenAI chat-completions shape on 127.0.0.1:11500. ``is_ready`` is cached a few seconds because Big
Kahuna asks on every turn; ``ensure_started`` launches the process when a promoted version exists.

"Ready" means *the promoted version* is being served. Promoting a newer one while an older one is up
used to change nothing until the old process idled out an hour later, so ``ensure_started`` now asks
the old one to stop and brings the new one up.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

PORT = int(os.environ.get("KAHUNA_MODEL_PORT", "11500"))
URL = f"http://127.0.0.1:{PORT}"
_ready_cache: Dict[str, Any] = {"at": 0.0, "ok": False, "info": None}
_lock = threading.Lock()
_last_start = 0.0


def current() -> Optional[Dict[str, Any]]:
    from identity0.model import registry

    entry = registry.current()
    if entry is None:
        return None
    info = dict(entry)
    info["ready"] = is_ready()
    info["endpoint"] = URL
    return info


def _health(timeout: float = 0.4) -> Optional[Dict[str, Any]]:
    import requests

    try:
        response = requests.get(URL + "/health", timeout=timeout)
        return response.json() if response.ok else None
    except Exception:  # noqa: BLE001 - not running is the common case
        return None


def served() -> Optional[Dict[str, Any]]:
    """What the serve process says it is holding right now (``None`` when nothing is up)."""
    is_ready()
    with _lock:
        return _ready_cache.get("info")


def is_ready() -> bool:
    with _lock:
        if time.time() - _ready_cache["at"] < 5:
            return bool(_ready_cache["ok"])
    info = _health()
    with _lock:
        _ready_cache.update(at=time.time(), ok=bool(info and info.get("ok")), info=info)
    return bool(info and info.get("ok"))


def stop(timeout: float = 5.0) -> bool:
    """Ask the serve process to exit (loopback only, its own endpoint)."""
    import requests

    try:
        requests.post(URL + "/shutdown", timeout=timeout)
    except Exception:  # noqa: BLE001 - already gone is a fine outcome
        pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        forget()
        if not is_ready():
            return True
        time.sleep(0.4)
    return False


def forget() -> None:
    with _lock:
        _ready_cache["at"] = 0.0


def ensure_started() -> Dict[str, Any]:
    """Serve the promoted version: start it, or swap it in when an older one is up (at most once a minute)."""
    global _last_start
    from identity0.model import registry

    entry = registry.current()
    if entry is None:
        return {"ok": False, "error": "No version of the own model is promoted yet."}
    if is_ready():
        running = (served() or {}).get("version") or ""
        if running == entry["version"]:
            return {"ok": True, "started": False}
        if time.time() - _last_start < 60:
            return {"ok": False, "error": "Switching…"}
        stop()  # an older version is up: hand the GPU over to the promoted one
    if time.time() - _last_start < 60:
        return {"ok": False, "error": "Starting…"}
    _last_start = time.time()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    project = Path(__file__).resolve().parents[2]
    subprocess.Popen([sys.executable, "-m", "identity0.model.serve", "--dir", entry["path"], "--port", str(PORT),
                      "--version", entry["version"]], cwd=str(project), stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=flags)
    forget()
    return {"ok": True, "started": True}


def stream_chat(messages: List[Dict[str, Any]], *, max_tokens: int = 512, temperature: float = 0.7,
                cancelled=None) -> Iterator[str]:
    import requests

    body = {"messages": [{"role": m.get("role", "user"), "content": str(m.get("content", ""))} for m in messages],
            "stream": True, "max_tokens": max_tokens, "temperature": temperature}
    with requests.post(URL + "/v1/chat/completions", json=body, stream=True, timeout=(3, 120)) as response:
        response.raise_for_status()
        response.encoding = "utf-8"
        for line in response.iter_lines(decode_unicode=True):
            if cancelled is not None and cancelled():
                return
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                return
            try:
                delta = json.loads(payload)["choices"][0].get("delta", {}).get("content")
            except (ValueError, KeyError, IndexError):
                continue
            if delta:
                yield delta


def complete(messages: List[Dict[str, Any]], **kwargs: Any) -> str:
    return "".join(stream_chat(messages, **kwargs))
