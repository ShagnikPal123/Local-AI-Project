"""Crit think — the skill the Hiring Board thinks with, and a skill Nyx can use anywhere.

The owner: *"add a agent (create this as a separate agent class that can only be spawned in this case) where
requests are given to it … and it decides if it should be done. Using a new skill mainly for it called crit
think which thinks if it is useful. In this agent, the agents/sub agents that want to add a new agent give the
agent they want (new or clone) and why they need it, and long term use."*

The instructions below are the skill (text, never code — ``skills.py`` invariant). ``weigh`` is the offline half:
the checks that do not need a model, so a decision still happens when every model is busy or down, and so the
model has something concrete to argue with rather than a blank page.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

SKILL_NAME = "Crit think"
SKILL_DESCRIPTION = ("Decide whether something new is actually worth adding — a new agent, tool, tab or "
                     "process — instead of adding it because it was asked for.")
SKILL_TRIGGERS = ["crit think", "critical thinking", "is this useful", "should we add", "do we need another",
                  "new agent request", "hiring board", "worth adding", "justify this"]

SKILL_INSTRUCTIONS = """Crit think — decide whether adding this is genuinely worth it.

Work through these in order and keep each answer to one line:

1. **The ask, in your own words.** What exactly is being added, and for which piece of work?
2. **Who does that work today?** Name the existing agent, tool or step. "Nobody" is a real answer — say it only
   after you have looked.
3. **Overlap.** How much of it is already covered? If something covers 80% of it, the honest answer is to use
   that thing, or to clone it, not to invent a new kind.
4. **Evidence of need.** Is there a task waiting on this right now, or is it a guess about the future? A request
   that cannot name the blocked work is a guess.
5. **Cost.** What does it take up — a seat, a model, attention, maintenance forever? Adding is cheap; carrying
   is not.
6. **Long-term use.** Will this be used again next week and next month, or once? One-offs are borrowed, not hired.
7. **The smallest thing that works.** Reuse an idle one → clone an existing kind → a new kind, in that order.

Then answer in one word — **approve**, **clone**, **reuse** or **deny** — with one sentence of reason that
names the deciding fact, and, when you say reuse or clone, who to use instead.

Never approve to be agreeable, and never deny to look careful. If the request is genuinely needed and nothing
covers it, approve it plainly."""


@dataclass
class Verdict:
    decision: str            # approve | clone | reuse | deny
    reason: str
    use_instead: str = ""
    score: float = 0.0
    checks: Dict[str, Any] = None  # type: ignore[assignment]

    def as_dict(self) -> Dict[str, Any]:
        return {"decision": self.decision, "reason": self.reason, "use_instead": self.use_instead,
                "score": round(self.score, 2), "checks": dict(self.checks or {})}


def _words(text: str) -> set:
    return {w for w in (text or "").lower().replace("/", " ").split() if len(w) > 3}


def overlap(role_words: str, *, office: Any) -> Dict[str, Any]:
    """How much of the requested kind an existing role already covers (0..1), and which role that is."""
    from office import roles as role_module

    wanted = _words(role_words)
    best, best_score = "", 0.0
    for role in role_module.catalogue(include_special=False):
        terms = _words(" ".join((role.title, role.plural or "", role.goal, *role.synonyms)))
        if not terms or not wanted:
            continue
        score = len(wanted & terms) / len(wanted)
        exact = role_module.find(role_words)
        if exact is not None and exact.id == role.id:
            score = max(score, 0.95)
        if score > best_score:
            best, best_score = role.id, score
    on_floor = {a.role for a in office.agents.values()} if office is not None else set()
    return {"role": best, "score": round(best_score, 2), "on_floor": best in on_floor}


def weigh(office: Any, request: Any, *, capacity: int = 0) -> Verdict:
    """The offline half of the decision — the facts a model should not be trusted to invent."""
    from office import roles as role_module

    checks: Dict[str, Any] = {}
    why = (getattr(request, "why", "") or "").strip()
    long_term = (getattr(request, "long_term", "") or "").strip()
    role_words = (getattr(request, "role_words", "") or "").strip()
    count = max(1, int(getattr(request, "count", 1) or 1))

    known = role_module.find(role_words)
    cover = overlap(role_words, office=office)
    checks["known_type"] = bool(known)
    checks["overlap"] = cover

    idle = []
    if office is not None and known is not None:
        idle = [a for a in office.agents.values() if a.role == known.id and a.status in ("idle", "waiting")]
    checks["idle_same_role"] = [a.name for a in idle][:4]

    head_room = (capacity or getattr(office, "capacity", 0) or 0) - len(getattr(office, "agents", {}) or {})
    checks["head_room"] = head_room

    recent_denials = [h for h in getattr(office, "hires", [])
                      if h.status == "denied" and h.role_words.lower() == role_words.lower()
                      and time.time() - h.ts < 900]
    checks["recently_denied"] = len(recent_denials)

    # Hard stops first — these are facts, not judgement.
    if head_room < count:
        return Verdict("deny", f"The office is at its limit for this computer ({len(office.agents)} agents).",
                       score=0.0, checks=checks)
    if idle:
        return Verdict("reuse", f"{idle[0].name} does this and is free right now.", use_instead=idle[0].name,
                       score=0.2, checks=checks)
    if recent_denials:
        return Verdict("deny", f"The same request was turned down {len(recent_denials)} time(s) in the last "
                               "15 minutes and nothing has changed.", score=0.1, checks=checks)

    score = 0.0
    score += 0.35 if len(why) >= 40 else (0.15 if len(why) >= 15 else 0.0)
    score += 0.25 if len(long_term) >= 30 else (0.1 if long_term else 0.0)
    if known is not None:
        score += 0.25          # a kind the office already understands is cheap to add
    elif cover["score"] >= 0.6:
        score += 0.05
    else:
        score += 0.15          # genuinely new ground, if the reason holds up
    score += 0.15 if head_room > count * 3 else 0.0
    if count > 4:
        score -= 0.1

    if known is None and cover["score"] >= 0.7 and cover["role"]:
        role = role_module.get(cover["role"])
        return Verdict("clone", f"{role.title if role else cover['role']} already covers most of this — "
                                "another one of those is the smaller change.",
                       use_instead=(role.title if role else cover["role"]), score=score, checks=checks)
    if score >= 0.55:
        return Verdict("approve", f"Nothing on the floor covers this and the reason names real work.",
                       score=score, checks=checks)
    if not why:
        return Verdict("deny", "No reason was given for the new agent.", score=score, checks=checks)
    return Verdict("deny", "The reason does not name work that is actually waiting, and nothing is blocked "
                           "without it.", score=score, checks=checks)


def prompt_for(office: Any, request: Any, verdict: Verdict) -> str:
    """What the Hiring Board is shown: the request, the facts, and the skill it must follow."""
    from office import roles as role_module

    on_floor: Dict[str, int] = {}
    for agent in getattr(office, "agents", {}).values():
        on_floor[agent.role] = on_floor.get(agent.role, 0) + 1
    roster = ", ".join(f"{(role_module.get(r).title if role_module.get(r) else r)} ×{n}"
                       for r, n in sorted(on_floor.items(), key=lambda kv: -kv[1])[:14])
    return (
        f"{SKILL_INSTRUCTIONS}\n\n## The request\n"
        f"Asked by: {getattr(request, 'by_name', '') or 'an agent'}"
        f"{' in ' + office.section(request.section_id).name if office.section(getattr(request, 'section_id', '')) else ''}\n"
        f"Wants: {getattr(request, 'count', 1)} × {getattr(request, 'role_words', '')}"
        f"{' (a clone of ' + request.clone_of + ')' if getattr(request, 'clone_of', '') else ''}\n"
        f"Why: {getattr(request, 'why', '') or '(nothing given)'}\n"
        f"Long-term use: {getattr(request, 'long_term', '') or '(nothing given)'}\n\n"
        f"## What is already on the floor\n{roster or '(nobody yet)'}\n"
        f"Seats left: {verdict.checks.get('head_room') if verdict.checks else '?'}\n"
        f"Closest existing kind: {verdict.checks.get('overlap', {}).get('role', '—') if verdict.checks else '—'} "
        f"(overlap {verdict.checks.get('overlap', {}).get('score', 0) if verdict.checks else 0})\n"
        f"Free right now who could do it: {', '.join(verdict.checks.get('idle_same_role', [])) or 'nobody'}\n"
        f"The office's own first read: {verdict.decision} — {verdict.reason}\n\n"
        'Answer with JSON only: {"decision": "approve|clone|reuse|deny", "reason": "one sentence", '
        '"use_instead": "agent or kind, when reuse or clone", "count": <how many to actually add>}'
    )
