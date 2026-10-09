"""How big an office this computer can hold, and which model each agent thinks with.

*"In here it can range from 10 to hundreds of agents depending on task and computer ability … Multiple models
(basically all of them) are used here and each agent uses one."*

Two separate numbers, because they are not the same thing:

* **head count** — how many agents may exist. An agent that is waiting costs a few kilobytes, so this can be in
  the hundreds even on a laptop.
* **concurrency** — how many of them may be thinking at the same moment. That is bounded by the Power setting
  (``resource_governor``), and per provider on top, because five agents calling one free API key at once is how
  you turn a working office into a wall of 429s.

Who gets which model is Big Kahuna's call: ``identity0.api.best_models`` ranks the members it has learned about
for a domain, and casting spreads agents across that ranking — best models get more desks, but every model that
is up gets used, which is what the owner asked for. If Identity 0 is not available the router's own list of
working providers is used instead, so an office still opens on a machine that has only Ollama.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from office import MAX_AGENTS, MIN_AGENTS

#: How many calls one provider may have in flight at once.
_PROVIDER_SLOTS = {"ollama": 2, "self": 1, "identity0": 2}
_DEFAULT_SLOTS = 3

_lock = threading.RLock()
_members_cache: Dict[str, Any] = {"at": 0.0, "rows": []}
_MEMBER_CACHE_SECONDS = 20.0


@dataclass
class Capacity:
    agents: int
    concurrency: int
    members: int
    reason: str = ""
    focus: bool = False
    power: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"agents": self.agents, "concurrency": self.concurrency, "members": self.members,
                "reason": self.reason, "focus": self.focus, "power": self.power}


def _device() -> Any:
    try:
        from device_profile import get_device_profile

        return get_device_profile()
    except Exception:  # noqa: BLE001 - an unreadable machine is treated as a small one
        return None


def capacity(*, focus: bool = False, member_count: Optional[int] = None) -> Capacity:
    """What this machine will allow right now, in words the tab can show."""
    try:
        from resource_governor import GOVERNOR

        ceiling = GOVERNOR.ceiling()
        workers, power = int(ceiling.max_workers), str(ceiling.mode.value)
    except Exception:  # noqa: BLE001
        workers, power = 2, "unknown"
    device = _device()
    ram = float(getattr(device, "ram_gb", 8) or 8)
    concurrency = max(2, min(12, workers + (workers // 2 if focus else 0)))
    if member_count is None:
        member_count = len(members())
    head = int(concurrency * 30 + ram + 10 * max(1, member_count))
    head = max(MIN_AGENTS, min(MAX_AGENTS, head))
    reason = (f"{concurrency} agents can think at once on this computer ({power} power"
              f"{', with the rest of Nyx paused' if focus else ''}), "
              f"and up to {head} can be on the floor at once with {member_count} model"
              f"{'s' if member_count != 1 else ''} to share between them.")
    return Capacity(agents=head, concurrency=concurrency, members=member_count, reason=reason, focus=focus,
                    power=power)


MAX_PARALLEL_OFFICES = 4


def parallel_offices() -> Tuple[int, str]:
    """How many offices may work at once here (UPDATE_IDEAS U14: "run multiple offices at once … on high end machines").

    Only a machine in the top worker class (32 GB+ of memory and a 12 GB+ graphics card — ``max_workers`` 8) runs
    more than one by itself, because two offices on a smaller one would each be slower than one alone. The owner can
    choose a number in the office settings; that is their call and is said so.
    """
    from office import settings as settings_module

    device = _device()
    workers = int(getattr(device, "max_workers", 2) or 2) if device is not None else 2
    auto = 3 if workers >= 8 else 1
    chosen = int(settings_module.load().get("parallel_offices") or 0)
    if chosen:
        n = max(1, min(MAX_PARALLEL_OFFICES, chosen))
        return n, f"you set {n} office{'s' if n != 1 else ''} at once"
    if auto > 1:
        return auto, f"this is a high-end PC, so {auto} offices can work at once"
    return 1, "this PC runs one office at a time; a high-end one runs up to three"


# ---------------------------------------------------------------------------
# Who is available to think
# ---------------------------------------------------------------------------


def _router_members(router: Any) -> List[Dict[str, Any]]:
    """Fallback discovery when Identity 0 is not there: whatever the router says is up."""
    rows: List[Dict[str, Any]] = []
    providers = getattr(router, "providers", {}) or {}
    for name, provider in providers.items():
        if name == "identity0":
            continue
        try:
            if router.unavailable_reason(name):
                continue
        except Exception:  # noqa: BLE001
            continue
        if name == "ollama":
            try:
                models = [m for m in provider.list_models() if m and "embed" not in m.lower()][:6]
            except Exception:  # noqa: BLE001
                models = []
            for model in models:
                rows.append({"member": f"ollama:{model}", "provider": "ollama", "model": model, "score": 0.5,
                             "local": True, "free": True, "label": f"{model} (local)"})
            continue
        try:
            from config import SETTINGS

            model = str(getattr(SETTINGS, f"{name}_model", "") or "")
        except Exception:  # noqa: BLE001
            model = ""
        rows.append({"member": f"{name}:{model or 'default'}", "provider": name, "model": model, "score": 0.5,
                     "local": False, "free": True, "label": str(getattr(provider, "label", "") or name)})
    return rows


def members(domain: str = "", *, router: Any = None, refresh: bool = False, limit: int = 12) -> List[Dict[str, Any]]:
    """Models that can answer right now, best first for ``domain``. Never raises."""
    key = domain or "chat"
    with _lock:
        hit = _members_cache.get(key)
        if hit and not refresh and time.time() - hit[0] < _MEMBER_CACHE_SECONDS:
            return list(hit[1])
    rows: List[Dict[str, Any]] = []
    try:
        from identity0 import api as kahuna_api

        rows = [dict(r) for r in kahuna_api.best_models(key, limit=limit, router=router)]
    except Exception:  # noqa: BLE001 - Big Kahuna is an improvement here, never a requirement
        rows = []
    if not rows:
        try:
            rows = _router_members(router if router is not None else _shared_router())
        except Exception:  # noqa: BLE001
            rows = []
    with _lock:
        _members_cache[key] = (time.time(), rows)
    return list(rows)


def forget_members() -> None:
    with _lock:
        _members_cache.clear()


_router_lock = threading.Lock()
_router: Any = None


def _shared_router() -> Any:
    """One Router for the whole office package (building one costs provider probes)."""
    global _router
    with _router_lock:
        if _router is None:
            from router import Router

            _router = Router()
        return _router


def shared_router() -> Any:
    return _shared_router()


def set_router(router: Any) -> None:
    """Tests inject a fake router."""
    global _router
    with _router_lock:
        _router = router


def domain_for(role_id: str) -> str:
    """The domain a role thinks in — what Big Kahuna ranks models by."""
    from office import roles as role_module

    role = role_module.get(role_id)
    return role.domain if role else "chat"


def provider_slots(provider: str) -> int:
    return _PROVIDER_SLOTS.get(provider, _DEFAULT_SLOTS)


# ---------------------------------------------------------------------------
# Handing out the models
# ---------------------------------------------------------------------------


@dataclass
class Casting:
    """Spreads agents across the available models, weighted by how good each one is at that domain.

    Keeps a rotation per domain so the second Coder does not get the same model as the first: the office is
    deliberately many minds, not one model copied twenty times.
    """

    router: Any = None
    _turn: Dict[str, int] = field(default_factory=dict)

    def pick(self, role_id: str, *, avoid: str = "") -> str:
        domain = domain_for(role_id)
        rows = members(domain, router=self.router)
        if not rows:
            return ""
        ranked: List[str] = []
        for index, row in enumerate(rows):
            weight = 3 if index == 0 else (2 if index < 3 else 1)
            ranked.extend([str(row.get("member") or "")] * weight)
        ranked = [m for m in ranked if m]
        if not ranked:
            return ""
        with _lock:
            start = self._turn.get(domain, 0)
            for step in range(len(ranked)):
                member = ranked[(start + step) % len(ranked)]
                if member != avoid or len(set(ranked)) == 1:
                    self._turn[domain] = (start + step + 1) % len(ranked)
                    return member
            self._turn[domain] = (start + 1) % len(ranked)
        return ranked[start % len(ranked)]

    def lead_member(self) -> str:
        """The top manager's seat: Big Kahuna itself when it is up, else the best general model."""
        router = self.router if self.router is not None else _shared_router()
        try:
            if router.providers.get("identity0") is not None and router.providers["identity0"].is_available():
                return "identity0:default"
        except Exception:  # noqa: BLE001
            pass
        rows = members("agents", router=router)
        return str(rows[0].get("member")) if rows else ""

    def spread(self) -> Dict[str, int]:
        """How many desks each model currently holds — only meaningful to the caller that fills it in."""
        return {}


def graded_agents(task: str, limit: int = 6) -> List[Dict[str, Any]]:
    """Ask the daily agent grading (Plan Null N9) which sub-agents suit a task. Empty when it is not installed."""
    try:
        import agent_grading

        rows = agent_grading.pick_agents(task, surface="office", limit=limit)
        return [r for r in rows if isinstance(r, dict)]
    except Exception:  # noqa: BLE001 - optional by contract
        return []


def record_use(agent_role: str, ok: bool, seconds: float, member: str = "") -> None:
    """Report a finished office task to the grading run, when it exists."""
    provider, _, model = (member or "").partition(":")
    try:
        import agent_grading

        agent_grading.record_use(agent_role, "office", ok, seconds, provider=provider, model=model)
    except Exception:  # noqa: BLE001 - optional by contract
        pass
