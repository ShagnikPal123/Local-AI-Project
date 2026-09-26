"""The Hiring Board — the agent class that only exists when an office starts hiring too freely.

The owner's rule, in their words: *"If it seems that too many agents are being added or new types of agents are
made (say 10 at this point) add a agent (create this as a separate agent class that can only be spawned in this
case) where requests are given to it … and it decides if it should be done."*

So: while an office is small, a section manager approving a teammate is fine and instant. Once the office has
invented ten kinds of agent, or ten agents have appeared inside ten minutes, the Hiring Board wakes up — a role
that cannot be staffed any other way — and from then on **every** request to add an agent goes through it and is
answered with the Crit think skill, offline facts first and a model second.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

from office import HIRES_PER_WINDOW_BEFORE_GATEKEEPER, HIRE_WINDOW_SECONDS, NEW_TYPES_BEFORE_GATEKEEPER
from office import crit_think
from office.crit_think import Verdict
from office.roles import HIRING_BOARD


def wake_reason(office: Any) -> str:
    """Why the board should exist now — empty while the office is still hiring sensibly."""
    if office.gatekeeper_id and office.gatekeeper_id in office.agents:
        return ""
    invented = len(office.invented_roles)
    if invented >= NEW_TYPES_BEFORE_GATEKEEPER:
        return (f"{invented} new kinds of agent have been invented in this office. From now on a Hiring Board "
                "decides whether another one is really needed.")
    cutoff = time.time() - HIRE_WINDOW_SECONDS
    recent = [h for h in office.hires if h.status == "approved" and h.decided_at >= cutoff]
    added = sum(max(1, h.count) for h in recent)
    if added >= HIRES_PER_WINDOW_BEFORE_GATEKEEPER:
        return (f"{added} agents were brought in within {HIRE_WINDOW_SECONDS // 60} minutes. A Hiring Board now "
                "decides whether the office needs more.")
    return ""


def is_awake(office: Any) -> bool:
    return bool(office.gatekeeper_id and office.gatekeeper_id in office.agents)


def decide(office: Any, request: Any, *, member: str = "", router: Any = None,
           cancelled: Optional[Callable[[], bool]] = None, use_model: bool = True) -> Verdict:
    """The board's answer to one request: the offline read, then the model, with the facts winning ties."""
    from office import talk

    capacity = int(getattr(office, "capacity", 0) or 0)
    verdict = crit_think.weigh(office, request, capacity=capacity)
    # Facts that are not judgement calls are final: no seats, or somebody idle who already does this.
    if verdict.decision in ("reuse",) or (verdict.checks or {}).get("head_room", 0) < max(1, request.count):
        return verdict
    if not use_model or not member:
        return verdict

    answer = talk.ask(member, [{"role": "user", "content": crit_think.prompt_for(office, request, verdict)}],
                      system=("You are the Hiring Board of an office of AI agents. You are the only agent that can "
                              "refuse a request for another agent. Answer with JSON only."),
                      max_tokens=400, timeout=60, cancelled=cancelled, router=router)
    data = talk.parse_json(answer.text) if answer.ok else None
    if not isinstance(data, dict):
        verdict.reason = f"{verdict.reason} (decided without a model: {answer.error or 'no readable answer'})"
        return verdict
    decision = str(data.get("decision") or "").strip().lower()
    if decision not in ("approve", "clone", "reuse", "deny"):
        return verdict
    reason = str(data.get("reason") or "").strip()[:300] or verdict.reason
    use_instead = str(data.get("use_instead") or "").strip()[:60]
    try:
        count = max(1, min(int(data.get("count") or request.count), max(1, request.count)))
    except (TypeError, ValueError):
        count = request.count
    request.count = count
    return Verdict(decision=decision, reason=reason, use_instead=use_instead or verdict.use_instead,
                   score=verdict.score, checks=verdict.checks)


def manager_verdict(office: Any, request: Any) -> Verdict:
    """Before the board exists: a section manager's own quick call, offline so it costs nothing."""
    verdict = crit_think.weigh(office, request, capacity=int(getattr(office, "capacity", 0) or 0))
    if verdict.decision == "deny" and verdict.score >= 0.4:
        # A manager is more permissive than the board: while the office is small, trying an agent is cheap.
        return Verdict("approve", "Approved by the section manager while the office is still small.",
                       score=verdict.score, checks=verdict.checks)
    return verdict


def skill_note() -> Dict[str, Any]:
    """The Crit think skill as the skill library stores it (used by ``office.api.install_skill``)."""
    return {"name": crit_think.SKILL_NAME, "description": crit_think.SKILL_DESCRIPTION,
            "instructions": crit_think.SKILL_INSTRUCTIONS, "triggers": list(crit_think.SKILL_TRIGGERS)}


__all__ = ["wake_reason", "is_awake", "decide", "manager_verdict", "skill_note", "HIRING_BOARD", "Verdict"]
