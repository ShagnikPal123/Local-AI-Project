"""Big Kahuna's stable public entry points for the rest of Nyx (Office Space, agent grading, the voice bar…).

Other features call these and nothing deeper: the modules behind them (competence, predict, companion)
may change shape, these signatures do not. Every function here is read-only or side-effect free, cheap,
and never raises — a broken Big Kahuna must never break the feature asking it for advice.

- ``domain_of(text)`` → the domain name Big Kahuna files a task under ("code", "math", "chat"…).
- ``best_models(task, limit=5)`` → the models Big Kahuna would pick for a task or domain, best first.
- ``competence()`` → the whole learned table (per domain × model record), for dashboards and grading.
- ``voice_intent(text, final=False, tabs=None)`` → early actions from partial speech ("open gmail…").
- ``suggest(text, current_tab="")`` → skills, agents, next tab and domain predictions in one call.
- ``warm_up()`` → load the local models into VRAM now (call it when the owner is about to speak).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def domain_of(text: str) -> str:
    """The domain Big Kahuna would file ``text`` under; a known domain name (``chat`` when unsure)."""
    try:
        from identity0.provider import classify

        return str(classify(text or "")[0] or "chat")  # the same call Big Kahuna plans a turn with
    except Exception:  # noqa: BLE001
        return "chat"


def _is_domain(value: str) -> bool:
    return bool(value) and " " not in value.strip() and len(value) <= 24


def best_models(task_or_domain: str, *, limit: int = 5, needs_vision: bool = False,
                router: Any = None) -> List[Dict[str, Any]]:
    """Models that are up and allowed right now, ranked by Big Kahuna's learned competence, best first.

    ``task_or_domain`` is either a domain name ("code") or a task in words ("fix this Python bug"). Each item:
    ``{"member": "ollama:qwen3.5:9b", "provider": "ollama", "model": "qwen3.5:9b", "score": 0.61,
    "local": True, "free": True, "vision": True, "avg_ms": 2100, "label": "…"}``. The own model only appears
    ranked for a domain it has graduated in. Empty when no model is up (or on any error).
    """
    try:
        from identity0 import competence, members
        from identity0.provider import shared_router

        domain = task_or_domain.strip().lower() if _is_domain(task_or_domain) else domain_of(task_or_domain)
        live = router if router is not None else shared_router()
        if live is None:
            return []
        pool = [m for m in members.available(live) if m.provider != "self" or competence.graduated(domain)]
        ranked = competence.rank(domain, pool, needs_vision=needs_vision)
        return [{"member": m.id, "provider": m.provider, "model": m.model, "score": competence.score(domain, m),
                 "local": m.local, "free": m.free, "vision": m.vision, "avg_ms": round(competence.avg_ms(domain, m)),
                 "label": m.label, "domain": domain} for m in ranked[:max(1, int(limit))]]
    except Exception:  # noqa: BLE001
        return []


def competence() -> Dict[str, Any]:
    """The learned table: ``{"domains": {domain: {member: record}}, "own_model": …, "graduated": …}``."""
    try:
        from identity0 import competence as table

        return table.table()
    except Exception:  # noqa: BLE001
        return {"domains": {}, "own_model": {}, "graduated": {}}


def voice_intent(text: str, *, final: bool = False, tabs: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """Actions to take from (possibly partial) speech — call it on every interim transcript.

    Returns ``{"text", "final", "actions": [...], "handled"}``. An action is ``{"kind": "open_tab", "tab": id,
    "early": True, "key": …}``, ``{"kind": "open_url", "url": …, "early": True}`` or, once ``final``,
    ``{"kind": "compose_email", "to", "spoken", "early": False}`` (a draft the owner sends; nothing is ever
    sent). ``early`` actions are safe before the sentence ends; ``key`` dedupes repeats across interim calls.
    ``tabs`` is the UI's ``[{"id", "label"}]`` list so spoken names map to real tabs. Executing is the
    caller's job (``POST /api/identity0/act`` or ``companion.act``).
    """
    try:
        from identity0 import companion

        return companion.intent(text or "", final=final, tabs=tabs or [])
    except Exception:  # noqa: BLE001
        return {"actions": []}


def warm_up(keep_minutes: int = 20) -> Dict[str, Any]:
    """Load the local models now so the next spoken turn is fast. Returns at once; work happens in a thread.

    Call it when the owner is about to talk (the voice bar opening, the companion opening, wake word) or
    when the engine starts. A local model Ollama has unloaded costs about three minutes to load again.
    """
    try:
        from identity0 import members

        return members.warm_local(keep_minutes)
    except Exception:  # noqa: BLE001
        return {"ollama": False, "own": False}


def suggest(text: str, current_tab: str = "") -> Dict[str, Any]:
    """Predicted domain, skills, sub-agents, next tab and speed mode for ``text`` (all best-effort)."""
    try:
        from identity0 import predict

        return predict.everything(text or "", current_tab)
    except Exception:  # noqa: BLE001
        return {"domain": {"domain": "chat"}, "skills": [], "agents": [], "next_tab": None, "speed": None}
