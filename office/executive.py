"""The office as a big company (UPDATE_IDEAS U42, the part Update 1 left): when a project is big, the head office
splits into an executive suite.

The owner: *"if an office project seems big the main head office splits into a bigger one … CEO, CFO, decision
bots, decision teams, thinkers, overhead managers, and manager distributors take the place of the old system when
it is really big. In here they make decisions."*

Each seat has a job the plain office did not have, so the split is more than new names on desks:

* **CEO** — the top manager, renamed. It still plans and writes the answer.
* **CFO** — keeps the books: a hiring budget for the job (past it, new agents are refused) and a ledger at the end
  (agents, tasks, agent-time, paid vs free models). Offline: arithmetic is not a model's job.
* **Decision team** — three decision bots that vote on every hire, each with its own bar (careful, balanced,
  bold), on the facts ``crit_think.weigh`` gathers. Majority wins; the facts (no seats, someone idle) are final.
* **Thinkers** — read the plan before work starts and name its risks and what is missing; one model call each.
  Their notes go to the CEO's final write-up.
* **Manager-distributors** — when a section has queued work and nobody free, they lend an idle agent of the same
  kind from another section of the same job.
* **Overhead managers** — a task that failed is given one more go, with the error attached so it is not repeated.

Everything here is decided once per job and only when the job is big: a small job never pays for a company.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence

from office import crit_think, talk
from office.state import AGENT_IDLE, TASK_FAILED, TASK_QUEUED, Message, new_id

EXECUTIVE_SUITE = "Executive Suite"
CFO, DECISION_BOT, THINKER, OVERHEAD, DISTRIBUTOR = "cfo", "decision-bot", "thinker", "overhead-manager", "distributor"
ROLE_IDS = frozenset({CFO, DECISION_BOT, THINKER, OVERHEAD, DISTRIBUTOR})
BIG_SCALES = frozenset({"large", "massive"})
#: Each decision bot's bar for "approve" on crit_think's 0–1 score: careful, balanced, bold.
DECISION_BARS = (0.65, 0.55, 0.45)
THINKER_TOKENS = 500
THINKER_TIMEOUT = 90.0


def is_big(job: Any) -> bool:
    """A job the plain office should not run alone: the plan says large, or its size does."""
    return (str(getattr(job, "scale", "") or "").lower() in BIG_SCALES
            or len(getattr(job, "section_ids", []) or []) >= 5
            or len(getattr(job, "task_ids", []) or []) >= 24)


def suite(office: Any) -> Optional[Any]:
    return office.section_by_name(EXECUTIVE_SUITE)


def active(office: Any) -> bool:
    return suite(office) is not None


def seated(office: Any, role_id: str) -> List[Any]:
    return [a for a in office.agents.values() if a.role == role_id]


def hiring_budget(office: Any, job: Any) -> int:
    """New agents the CFO allows for one job: two per section, at least four."""
    return max(4, 2 * len(getattr(job, "section_ids", []) or []))


def hires_this_job(office: Any, job: Any) -> int:
    started = float(getattr(job, "started_at", 0) or getattr(job, "created_at", 0) or 0)
    return sum(1 for h in office.hires if h.status == "approved" and h.decided_at >= started) if started else 0


# ---------------------------------------------------------------------------
# The split
# ---------------------------------------------------------------------------


def expand(engine: Any, office: Any, job: Any) -> List[str]:
    """Seat the executive suite (once per office). Returns the names of who joined."""
    joined: List[str] = []
    section = suite(office)
    if section is None:
        section = engine._make_section(office, EXECUTIVE_SUITE, "Runs the company when one head office is too "
                                       "small for the work: budget, decisions, risks, and moving people where "
                                       "the work is.", job_id=job.id)
    distributors = max(1, min(3, len(job.section_ids) // 4 or 1))
    wanted = {CFO: 1, DECISION_BOT: len(DECISION_BARS), THINKER: 2, OVERHEAD: 1, DISTRIBUTOR: distributors}
    for role_id, count in wanted.items():
        for _ in range(max(0, count - len(seated(office, role_id)))):
            joined.append(engine._add_agent(office, section.id, role_id).name)
    if section.id not in job.section_ids:
        job.section_ids.append(section.id)
    top = office.top_manager()
    if top is not None and not top.name.startswith("CEO"):
        top.name = f"CEO {top.name}" if top.name != "Top Manager" else "CEO"
    if joined:
        engine._post(office, Message(
            id=new_id("msg"), by="office", by_name="Office", kind="chat", job_id=job.id,
            text=(f"This is a big one, so the head office becomes a company: {top.name if top else 'the CEO'} leads, "
                  f"with {', '.join(joined)} in the {EXECUTIVE_SUITE}.")))
    return joined


# ---------------------------------------------------------------------------
# Decision team and CFO
# ---------------------------------------------------------------------------


def decide_hire(office: Any, request: Any, job: Optional[Any]) -> crit_think.Verdict:
    """The decision team's vote on one hire, inside the CFO's budget. Offline, so it costs nothing."""
    base = crit_think.weigh(office, request, capacity=int(getattr(office, "capacity", 0) or 0))
    if base.decision in ("reuse", "clone") or (base.checks or {}).get("head_room", 0) < max(1, request.count):
        return base                                     # facts, not judgement
    if job is not None and hires_this_job(office, job) + request.count > hiring_budget(office, job):
        return crit_think.Verdict("deny", f"The CFO's hiring budget for this job is {hiring_budget(office, job)} "
                                          "new agents and it is spent. Use who is here.",
                                  score=base.score, checks=base.checks)
    votes = ["approve" if base.score >= bar else "deny" for bar in DECISION_BARS]
    yes = votes.count("approve")
    decision = "approve" if yes * 2 > len(votes) else "deny"
    tally = f"{yes}–{len(votes) - yes}"
    reason = (f"The decision team voted {tally} to bring them in: {base.reason}" if decision == "approve" else
              f"The decision team voted {tally} against: {base.reason}")
    checks = dict(base.checks or {}, votes=votes)
    return crit_think.Verdict(decision, reason, use_instead=base.use_instead, score=base.score, checks=checks)


def ledger(office: Any, job: Any) -> str:
    """The CFO's report for one job: what it used, in plain numbers."""
    tasks = [office.tasks[t] for t in job.task_ids if t in office.tasks]
    workers = {t.agent_id for t in tasks if t.agent_id}
    seconds = sum(max(0.0, (t.ended_at or 0) - (t.started_at or 0)) for t in tasks if t.started_at and t.ended_at)
    paid, free = set(), set()
    for agent_id in workers:
        agent = office.agent(agent_id)
        if agent is None or not agent.member:
            continue
        provider = agent.member.split(":", 1)[0]
        (free if provider in ("ollama", "identity0", "local") or "free" in agent.member else paid).add(agent.member)
    done = sum(1 for t in tasks if t.status == "done")
    failed = sum(1 for t in tasks if t.status == TASK_FAILED)
    hired = hires_this_job(office, job)
    return (f"CFO's ledger: {len(workers)} agents worked {len(tasks)} tasks ({done} done, {failed} failed) for "
            f"{seconds / 60:.1f} agent-minutes; {hired} new hire{'s' if hired != 1 else ''} of a budget of "
            f"{hiring_budget(office, job)}. Models: {len(free)} local or free, {len(paid)} on a key that may cost money"
            f"{' (' + ', '.join(sorted(paid))[:160] + ')' if paid else ''}.")


# ---------------------------------------------------------------------------
# Thinkers
# ---------------------------------------------------------------------------


def think_through(engine: Any, office: Any, job: Any, cancelled: Any = None) -> List[Dict[str, str]]:
    """Each thinker reads the plan once and names its risks. Their notes become part of the final write-up."""
    plan_lines = []
    for section_id in job.section_ids:
        section = office.section(section_id)
        if section is None or section.name == EXECUTIVE_SUITE:
            continue
        titles = [office.tasks[t].title for t in job.task_ids if t in office.tasks and office.tasks[t].section_id == section_id]
        plan_lines.append(f"- {section.name}: {'; '.join(titles[:8])}")
    if not plan_lines:
        return []
    notes: List[Dict[str, str]] = []
    angles = ("what could go wrong and what is missing from the plan",
              "what the owner will actually judge the result on, and whether the plan delivers that")
    for thinker, angle in zip(seated(office, THINKER), angles):
        engine._set_agent(office, thinker, "working", "Thinking the plan through")
        answer = talk.ask(thinker.member, [{"role": "user", "content": (
            f"The owner asked: {job.request[:1500]}\n\nThe plan:\n" + "\n".join(plan_lines[:20]) +
            f"\n\nThink about {angle}. Answer in at most four short bullet points, most important first.")}],
            system="You are a thinker in an office of AI agents. You do not do the work; you see what others miss.",
            max_tokens=THINKER_TOKENS, timeout=THINKER_TIMEOUT, cancelled=cancelled, router=engine._router())
        engine._set_agent(office, thinker, AGENT_IDLE, "")
        if answer.ok and answer.text.strip():
            text = answer.text.strip()[:1200]
            notes.append({"section": thinker.name, "text": text})
            engine._post(office, Message(id=new_id("msg"), by=thinker.id, by_name=thinker.name, kind="report",
                                         job_id=job.id, text=text))
    return notes


# ---------------------------------------------------------------------------
# Distributors and overhead managers
# ---------------------------------------------------------------------------


def lend(office: Any, job: Any, task: Any, *, excluded: Sequence[str]) -> Optional[Any]:
    """An idle agent of the task's kind from another section of the same job, or None."""
    if not seated(office, DISTRIBUTOR):
        return None
    for section_id in job.section_ids:
        if section_id == task.section_id:
            continue
        for agent in office.agents_in(section_id):
            if agent.status == AGENT_IDLE and agent.role == task.role and agent.role not in excluded:
                return agent
    return None


def rescue(office: Any, job: Any) -> List[Any]:
    """Failed tasks of this job get one more go, error attached; returns the tasks put back in the queue."""
    if not seated(office, OVERHEAD):
        return []
    again: List[Any] = []
    for task_id in job.task_ids:
        task = office.tasks.get(task_id)
        if task is None or task.status != TASK_FAILED or task.tries > 1:
            continue
        task.feedback = (f"Overhead manager: the first try failed ({(task.result or 'no result')[:300]}). "
                         "Try a different approach.")
        task.status, task.result, task.ended_at = TASK_QUEUED, "", 0.0
        task.agent_id = ""                   # tries is now 1, so the next failure is final
        again.append(task)
    return again


__all__ = ["EXECUTIVE_SUITE", "ROLE_IDS", "is_big", "active", "expand", "decide_hire", "ledger", "think_through",
           "lend", "rescue", "hiring_budget"]
