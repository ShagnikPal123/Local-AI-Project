"""Who Identity 0 can work with right now: every model that is up, allowed and not itself.

A *member* is one provider + model: ``ollama:qwen3.5:9b``, ``nvidia:<default>``, ``gemini:<default>``,
``self:<version>`` (Identity 0's own model, once one is trained and served). Discovery reads the
router's own availability and consent rules, so Identity 0 can never reach a model the router would
refuse — in particular it never starts spending on a paid key the owner did not pick (Request H11).

The list is cached for a few seconds: it is read on every turn, and each probe it wraps is cheap
only because the providers cache theirs.
"""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import identity0

_CACHE_SECONDS = 5.0
_cache: Dict[int, tuple] = {}
_lock = threading.Lock()
_last_autostart = 0.0
_vision_cache: Dict[str, tuple] = {}


@dataclass(frozen=True)
class Member:
    id: str
    provider: str
    model: str
    local: bool
    free: bool
    vision: bool
    label: str

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def member_id(provider: str, model: str = "") -> str:
    return f"{provider}:{model or 'default'}"


def split_id(member: str) -> tuple:
    provider, _, model = (member or "").partition(":")
    return provider, ("" if model == "default" else model)


def _ollama_info(model: str) -> Dict[str, Any]:
    """``/api/show`` facts for an installed model (vision, parent), cached 10 min; unknown → empty."""
    hit = _vision_cache.get(model)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    info: Dict[str, Any] = {}
    try:
        import requests
        import local_models

        response = requests.post(local_models.host() + "/api/show", json={"model": model}, timeout=1.5)
        data = response.json()
        info = {"vision": "vision" in (data.get("capabilities") or []),
                "parent": str((data.get("details") or {}).get("parent_model") or "")}
    except Exception:  # noqa: BLE001 - unknown means "no", never an error
        info = {}
    _vision_cache[model] = (time.time(), info)
    return info


def _ollama_vision(model: str) -> bool:
    return bool(_ollama_info(model).get("vision"))


def maybe_start_ollama() -> bool:
    """Start the installed Ollama service when it is down (at most every 5 minutes, never blocking).

    The owner installed Ollama so Identity 0 can work alongside it; a reboot that leaves the service
    stopped should not quietly turn Big Kahuna into an online-only brain.
    """
    global _last_autostart
    try:
        from identity0.state import get_settings

        if not get_settings().get("ollama_autostart", True) or time.time() - _last_autostart < 300:
            return False
        import local_models

        exe = local_models.ollama_exe()
        if not exe or local_models.running():
            return False
        _last_autostart = time.time()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, creationflags=flags)
        return True
    except Exception:  # noqa: BLE001
        return False


_last_warm = 0.0


def warm_local(keep_minutes: int = 20) -> Dict[str, Any]:
    """Load the local models into VRAM now and keep them there, so the next spoken turn is not the slow one.

    A model Ollama has unloaded costs about three minutes to load again — measured on this PC. That is
    fine for a typed question and useless for "open Gmail and write this", so whoever knows the owner is
    about to talk (the voice bar, the companion, the engine starting) calls this first. It never blocks.
    """
    global _last_warm
    if time.time() - _last_warm < 60:
        return {"warming": False, "reason": "warmed a moment ago"}
    _last_warm = time.time()

    def work() -> None:
        try:
            maybe_start_ollama()
            import requests
            import local_models
            from config import SETTINGS

            model = str(getattr(SETTINGS, "ollama_model", "") or "")
            if model and local_models.running():
                # num_predict 0 loads the weights without generating; keep_alive holds them there.
                requests.post(local_models.host() + "/api/chat", timeout=300, json={
                    "model": model, "messages": [{"role": "user", "content": "hi"}], "stream": False,
                    "think": False, "keep_alive": f"{max(1, int(keep_minutes))}m",
                    "options": {"num_predict": 0}})
        except Exception:  # noqa: BLE001 - warming up is a bonus, never an error
            pass
        try:
            from identity0.model import client

            if client.current() is not None:
                client.ensure_started()
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=work, name="kahuna-warm", daemon=True).start()
    return {"warming": True}


def _own_member() -> Optional[Member]:
    try:
        from identity0.model import client  # imports without torch by contract

        ready = client.is_ready()
        if not ready and client.current() is not None:
            client.ensure_started()  # a promoted version exists: bring it online (at most once a minute)
        info = client.current() if ready else None
    except Exception:  # noqa: BLE001 - no own model yet is the normal case
        info = None
    if not info:
        return None
    version = str(info.get("version") or "v0")
    return Member(member_id("self", version), "self", version, True, True, False,
                  f"{identity0.NAME} own model ({version})")


def discover(router: Any) -> List[Member]:
    """Uncached discovery; ``available`` is what callers use."""
    from config import SETTINGS

    found: List[Member] = []
    providers = getattr(router, "providers", {}) or {}
    # Billable providers join only when they are the owner's own current pick: an old pick is
    # consent for the router to use that key when asked, not for Identity 0 to spend on shadows.
    try:
        import router as router_module

        paid = set(router_module._PAID_PROVIDERS) | {
            n for n, p in (getattr(router, "custom", {}) or {}).items() if not getattr(p, "is_free", False)}
    except Exception:  # noqa: BLE001
        paid = set()
    try:
        import model_choice

        picked = str(model_choice.load().get("provider") or "")
    except Exception:  # noqa: BLE001
        picked = ""
    paid.discard(picked)
    for name, provider in providers.items():
        if name == identity0.PROVIDER_ID:
            continue
        try:
            reason = router.unavailable_reason(name)
        except Exception:  # noqa: BLE001
            reason = "unknown"
        if name == "ollama":
            if reason:
                maybe_start_ollama()
                continue
            try:
                models = [m for m in provider.list_models() if m and "embed" not in m.lower()]
            except Exception:  # noqa: BLE001
                models = []
            # A model built on another installed one (Data Absorption's "nyx-absorbed" is qwen3.5 plus
            # a system prompt) is the same weights: switching between them only makes Ollama reload.
            configured = str(getattr(SETTINGS, "ollama_model", "") or "")
            models = [m for m in models if m == configured or _ollama_info(m).get("parent", "") not in models]
            models.sort(key=lambda m: 0 if m == configured else 1)
            for model in models:
                found.append(Member(member_id("ollama", model), "ollama", model, True, True,
                                    _ollama_vision(model), f"{model} (local)"))
            continue
        if reason or name in paid:
            continue
        model = str(getattr(SETTINGS, f"{name}_model", "") or "")
        label = getattr(provider, "label", "") or name
        found.append(Member(member_id(name, model), name, model, False, name not in paid,
                            bool(getattr(provider, "supports_vision", False)), str(label)))
    own = _own_member()
    if own is not None:
        found.insert(0, own)
    return found


def available(router: Any, *, refresh: bool = False) -> List[Member]:
    key = id(router)
    with _lock:
        hit = _cache.get(key)
        if hit and not refresh and time.time() - hit[0] < _CACHE_SECONDS:
            return list(hit[1])
    members = discover(router)
    with _lock:
        _cache[key] = (time.time(), members)
    return list(members)


def forget_cache() -> None:
    with _lock:
        _cache.clear()
