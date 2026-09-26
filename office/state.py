"""The records an office is made of, and their JSON form.

One office file holds all of this: the sections (rooms), the agents at their desks, every task, the main chat
with the top manager, the targeted chat, what agents said to each other, the hiring requests, and the jobs the
owner has given. It is plain data — an office that is closed and re-opened a week later comes back with the same
team at the same desks, which is what *"It fully remembers things from previous sessions"* means in practice.

Sizes are capped here rather than in the writer, so a runaway office cannot grow an unopenable file: chat and
feed keep their last N entries (older ones go to ``history.jsonl``) and a task keeps a preview of its result
(the whole thing lives in ``work/_reports/``).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from office import KEEP_CHAT, KEEP_FEED, KEEP_TASK_PREVIEW

# Statuses, in one place so the UI and the engine cannot drift apart.
OFFICE_IDLE, OFFICE_RUNNING, OFFICE_PAUSED, OFFICE_HALTED = "idle", "running", "paused", "halted"
AGENT_IDLE, AGENT_WORKING, AGENT_WAITING, AGENT_PAUSED, AGENT_ERROR = "idle", "working", "waiting", "paused", "error"
TASK_QUEUED, TASK_WORKING, TASK_REVIEW, TASK_DONE, TASK_FAILED, TASK_CANCELLED = (
    "queued", "working", "review", "done", "failed", "cancelled")
PHASES = ("plan", "staff", "brief", "work", "review", "wrap")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _keep_last(items: List[Any], limit: int) -> List[Any]:
    return items[-limit:] if len(items) > limit else items


@dataclass
class Section:
    """A department — the owner's "smaller managers of different infrastructure"."""

    id: str
    name: str
    color: str
    purpose: str = ""
    manager_id: str = ""
    status: str = "active"          # active | paused | halted
    created_at: float = field(default_factory=time.time)
    job_id: str = ""                # the job that opened it
    notes: str = ""                 # what the section has learned about its own work
    order: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Agent:
    """One agent at one desk. ``member`` is the model it thinks with: "provider:model"."""

    id: str
    name: str
    role: str
    section_id: str
    member: str = ""
    status: str = AGENT_IDLE
    step: str = ""
    task_id: str = ""
    desk: int = 0
    created_at: float = field(default_factory=time.time)
    origin: str = "hired"           # hired | cloned | invented | founding
    tasks_done: int = 0
    seconds: float = 0.0
    errors: int = 0
    note: str = ""                  # what this agent keeps to itself between sessions
    inbox: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["inbox"] = len(self.inbox)   # the UI wants the count; the contents go to the agent itself
        return data


@dataclass
class Task:
    id: str
    title: str
    detail: str = ""
    section_id: str = ""
    agent_id: str = ""
    role: str = ""
    status: str = TASK_QUEUED
    created_by: str = "owner"
    job_id: str = ""
    parent_id: str = ""
    after: List[str] = field(default_factory=list)      # task ids that must finish first
    result: str = ""                                     # preview; the full report is a file
    report_path: str = ""
    files: List[str] = field(default_factory=list)
    feedback: str = ""                                   # a manager's fix note, when it sent the work back
    tries: int = 0
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    ended_at: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def trim(self) -> None:
        if len(self.result) > KEEP_TASK_PREVIEW:
            self.result = self.result[:KEEP_TASK_PREVIEW] + "…"


@dataclass
class Message:
    id: str
    text: str
    by: str = "owner"               # agent id, "owner", or "office"
    by_name: str = "You"
    to: List[str] = field(default_factory=list)          # agent ids
    to_label: str = ""              # "3 coders in Frontend, Backend"
    kind: str = "chat"              # chat | thread | report | delegate | liaison | system | hire
    ts: float = field(default_factory=time.time)
    job_id: str = ""
    section_id: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HireRequest:
    """An agent asking for another agent — what the Hiring Board decides on."""

    id: str
    role_words: str                 # what was asked for, in the asker's words
    why: str
    long_term: str = ""
    count: int = 1
    clone_of: str = ""
    section_id: str = ""
    by: str = ""
    by_name: str = ""
    status: str = "pending"         # pending | approved | denied | reuse
    decided_by: str = ""            # "manager" | "Hiring Board" | "owner"
    reason: str = ""
    use_instead: str = ""
    role_id: str = ""
    new_type: bool = False
    ts: float = field(default_factory=time.time)
    decided_at: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Job:
    """One thing the owner asked for, from plan to final answer."""

    id: str
    request: str
    title: str = ""
    phase: str = "plan"
    kind: str = "job"               # job (planned from the main chat) | ad-hoc (came from the targeted chat)
    status: str = "running"         # running | done | stopped | failed
    started_at: float = field(default_factory=time.time)
    ended_at: float = 0.0
    reply: str = ""
    summary: str = ""
    scale: str = ""
    section_ids: List[str] = field(default_factory=list)
    task_ids: List[str] = field(default_factory=list)
    error: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Office:
    id: str
    name: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = OFFICE_IDLE
    phase: str = ""
    goal: str = ""
    sections: Dict[str, Section] = field(default_factory=dict)
    agents: Dict[str, Agent] = field(default_factory=dict)
    tasks: Dict[str, Task] = field(default_factory=dict)
    chat: List[Message] = field(default_factory=list)
    thread: List[Message] = field(default_factory=list)
    feed: List[Message] = field(default_factory=list)
    jobs: List[Job] = field(default_factory=list)
    hires: List[HireRequest] = field(default_factory=list)
    invented_roles: List[Dict[str, Any]] = field(default_factory=list)
    gatekeeper_id: str = ""
    capacity: int = 0
    stats: Dict[str, Any] = field(default_factory=dict)
    settings: Dict[str, Any] = field(default_factory=dict)
    version: int = 1

    # --- reads ------------------------------------------------------------------

    def agent(self, agent_id: str) -> Optional[Agent]:
        return self.agents.get(agent_id)

    def by_name(self, name: str) -> Optional[Agent]:
        wanted = (name or "").strip().lower()
        if not wanted:
            return None
        found = next((a for a in self.agents.values() if a.name.lower() == wanted), None)
        if found is not None:
            return found
        # "Coder 2" for "Coder #2", and a bare role name when only one of them exists.
        squashed = wanted.replace("#", "").replace("  ", " ")
        for agent in self.agents.values():
            if agent.name.lower().replace("#", "") == squashed:
                return agent
        same_role = [a for a in self.agents.values() if a.role == wanted or a.name.lower().startswith(wanted)]
        return same_role[0] if len(same_role) == 1 else None

    def section(self, section_id: str) -> Optional[Section]:
        return self.sections.get(section_id)

    def section_by_name(self, name: str) -> Optional[Section]:
        wanted = (name or "").strip().lower()
        if not wanted:
            return None
        return (next((s for s in self.sections.values() if s.name.lower() == wanted), None)
                or next((s for s in self.sections.values()
                         if wanted in s.name.lower() or s.name.lower() in wanted), None))

    def agents_in(self, section_id: str) -> List[Agent]:
        return sorted((a for a in self.agents.values() if a.section_id == section_id), key=lambda a: a.desk)

    def top_manager(self) -> Optional[Agent]:
        from office.roles import TOP_MANAGER

        return next((a for a in self.agents.values() if a.role == TOP_MANAGER), None)

    def manager_of(self, section_id: str) -> Optional[Agent]:
        section = self.sections.get(section_id)
        if section and section.manager_id:
            return self.agents.get(section.manager_id)
        from office.roles import SECTION_MANAGER

        return next((a for a in self.agents_in(section_id) if a.role == SECTION_MANAGER), None)

    def job(self, job_id: str) -> Optional[Job]:
        return next((j for j in self.jobs if j.id == job_id), None)

    def current_job(self) -> Optional[Job]:
        return next((j for j in reversed(self.jobs) if j.status == "running"), None)

    def counts(self) -> Dict[str, int]:
        working = sum(1 for a in self.agents.values() if a.status == AGENT_WORKING)
        done = sum(1 for t in self.tasks.values() if t.status == TASK_DONE)
        open_tasks = sum(1 for t in self.tasks.values() if t.status in (TASK_QUEUED, TASK_WORKING, TASK_REVIEW))
        return {"agents": len(self.agents), "working": working, "sections": len(self.sections),
                "tasks": len(self.tasks), "tasks_done": done, "tasks_open": open_tasks,
                "hires_pending": sum(1 for h in self.hires if h.status == "pending")}

    # --- writes -----------------------------------------------------------------

    def add_message(self, message: Message) -> Message:
        if message.kind == "chat":
            self.chat.append(message)
            self.chat = _keep_last(self.chat, KEEP_CHAT)
        elif message.kind == "thread":
            self.thread.append(message)
            self.thread = _keep_last(self.thread, KEEP_CHAT)
        else:
            self.feed.append(message)
            self.feed = _keep_last(self.feed, KEEP_FEED)
        self.updated_at = time.time()
        return message

    # --- JSON -------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "created_at": self.created_at, "updated_at": self.updated_at,
            "status": self.status, "phase": self.phase, "goal": self.goal, "capacity": self.capacity,
            "gatekeeper_id": self.gatekeeper_id, "version": self.version,
            "sections": [s.as_dict() for s in self.sections.values()],
            "agents": [{**asdict(a), "inbox": list(a.inbox)[-20:]} for a in self.agents.values()],
            "tasks": [t.as_dict() for t in self.tasks.values()],
            "chat": [m.as_dict() for m in self.chat],
            "thread": [m.as_dict() for m in self.thread],
            "feed": [m.as_dict() for m in self.feed],
            "jobs": [j.as_dict() for j in self.jobs[-40:]],
            "hires": [h.as_dict() for h in self.hires[-120:]],
            "invented_roles": list(self.invented_roles),
            "stats": dict(self.stats), "settings": dict(self.settings),
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Office":
        def build(kind: Any, rows: Any) -> List[Any]:
            out = []
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                fields = {f for f in kind.__dataclass_fields__}
                try:
                    out.append(kind(**{k: v for k, v in row.items() if k in fields}))
                except Exception:  # noqa: BLE001 - one broken row must not lose the office
                    continue
            return out

        office = cls(id=str(raw.get("id") or new_id("ofc")), name=str(raw.get("name") or "Office"))
        office.created_at = float(raw.get("created_at") or time.time())
        office.updated_at = float(raw.get("updated_at") or office.created_at)
        office.goal = str(raw.get("goal") or "")
        office.capacity = int(raw.get("capacity") or 0)
        office.gatekeeper_id = str(raw.get("gatekeeper_id") or "")
        office.invented_roles = [r for r in (raw.get("invented_roles") or []) if isinstance(r, dict)]
        office.stats = dict(raw.get("stats") or {})
        office.settings = dict(raw.get("settings") or {})
        office.sections = {s.id: s for s in build(Section, raw.get("sections"))}
        for agent in build(Agent, raw.get("agents")):
            if not isinstance(agent.inbox, list):
                agent.inbox = []
            office.agents[agent.id] = agent
        office.tasks = {t.id: t for t in build(Task, raw.get("tasks"))}
        office.chat = build(Message, raw.get("chat"))
        office.thread = build(Message, raw.get("thread"))
        office.feed = build(Message, raw.get("feed"))
        office.jobs = build(Job, raw.get("jobs"))
        office.hires = build(HireRequest, raw.get("hires"))

        # An office is never re-opened mid-flight: a run cannot survive the engine stopping, so anything that
        # was in the air becomes something the owner can restart, not a ghost that looks alive.
        office.status = OFFICE_IDLE
        office.phase = ""
        for agent in office.agents.values():
            if agent.status in (AGENT_WORKING, AGENT_WAITING):
                agent.status, agent.step, agent.task_id = AGENT_IDLE, "", ""
        for task in office.tasks.values():
            if task.status in (TASK_WORKING, TASK_REVIEW):
                task.status, task.agent_id = TASK_QUEUED, task.agent_id
        for job in office.jobs:
            if job.status == "running":
                job.status, job.ended_at = "stopped", job.ended_at or time.time()
        return office

    def snapshot(self) -> Dict[str, Any]:
        """What the tab renders: the same records, plus the counts and the current job."""
        job = self.current_job() or (self.jobs[-1] if self.jobs else None)
        return {
            "office": {"id": self.id, "name": self.name, "status": self.status, "phase": self.phase,
                       "goal": self.goal, "created_at": self.created_at, "updated_at": self.updated_at,
                       "capacity": self.capacity, "gatekeeper_id": self.gatekeeper_id,
                       "counts": self.counts(), "settings": dict(self.settings), "stats": dict(self.stats)},
            "sections": [s.as_dict() for s in sorted(self.sections.values(), key=lambda s: s.order)],
            "agents": [a.as_dict() for a in self.agents.values()],
            "tasks": [t.as_dict() for t in self.tasks.values()],
            "chat": [m.as_dict() for m in self.chat[-120:]],
            "thread": [m.as_dict() for m in self.thread[-120:]],
            "feed": [m.as_dict() for m in self.feed[-80:]],
            "hires": [h.as_dict() for h in self.hires[-40:]],
            "job": job.as_dict() if job else None,
            "roles": [],  # filled by the engine, which knows the live catalogue
        }
