"""The office at work: plan → staff → brief → work → review → wrap, live, pausable, and watchable.

One owner request becomes one **job**. The top manager (Big Kahuna, when it is up) plans it into sections and
tasks; the office staffs itself in front of the owner, desk by desk; each section manager splits its own work and
hands it out; the workers do it with their small tool set; managers review what comes back; the top manager
writes the answer and what the office should remember.

Everything that changes is published as an ``office.event`` the moment it happens, because the point of this tab
is watching it happen. Everything that matters is written into the office file, because the point of an office
is that it is still there tomorrow.

How many offices work at once comes from the machine (``casting.parallel_offices``, UPDATE_IDEAS U14): one on an
ordinary PC, where two offices fighting over the same free API keys would make both slower than one, and up to three
on a high-end one. Each running office has its own ``Run``; focus mode is held while any of them works and released
when the last one finishes.
"""

from __future__ import annotations

import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from office import (MAX_AGENTS_PER_SECTION, MAX_SECTIONS, casting, focus, gatekeeper, library, memory,
                    officetools, prompts, settings as settings_module, staffing, talk, targeting)
from office import roles as role_module
from office.roles import HIRING_BOARD, LIAISON, SECTION_MANAGER, TOP_MANAGER
from office.state import (AGENT_ERROR, AGENT_IDLE, AGENT_PAUSED, AGENT_WORKING, Agent, HireRequest, Job, Message, Output,
                          OFFICE_HALTED, OFFICE_IDLE, OFFICE_PAUSED, OFFICE_RUNNING, Office, Section,
                          TASK_CANCELLED, TASK_DONE, TASK_FAILED, TASK_QUEUED, TASK_REVIEW, TASK_WORKING, Task,
                          new_id)

#: Colours for sections — far apart, so two rooms never read as the same place.
SECTION_COLORS = ("#a594ff", "#5ac8fa", "#30d158", "#ffd60a", "#ff9f0a", "#ff6482", "#bf5af2", "#64d2ff",
                  "#acd94a", "#ff8c69", "#7bd3a8", "#f7b2ff", "#9ad7ff", "#e0b45a", "#5ad6e0", "#e07ac0",
                  "#b5abfc", "#5ac08a", "#e07a7a", "#75a8ff", "#d2cefd", "#5ab8e0", "#c9a227", "#8ee6c8")

HEAD_OFFICE = "Head Office"

MAX_WORKER_STEPS = 4
WORKER_TOKENS = 1200
MANAGER_TOKENS = 1300
PLAN_TOKENS = 2200
WORKER_TIMEOUT = 150.0
MANAGER_TIMEOUT = 150.0
PLAN_TIMEOUT = 210.0
MAX_TASKS_PER_JOB = 240
MAX_REPLIES_PER_MESSAGE = 12
SAVE_EVERY = 2.0
STAFF_ANIMATION_BUDGET = 3.0

_TASK_LINE = re.compile(r"^\s*TASK:\s*(?P<title>[^\n—–-]{3,90})\s*[—–-]{1,2}\s*(?P<detail>.+)$",
                        re.IGNORECASE | re.MULTILINE)


class OfficeError(ValueError):
    """Something the owner can act on: no office open, nothing to say, an action that does not apply."""


@dataclass
class Run:
    """One job in flight."""

    office_id: str
    job_id: str
    cancel: threading.Event = field(default_factory=threading.Event)
    paused: threading.Event = field(default_factory=threading.Event)
    pending: List[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    thread: Optional[threading.Thread] = None


class Engine:
    """Every open office, the one that is running, and everything that changes them."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._offices: Dict[str, Office] = {}
        self._saved_at: Dict[str, float] = {}
        self._runs: Dict[str, Run] = {}
        self._casting = casting.Casting()
        self._published: Dict[str, float] = {}
        self._replies = ThreadPoolExecutor(max_workers=6, thread_name_prefix="office-reply")

    # ------------------------------------------------------------------ opening

    def open(self, office_id: str, *, found: bool = True) -> Office:
        """Load an office into memory (and give it its top manager if it has never been opened)."""
        with self._lock:
            office = self._offices.get(office_id)
        if office is None:
            office = library.load(office_id)
            role_module.remember(office.invented_roles)
            with self._lock:
                self._offices[office_id] = office
                self._forget_idle_offices()
        office.capacity = self._capacity(office).agents
        if found and not office.sections:
            self._found(office)
        return office

    def opened(self, office_id: str) -> Optional[Office]:
        with self._lock:
            return self._offices.get(office_id)

    def close(self, office_id: str) -> None:
        with self._lock:
            office = self._offices.pop(office_id, None)
        if office is not None:
            library.save(office)

    def _forget_idle_offices(self) -> None:
        """Keep a few offices in memory; the rest are on disk and one read away."""
        keep = int(settings_module.load().get("keep_open_offices") or 3)
        extra = [oid for oid in list(self._offices) if oid not in self._runs]
        for office_id in extra[:-keep] if len(extra) > keep else []:
            office = self._offices.pop(office_id, None)
            if office is not None:
                library.save(office)

    def _capacity(self, office: Office) -> casting.Capacity:
        chosen = int((settings_module.load().get("max_agents") or 0))
        capacity = casting.capacity(focus=focus.held_by(office.id))
        if chosen:
            capacity.agents = max(1, min(chosen, capacity.agents * 4))
            capacity.reason = f"You set this office to at most {chosen} agents. " + capacity.reason
        return capacity

    def _found(self, office: Office) -> None:
        """The first thing an office has: a head office and a top manager sitting in it."""
        section = self._make_section(office, HEAD_OFFICE, "The top manager's own office — the whole office reports here.")
        member = self._casting.lead_member()
        top = self._add_agent(office, section.id, TOP_MANAGER, member=member, origin="founding")
        section.manager_id = top.id
        self._save(office, force=True)

    # ------------------------------------------------------------------ reading

    def snapshot(self, office_id: str) -> Dict[str, Any]:
        office = self.open(office_id)
        data = office.snapshot()
        data["roles"] = [r.as_dict() for r in role_module.catalogue()]
        item = library.find(office_id)
        folder = library.parent_folder_of(office_id)
        data["office"].update({
            "path": item.path if item else "",
            "folder": {"id": folder.id, "name": folder.name, "linked": folder.linked} if folder else None,
            "linked_offices": [{"id": s.id, "name": s.name} for s in library.linked_siblings(office_id)],
            "capacity_detail": self._capacity(office).as_dict(),
            "running": office_id in self._runs,
            "gatekeeper_reason": gatekeeper.wake_reason(office),
        })
        data["focus"] = focus.status()
        return data

    def overview(self) -> Dict[str, Any]:
        """What the tab needs before an office is open: the library, the settings, and what is running."""
        tree = library.tree()
        running = self.running_offices()
        limit, why = casting.parallel_offices()
        return {
            "library": tree,
            "settings": settings_module.load(),
            "focus": focus.status(),
            "capacity": casting.capacity(focus=focus.status()["held"]).as_dict(),
            "running_office": running[0] if running else "",
            "running_offices": running,
            "parallel": {"limit": limit, "reason": why},
            "first_run": not tree["offices"],
            "models": [m.get("member") for m in casting.members(router=self._router())][:12],
        }

    def _router(self) -> Any:
        return casting.shared_router()

    # ------------------------------------------------------------------ the main chat

    def say(self, office_id: str, text: str, *, by: str = "owner", by_name: str = "You") -> Dict[str, Any]:
        """The owner's big text box: a new job, or something to say to a job already running.

        ``by_name`` lets an AI Environment world's government sign the projects it hands the office."""
        body = (text or "").strip()
        if not body:
            raise OfficeError("Say what the office should do.")
        office = self.open(office_id)
        self._post(office, Message(id=new_id("msg"), text=body, by=by, by_name=by_name or "You", kind="chat"))
        run = self._runs.get(office_id)
        if run is not None:
            job = office.job(run.job_id)
            if job is not None and job.status == "running":
                self._replies.submit(self._amend, office, job, body)
                return {"queued": True, "job_id": job.id}
        self._check_room(office_id)
        job = self._start_job(office, body)
        return {"queued": False, "job_id": job.id}

    def target(self, office_id: str, text: str, *, selection: Optional[Dict[str, Any]] = None,
               focus_section: str = "") -> Dict[str, Any]:
        """The second chat box: a message aimed at sections, kinds of agent, or named agents."""
        body = (text or "").strip()
        if not body:
            raise OfficeError("Say something to send.")
        office = self.open(office_id)
        aim = targeting.resolve(office, body, selection=selection, focus_section=focus_section)
        if not aim.agent_ids:
            raise OfficeError("Nobody matched that. Click a section or a few agents, or name them "
                              "(\"the coders in every group\", \"managers\", \"Coder #2\").")
        message = Message(id=new_id("msg"), text=aim.message or body, by="owner", by_name="You",
                          to=list(aim.agent_ids), to_label=aim.label, kind="thread")
        self._post(office, message)
        for agent_id in aim.agent_ids:
            agent = office.agent(agent_id)
            if agent is not None:
                agent.inbox.append({"from": "the owner", "text": aim.message or body, "ts": time.time()})
        for agent_id in aim.agent_ids[:MAX_REPLIES_PER_MESSAGE]:
            self._replies.submit(self._reply_to_owner, office, agent_id, aim.message or body, len(aim.agent_ids) - 1)
        self._save(office)
        return {"sent_to": aim.agent_ids, "label": aim.label, "replying": min(len(aim.agent_ids),
                                                                             MAX_REPLIES_PER_MESSAGE)}

    def resolve(self, office_id: str, text: str, *, selection: Optional[Dict[str, Any]] = None,
                focus_section: str = "") -> Dict[str, Any]:
        """Live "who will get this" while the owner types."""
        office = self.open(office_id)
        return targeting.resolve(office, text or "", selection=selection, focus_section=focus_section).as_dict()

    # ------------------------------------------------------------------ control

    def control(self, office_id: str, action: str, *, scope: str = "office", target_id: str = "") -> Dict[str, Any]:
        """Pause, resume or halt — the whole office, one section, or one agent."""
        office = self.open(office_id)
        action = (action or "").strip().lower()
        if action not in ("pause", "resume", "halt"):
            raise OfficeError("Use pause, resume or halt.")
        run = self._runs.get(office_id)

        if scope == "agent":
            agent = office.agent(target_id)
            if agent is None:
                raise OfficeError("That agent is not in this office.")
            agent.status = AGENT_PAUSED if action in ("pause", "halt") else AGENT_IDLE
            agent.step = "Paused by you" if agent.status == AGENT_PAUSED else ""
            self._publish(office, "agent", agent=agent.as_dict())
        elif scope == "section":
            section = office.section(target_id)
            if section is None:
                raise OfficeError("That section is gone.")
            section.status = {"pause": "paused", "halt": "halted", "resume": "active"}[action]
            for agent in office.agents_in(section.id):
                if action == "resume" and agent.status == AGENT_PAUSED:
                    agent.status, agent.step = AGENT_IDLE, ""
                elif action in ("pause", "halt") and agent.status in (AGENT_IDLE, AGENT_WORKING):
                    agent.status, agent.step = AGENT_PAUSED, f"Section {action}d"
                self._publish(office, "agent", agent=agent.as_dict())
            self._publish(office, "section", section=section.as_dict())
        else:
            if action == "pause" and run is not None:
                run.paused.set()
                office.status = OFFICE_PAUSED
            elif action == "resume":
                if run is not None:
                    run.paused.clear()
                office.status = OFFICE_RUNNING if run is not None else OFFICE_IDLE
                for agent in office.agents.values():
                    if agent.status == AGENT_PAUSED:
                        agent.status, agent.step = AGENT_IDLE, ""
            elif action == "halt":
                self._halt(office, run)
            self._publish(office, "office", office=self.snapshot(office_id)["office"])
        self._save(office, force=True)
        return self.snapshot(office_id)

    def _halt(self, office: Office, run: Optional[Run]) -> None:
        if run is not None:
            run.cancel.set()
            run.paused.clear()
            run.pending.clear()
        office.status = OFFICE_HALTED
        job = office.current_job()
        if job is not None:
            job.status, job.ended_at = "stopped", time.time()
        for task in office.tasks.values():
            if task.status in (TASK_QUEUED, TASK_WORKING, TASK_REVIEW):
                task.status, task.ended_at = TASK_CANCELLED, time.time()
        for agent in office.agents.values():
            agent.status, agent.step, agent.task_id = AGENT_IDLE, "", ""
        self._post(office, Message(id=new_id("msg"), text="Halted. Everything stopped where it was; the work that "
                                                          "was already saved is still in the work folder.",
                                   by="office", by_name="Office", kind="chat"))
        with self._lock:
            others = [oid for oid in self._runs if oid != office.id]
        if not others:          # the run itself is cleared when its thread winds down (_finish_job)
            focus.leave()

    # ------------------------------------------------------------------ jobs

    def _check_room(self, office_id: str) -> None:
        """Refuse a new job when as many offices as this PC runs at once are already working (U14)."""
        limit, why = casting.parallel_offices()
        with self._lock:
            others = [oid for oid in self._runs if oid != office_id]
        if len(others) < limit:
            return
        names = []
        for oid in others:
            other = self._offices.get(oid)
            names.append(f"\"{other.name if other else 'Another office'}\"")
        if limit == 1:
            raise OfficeError(f"{names[0]} is working right now. One office runs at a time on this PC — halt that "
                              f"one first. ({why})")
        raise OfficeError(f"{', '.join(names)} are working — {limit} offices at once is this PC's most. Halt one "
                          f"first. ({why})")

    def _start_job(self, office: Office, request: str, *, kind: str = "job") -> Job:
        job = Job(id=new_id("job"), request=request[:6000], kind=kind)
        office.jobs.append(job)
        office.status = OFFICE_RUNNING
        office.goal = request[:200]
        run = Run(office_id=office.id, job_id=job.id)
        with self._lock:
            self._runs[office.id] = run
            together = len(self._runs)
        # Offices working side by side share the machine's model calls; the gates grow with them, the machine's
        # ceiling (casting.capacity) still caps each one.
        talk.GATES.resize(self._capacity(office).concurrency * together)
        mode = str(settings_module.load().get("focus_mode") or "ask")
        if mode == "always" and not focus.held_by(office.id):
            focus.enter(office.id, f"Office Space — {office.name}")
        run.thread = threading.Thread(target=self._run_job, args=(office, job, run), daemon=True,
                                      name=f"office-{office.id[:6]}-{job.id[:6]}")
        run.thread.start()
        self._publish(office, "job", job=job.as_dict())
        return job

    def _run_job(self, office: Office, job: Job, run: Run) -> None:
        try:
            if job.kind == "job":
                self._phase(office, job, "plan")
                plan = self._make_plan(office, job, run)
                if run.cancel.is_set():
                    return
                self._phase(office, job, "staff")
                self._apply_plan(office, job, plan, run)
                self._phase(office, job, "brief")
                self._brief_sections(office, job, run)
            self._phase(office, job, "work")
            self._work_loop(office, job, run)
            if run.cancel.is_set():
                return
            self._phase(office, job, "review")
            reports = self._review(office, job, run, rounds=self._effort(office, "review_rounds", 1, 0, 3))
            if run.cancel.is_set():
                return
            self._phase(office, job, "wrap")
            self._wrap(office, job, reports, run)
        except Exception as error:  # noqa: BLE001 - a failed job is reported, never a dead engine
            job.status, job.error, job.ended_at = "failed", f"{type(error).__name__}: {error}"[:400], time.time()
            self._post(office, Message(id=new_id("msg"), by="office", by_name="Office", kind="chat",
                                       text=f"The office could not finish this one: {job.error}"))
            self._deliver_output(office, job, status="failed", title=job.title or job.request[:80],
                                 text=f"Not finished — {job.error}")
        finally:
            self._finish_job(office, job, run)

    def _finish_job(self, office: Office, job: Job, run: Run) -> None:
        if job.status == "running":
            job.status, job.ended_at = ("stopped" if run.cancel.is_set() else "done"), time.time()
        if job.status == "stopped" and not any(o.job_id == job.id for o in office.outputs):
            # The Output box says plainly that this one is not done, rather than staying silent.
            mine = [t for t in office.tasks.values() if t.job_id == job.id]
            finished = sum(1 for t in mine if t.status == TASK_DONE)
            self._deliver_output(office, job, status="stopped", title=job.title or job.request[:80],
                                 text=f"Stopped before it finished — {finished} of {len(mine)} tasks were done. "
                                      "Press Deliver now for what exists so far.")
        if job.status == "done":
            # The office as a company (U42): part-time, letting go, promotions and demotions after each job.
            for change in staffing.review(office, job):
                self._publish(office, "staffing", change=change.as_dict())
        for agent in office.agents.values():
            if agent.status in (AGENT_WORKING,):
                agent.status, agent.step, agent.task_id = AGENT_IDLE, "", ""
        office.status = OFFICE_IDLE
        office.phase = ""
        self._save(office, force=True)
        self._publish(office, "job", job=job.as_dict())
        try:
            self._publish(office, "office", office=self.snapshot(office.id)["office"])
        except library.LibraryError:
            pass            # the office's folder was moved or deleted while it worked; the run still ends cleanly
        next_request = run.pending.pop(0) if run.pending else ""
        with self._lock:
            if self._runs.get(office.id) is run:
                self._runs.pop(office.id, None)
            last = not self._runs
        if next_request and not run.cancel.is_set():
            self._start_job(office, next_request)
            return
        if last:
            focus.leave()

    def _phase(self, office: Office, job: Job, phase: str) -> None:
        job.phase = phase
        office.phase = phase
        focus.touch()
        self._publish(office, "phase", job=job.as_dict())
        self._save(office)

    # ------------------------------------------------------------------ plan

    def _make_plan(self, office: Office, job: Job, run: Run) -> Dict[str, Any]:
        top = office.top_manager()
        if top is None:
            self._found(office)
            top = office.top_manager()
        assert top is not None
        self._set_agent(office, top, AGENT_WORKING, "Planning the work")
        capacity = self._capacity(office)
        office.capacity = capacity.agents
        question = prompts.plan(office, job.request, capacity=capacity.agents,
                                memory_brief=memory.brief(office.id, job.request),
                                linked=memory.linked_note(office.id))
        answer = talk.ask_lead([{"role": "user", "content": question}],
                               system=prompts.top_manager_system(office), max_tokens=PLAN_TOKENS,
                               timeout=PLAN_TIMEOUT, cancelled=run.cancel.is_set, router=self._router(),
                               turn_id=f"office-{job.id}")
        plan = talk.parse_json(answer.text) if answer.ok else None
        if not isinstance(plan, dict) or not plan.get("sections"):
            plan = self._fallback_plan(office, job, answer)
        job.title = str(plan.get("title") or job.request[:60])[:80]
        job.scale = str(plan.get("scale") or "")[:20]
        reply = str(plan.get("reply") or "").strip()
        if reply:
            self._post(office, Message(id=new_id("msg"), text=reply, by=top.id, by_name=top.name, kind="chat",
                                       job_id=job.id))
        self._set_agent(office, top, AGENT_IDLE, "")
        memory.add(office.id, job.request, kind="request", by="owner", job_id=job.id)
        return plan

    def _fallback_plan(self, office: Office, job: Job, answer: talk.Answer) -> Dict[str, Any]:
        """No usable plan came back — the office still does something sensible rather than nothing."""
        text = job.request.lower()
        wanted: List[str] = []
        for role_id, words in (("coder", ("code", "app", "script", "bug", "build", "api", "function")),
                               ("web-design", ("site", "website", "page", "design", "ui", "css")),
                               ("researcher", ("research", "find", "compare", "sources", "study")),
                               ("writer", ("write", "draft", "copy", "email", "post", "article")),
                               ("data-analyst", ("data", "csv", "numbers", "chart", "spreadsheet"))):
            if any(word in text for word in words):
                wanted.append(role_id)
        wanted = wanted[:3] or ["researcher", "writer"]
        note = f" (the top manager's model did not answer: {answer.error})" if not answer.ok else ""
        return {
            "reply": f"I could not get a full plan back{note}, so I have put a small team on it and we will "
                     "report what we find.",
            "title": job.request[:60], "scale": "small",
            "sections": [{
                "name": "Core Team", "purpose": "Whatever the owner asked for, split between a few agents.",
                "existing": bool(office.section_by_name("Core Team")),
                "team": [{"role": role, "count": 1} for role in wanted] + [{"role": "reviewer", "count": 1}],
                "tasks": [{"title": f"Work on: {job.request[:60]}", "detail": job.request[:1500],
                           "role": wanted[0], "after": []},
                          {"title": "Check the work", "detail": "Read what the others produced and say what is "
                                                                "missing or wrong.", "role": "reviewer",
                           "after": [f"Work on: {job.request[:60]}"]}],
            }],
        }

    # ------------------------------------------------------------------ staff

    def _apply_plan(self, office: Office, job: Job, plan: Dict[str, Any], run: Run) -> None:
        capacity = office.capacity or self._capacity(office).agents
        animate = bool(settings_module.load().get("animate", True))
        sections_raw = [s for s in (plan.get("sections") or []) if isinstance(s, dict)][:MAX_SECTIONS]
        made: List[Tuple[Section, Dict[str, Any]]] = []
        pace = min(0.06, STAFF_ANIMATION_BUDGET / max(1, sum(
            1 + sum(int(t.get("count") or 1) for t in (s.get("team") or []) if isinstance(t, dict))
            for s in sections_raw))) if animate else 0.0

        for raw in sections_raw:
            if run.cancel.is_set():
                return
            name = str(raw.get("name") or "").strip()[:40]
            if not name:
                continue
            section = office.section_by_name(name)
            if section is None:
                if len(office.sections) >= MAX_SECTIONS:
                    continue
                section = self._make_section(office, name, str(raw.get("purpose") or "")[:300], job_id=job.id,
                                             pace=pace)
            elif raw.get("purpose") and not section.purpose:
                section.purpose = str(raw["purpose"])[:300]
            if section.id not in job.section_ids:
                job.section_ids.append(section.id)
            if not office.manager_of(section.id):
                manager = self._add_agent(office, section.id, SECTION_MANAGER, pace=pace)
                section.manager_id = manager.id
            for wanted in (raw.get("team") or [])[:12]:
                if not isinstance(wanted, dict) or run.cancel.is_set():
                    continue
                role_id = self._role_id_for(office, str(wanted.get("role") or ""), why=str(raw.get("why") or ""))
                try:
                    count = max(1, min(int(wanted.get("count") or 1), MAX_AGENTS_PER_SECTION))
                except (TypeError, ValueError):
                    count = 1
                have = sum(1 for a in office.agents_in(section.id) if a.role == role_id)
                for _ in range(max(0, count - have)):
                    if len(office.agents) >= capacity or len(office.agents_in(section.id)) >= MAX_AGENTS_PER_SECTION:
                        break
                    self._add_agent(office, section.id, role_id, pace=pace)
            made.append((section, raw))

        for section, raw in made:
            for item in (raw.get("tasks") or [])[:40]:
                if not isinstance(item, dict):
                    continue
                if len(job.task_ids) >= MAX_TASKS_PER_JOB:
                    break
                title = str(item.get("title") or "").strip()[:120]
                if not title:
                    continue
                task = Task(id=new_id("tsk"), title=title, detail=str(item.get("detail") or "")[:4000],
                            section_id=section.id, role=self._role_id_for(office, str(item.get("role") or "")),
                            job_id=job.id, created_by=office.top_manager().id if office.top_manager() else "office")
                task.after = [str(a) for a in (item.get("after") or []) if isinstance(a, str)][:6]
                office.tasks[task.id] = task
                job.task_ids.append(task.id)
                self._publish(office, "task", task=task.as_dict())
        self._resolve_after(office, job)

        for link in (plan.get("links") or [])[:6]:
            if not isinstance(link, dict):
                continue
            self._make_liaison(office, job, str(link.get("from") or ""), str(link.get("to") or ""),
                               str(link.get("why") or ""))
        office.capacity = capacity
        self._save(office, force=True)

    def _resolve_after(self, office: Office, job: Job) -> None:
        """The planner writes "after" as task titles; turn them into ids (and drop the ones that do not exist)."""
        by_title = {t.title.lower(): t.id for t in office.tasks.values() if t.job_id == job.id}
        for task_id in job.task_ids:
            task = office.tasks.get(task_id)
            if task is None:
                continue
            task.after = [by_title.get(str(a).lower(), a if a in office.tasks else "") for a in task.after]
            task.after = [a for a in task.after if a and a != task.id]

    def _make_section(self, office: Office, name: str, purpose: str = "", *, job_id: str = "",
                      pace: float = 0.0) -> Section:
        used = {s.color for s in office.sections.values()}
        color = next((c for c in SECTION_COLORS if c not in used), SECTION_COLORS[len(office.sections) % len(SECTION_COLORS)])
        section = Section(id=new_id("sec"), name=name[:40], color=color, purpose=purpose[:300], job_id=job_id,
                          order=len(office.sections))
        office.sections[section.id] = section
        self._publish(office, "section.created", section=section.as_dict())
        if pace:
            time.sleep(pace * 2)
        return section

    def _add_agent(self, office: Office, section_id: str, role_id: str, *, member: str = "", origin: str = "hired",
                   pace: float = 0.0) -> Agent:
        role = role_module.get(role_id) or role_module.invent(role_id)
        same = sum(1 for a in office.agents.values() if a.role == role.id)
        agent = Agent(id=new_id("agt"), name=f"{role.title} #{same + 1}" if role.kind != "manager" or same else role.title,
                      role=role.id, section_id=section_id,
                      member=member or self._casting.pick(role.id), origin=origin,
                      desk=len(office.agents_in(section_id)))
        if role.id == SECTION_MANAGER:
            section = office.section(section_id)
            agent.name = f"{section.name} Manager" if section else f"Manager #{same + 1}"
        office.agents[agent.id] = agent
        self._publish(office, "agent.created", agent=agent.as_dict())
        if pace:
            time.sleep(pace)
        return agent

    def _role_id_for(self, office: Office, words: str, *, why: str = "", exact: bool = False,
                     domain: str = "") -> str:
        """A role id for what the planner asked for, inventing a kind (and a sub-agent) when it is genuinely new."""
        text = (words or "").strip()
        if not text:
            return "coder"
        role = role_module.get(text) if exact else role_module.find(text)
        if role is not None:
            return role.id
        invented = role_module.invent(text, goal=why or f"Work as {text} in this office.", domain=domain, exact=exact)
        if not any(r.get("id") == invented.id for r in office.invented_roles):
            office.invented_roles.append(invented.as_dict())
            note = role_module.add_to_subagents(invented, office.name)
            self._post(office, Message(id=new_id("msg"), by="office", by_name="Office", kind="system",
                                       text=f"New kind of agent: {invented.title}. {note}"))
            self._publish(office, "role.created", role=invented.as_dict())
            self._maybe_wake_gatekeeper(office)
        return invented.id

    def _make_liaison(self, office: Office, job: Job, from_name: str, to_name: str, why: str) -> None:
        """*"they can bring in agents specifically for communication where they talk to the specific agent they want to."*"""
        source, target = office.section_by_name(from_name), office.section_by_name(to_name)
        if source is None or target is None or source.id == target.id:
            return
        if len(office.agents) >= (office.capacity or 999):
            return
        agent = self._add_agent(office, source.id, LIAISON)
        agent.note = f"Speaks for {source.name} to {target.name}: {why[:200]}"
        task = Task(id=new_id("tsk"), title=f"Agree with {target.name}: {why[:60] or 'how the two sections fit'}",
                    detail=(f"You are the link between {source.name} and {target.name}. {why[:600]}\n"
                            f"Use message() to ask the {target.name} manager what they need from us and tell them "
                            "what we need from them, then report what was agreed."),
                    section_id=source.id, role=LIAISON, agent_id=agent.id, job_id=job.id, created_by=agent.id)
        office.tasks[task.id] = task
        job.task_ids.append(task.id)
        self._publish(office, "task", task=task.as_dict())

    def _maybe_wake_gatekeeper(self, office: Office) -> None:
        reason = gatekeeper.wake_reason(office)
        if not reason:
            return
        section = office.section_by_name(HEAD_OFFICE) or next(iter(office.sections.values()), None)
        if section is None:
            return
        board = self._add_agent(office, section.id, HIRING_BOARD, origin="founding")
        office.gatekeeper_id = board.id
        board.note = reason
        self._post(office, Message(id=new_id("msg"), by="office", by_name="Office", kind="chat",
                                   text=f"**The Hiring Board has been brought in.** {reason} It answers every "
                                        "request for a new agent with the Crit think skill, and you can see each "
                                        "decision under Hiring."))
        self._publish(office, "gatekeeper", agent=board.as_dict(), reason=reason)

    # ------------------------------------------------------------------ brief

    def _brief_sections(self, office: Office, job: Job, run: Run) -> None:
        sections = [office.section(sid) for sid in job.section_ids if office.section(sid)]
        pool = ThreadPoolExecutor(max_workers=max(2, min(6, len(sections) or 1)), thread_name_prefix="office-brief")
        try:
            futures = [pool.submit(self._brief_one, office, job, section, run) for section in sections]
            for future in futures:
                try:
                    future.result(timeout=MANAGER_TIMEOUT + 60)
                except Exception:  # noqa: BLE001 - a manager that fails falls back to round-robin below
                    continue
        finally:
            pool.shutdown(wait=False)
        # Anything still unassigned is handed out by the office itself, so no task can be orphaned.
        for task_id in job.task_ids:
            task = office.tasks.get(task_id)
            if task is not None and task.status == TASK_QUEUED and not task.agent_id:
                agent = self._pick_agent(office, task)
                if agent is not None:
                    task.agent_id = agent.id
        self._save(office, force=True)

    def _brief_one(self, office: Office, job: Job, section: Section, run: Run) -> None:
        manager = office.manager_of(section.id)
        tasks = [office.tasks[t] for t in job.task_ids
                 if t in office.tasks and office.tasks[t].section_id == section.id
                 and office.tasks[t].status == TASK_QUEUED]
        if manager is None or not tasks:
            return
        self._set_agent(office, manager, AGENT_WORKING, "Handing out the work")
        answer = talk.ask(manager.member, [{"role": "user", "content": prompts.brief(office, section, tasks)}],
                          system=prompts.manager_system(office, section, manager), max_tokens=MANAGER_TOKENS,
                          timeout=MANAGER_TIMEOUT, cancelled=run.cancel.is_set, router=self._router())
        data = talk.parse_json(answer.text) if answer.ok else None
        if isinstance(data, dict):
            by_title = {t.title.lower(): t for t in tasks}
            for item in (data.get("assignments") or [])[:60]:
                if not isinstance(item, dict):
                    continue
                task = by_title.get(str(item.get("task") or "").strip().lower())
                agent = office.by_name(str(item.get("agent") or ""))
                if task is None or agent is None or agent.section_id != section.id:
                    continue
                task.agent_id = agent.id
                extra = str(item.get("detail") or "").strip()
                if extra:
                    task.detail = f"{task.detail}\n\nFrom {manager.name}: {extra}"[:4000]
                self._publish(office, "task", task=task.as_dict())
            for item in (data.get("extra_tasks") or [])[:12]:
                if not isinstance(item, dict) or len(job.task_ids) >= MAX_TASKS_PER_JOB:
                    continue
                title = str(item.get("title") or "").strip()[:120]
                if not title:
                    continue
                agent = office.by_name(str(item.get("agent") or ""))
                task = Task(id=new_id("tsk"), title=title, detail=str(item.get("detail") or "")[:3000],
                            section_id=section.id, role=self._role_id_for(office, str(item.get("role") or "")),
                            agent_id=agent.id if agent and agent.section_id == section.id else "",
                            job_id=job.id, created_by=manager.id)
                office.tasks[task.id] = task
                job.task_ids.append(task.id)
                self._publish(office, "task", task=task.as_dict())
            for item in (data.get("hire") or [])[:4]:
                if not isinstance(item, dict):
                    continue
                self.agent_hire(office, manager, role=str(item.get("role") or ""), why=str(item.get("why") or ""),
                                long_term=str(item.get("long_term") or ""),
                                count=int(item.get("count") or 1) if str(item.get("count") or "1").isdigit() else 1,
                                clone_of=str(item.get("clone_of") or ""), section_id=section.id)
            note = str(data.get("note") or "").strip()
            if note:
                section.notes = note[:600]
        self._set_agent(office, manager, AGENT_IDLE, "")

    # ------------------------------------------------------------------ work

    def _ready_tasks(self, office: Office, job: Job) -> List[Task]:
        ready: List[Task] = []
        for task_id in list(job.task_ids):
            task = office.tasks.get(task_id)
            if task is None or task.status != TASK_QUEUED:
                continue
            section = office.section(task.section_id)
            if section is not None and section.status in ("paused", "halted"):
                continue
            blocked = any(office.tasks.get(a) is not None and office.tasks[a].status not in (TASK_DONE, TASK_FAILED,
                                                                                             TASK_CANCELLED)
                          for a in task.after)
            if not blocked:
                ready.append(task)
        return ready

    def _pick_agent(self, office: Office, task: Task) -> Optional[Agent]:
        pool = [a for a in office.agents_in(task.section_id)
                if a.status == AGENT_IDLE and a.role not in (SECTION_MANAGER, TOP_MANAGER, HIRING_BOARD)]
        same_role = [a for a in pool if a.role == task.role]
        if same_role:
            return min(same_role, key=lambda a: a.tasks_done)
        if pool:
            return min(pool, key=lambda a: a.tasks_done)
        # Nobody free with the right skill: bring one in if there is room, else wait for a desk.
        if len(office.agents) < (office.capacity or 0) and len(office.agents_in(task.section_id)) < MAX_AGENTS_PER_SECTION:
            return self._add_agent(office, task.section_id, task.role or "coder")
        return None

    def _work_loop(self, office: Office, job: Job, run: Run) -> None:
        capacity = self._capacity(office)
        pool = ThreadPoolExecutor(max_workers=max(2, min(40, capacity.concurrency * 3)),
                                  thread_name_prefix="office-work")
        running: Dict[Future, str] = {}
        try:
            while not run.cancel.is_set():
                if run.paused.is_set():
                    time.sleep(0.4)
                    continue
                for task in self._ready_tasks(office, job):
                    if len(running) >= capacity.concurrency * 3:
                        break
                    agent = office.agent(task.agent_id) if task.agent_id else None
                    if agent is None or agent.status != AGENT_IDLE:
                        if agent is not None and agent.status in (AGENT_WORKING, AGENT_PAUSED):
                            continue
                        agent = self._pick_agent(office, task)
                    if agent is None:
                        continue
                    task.agent_id = agent.id
                    task.status = TASK_WORKING
                    agent.status, agent.task_id = AGENT_WORKING, task.id
                    self._publish(office, "task", task=task.as_dict())
                    running[pool.submit(self._do_task, office, job, agent, task, run)] = task.id
                done = [f for f in running if f.done()]
                for future in done:
                    running.pop(future, None)
                    try:
                        future.result()
                    except Exception:  # noqa: BLE001 - recorded on the task itself
                        pass
                if not running and not self._ready_tasks(office, job):
                    break
                focus.touch()
                self._save(office)
                time.sleep(0.25)
        finally:
            pool.shutdown(wait=False)
            for future in running:
                future.cancel()

    def _do_task(self, office: Office, job: Job, agent: Agent, task: Task, run: Run) -> None:
        """One agent doing one task: think, use its tools, report back."""
        started = time.perf_counter()
        task.started_at = time.time()
        task.tries += 1
        allow_web = bool(settings_module.load().get("allow_web", True))
        section = office.section(task.section_id)
        box = officetools.Toolbox(self, office, agent, task, allow_web=allow_web)
        system = prompts.worker_system(office, section, agent, allow_web=allow_web)
        depends = [office.tasks[a] for a in task.after if a in office.tasks]
        inbox, agent.inbox = list(agent.inbox), []
        history: List[Dict[str, Any]] = [{"role": "user", "content": prompts.worker_task(
            office, agent, task, depends=depends, memory_brief=memory.brief(office.id, task.title + " " + task.detail,
                                                                            limit=4), inbox=inbox)}]
        report, error = "", ""
        member = agent.member or self._casting.pick(agent.role)
        steps = self._effort(office, "worker_steps", MAX_WORKER_STEPS, 2, 8)
        for step in range(1, steps + 1):
            if run.cancel.is_set():
                error = "stopped"
                break
            while run.paused.is_set() and not run.cancel.is_set():
                self._set_agent(office, agent, AGENT_PAUSED, "Paused")
                time.sleep(0.5)
            if agent.status == AGENT_PAUSED:
                self._set_agent(office, agent, AGENT_WORKING, "Back to work")
            self._set_agent(office, agent, AGENT_WORKING,
                            f"Thinking with {talk.split_member(member)[1] or talk.split_member(member)[0] or 'a model'}")
            answer = talk.ask(member, history, system=system, max_tokens=WORKER_TOKENS, timeout=WORKER_TIMEOUT,
                              cancelled=run.cancel.is_set, router=self._router())
            if not answer.ok:
                other = self._casting.pick(agent.role, avoid=member)
                if other and other != member and step == 1:
                    member, agent.member = other, other   # a model that is down costs a retry, not the task
                    self._publish(office, "agent", agent=agent.as_dict())
                    continue
                error = answer.error or "no answer"
                break
            calls = officetools.parse_calls(answer.text)
            if not calls:
                report = answer.clean
                break
            history.append({"role": "assistant", "content": answer.text})
            results = []
            for name, arguments in calls[:4]:
                self._set_agent(office, agent, AGENT_WORKING, self._step_words(name, arguments))
                results.append(f"{name} → {box.run(name, arguments)}")
            history.append({"role": "user", "content": "Tool results:\n" + "\n\n".join(results) +
                                                       "\n\nCarry on, or write your report."})
            if step == steps:
                history.append({"role": "user", "content": "Write your report now — no more tools."})
                final = talk.ask(member, history, system=system, max_tokens=WORKER_TOKENS, timeout=WORKER_TIMEOUT,
                                 cancelled=run.cancel.is_set, router=self._router())
                report = final.clean if final.ok else ""
                error = "" if final.ok else (final.error or "no answer")

        seconds = round(time.perf_counter() - started, 1)
        task.ended_at = time.time()
        task.files = list(box.files)
        if report.strip():
            task.result = report.strip()
            task.report_path = self._write_report(office, task, agent, report)
            task.status = TASK_DONE
            agent.tasks_done += 1
        else:
            task.result = f"No report: {error or 'the agent said nothing'}"
            task.status = TASK_FAILED
            agent.errors += 1
        task.trim()
        agent.seconds = round(agent.seconds + seconds, 1)
        agent.task_id = ""
        self._set_agent(office, agent, AGENT_IDLE if task.status == TASK_DONE else AGENT_ERROR,
                        "Reported back" if task.status == TASK_DONE else f"Could not finish: {error[:60]}")
        if agent.status == AGENT_ERROR:
            agent.status = AGENT_IDLE            # an error is a state of the task, not a broken agent
        self._publish(office, "task", task=task.as_dict())
        casting.record_use(agent.role, task.status == TASK_DONE, seconds, agent.member)
        self._post(office, Message(id=new_id("msg"), by=agent.id, by_name=agent.name, kind="report",
                                   section_id=task.section_id, job_id=job.id,
                                   text=f"{task.title} — {task.result[:400]}"))
        self._save(office)

    @staticmethod
    def _step_words(name: str, arguments: Dict[str, Any]) -> str:
        if name == "write_file":
            return f"Writing {str(arguments.get('path', 'a file'))[:40]}"
        if name == "read_file":
            return f"Reading {str(arguments.get('path', 'a file'))[:40]}"
        if name == "search_web":
            return f"Looking up {str(arguments.get('query', ''))[:40]}"
        if name == "read_link":
            return "Reading a page"
        if name == "message":
            return f"Talking to {str(arguments.get('to', 'someone'))[:30]}"
        if name == "delegate":
            return f"Handing work to {str(arguments.get('to', 'someone'))[:30]}"
        if name == "hire":
            return f"Asking for {str(arguments.get('role', 'an agent'))[:30]}"
        return {"recall": "Checking what the office knows", "note": "Keeping a note",
                "list_files": "Checking the work folder"}.get(name, name.replace("_", " ").title())

    def _write_report(self, office: Office, task: Task, agent: Agent, report: str) -> str:
        try:
            folder = library.work_dir(office.id) / "_reports"
            folder.mkdir(parents=True, exist_ok=True)
            name = officetools.safe_relative(f"{task.title[:50]}-{task.id}.md")
            path = folder / name
            section = office.section(task.section_id)
            path.write_text(f"# {task.title}\n\n*{agent.name} · {section.name if section else ''} · "
                            f"{time.strftime('%Y-%m-%d %H:%M')}*\n\n{report}\n", encoding="utf-8")
            return f"_reports/{name}"
        except OSError:
            return ""

    # ------------------------------------------------------------------ review

    def _review(self, office: Office, job: Job, run: Run, *, rounds: int = 1) -> List[Dict[str, Any]]:
        reports: List[Dict[str, Any]] = []
        for attempt in range(rounds + 1):
            fixes: List[Task] = []
            reports = []
            for section_id in job.section_ids:
                section = office.section(section_id)
                if section is None or run.cancel.is_set():
                    continue
                done = [office.tasks[t] for t in job.task_ids
                        if t in office.tasks and office.tasks[t].section_id == section_id
                        and office.tasks[t].status in (TASK_DONE, TASK_FAILED)]
                if not done:
                    continue
                outcome = self._review_one(office, job, section, done, run)
                reports.append({"section": section.name, "text": outcome["report"]})
                fixes.extend(outcome["fixes"])
            if not fixes or attempt >= rounds or run.cancel.is_set():
                break
            for task in fixes:
                task.status, task.result, task.ended_at = TASK_QUEUED, "", 0.0
                self._publish(office, "task", task=task.as_dict())
            self._phase(office, job, "work")
            self._work_loop(office, job, run)
            self._phase(office, job, "review")
        return reports

    def _review_one(self, office: Office, job: Job, section: Section, done: Sequence[Task],
                    run: Run) -> Dict[str, Any]:
        manager = office.manager_of(section.id)
        fallback = "\n\n".join(f"**{t.title}** — {t.result[:600]}" for t in done)
        if manager is None:
            return {"report": fallback, "fixes": []}
        self._set_agent(office, manager, AGENT_WORKING, "Reviewing the work")
        answer = talk.ask(manager.member, [{"role": "user", "content": prompts.review(office, section, done)}],
                          system=prompts.manager_system(office, section, manager), max_tokens=MANAGER_TOKENS,
                          timeout=MANAGER_TIMEOUT, cancelled=run.cancel.is_set, router=self._router())
        self._set_agent(office, manager, AGENT_IDLE, "")
        data = talk.parse_json(answer.text) if answer.ok else None
        if not isinstance(data, dict):
            return {"report": fallback, "fixes": []}
        fixes: List[Task] = []
        by_title = {t.title.lower(): t for t in done}
        for item in (data.get("fixes") or [])[:3]:
            if not isinstance(item, dict):
                continue
            task = by_title.get(str(item.get("task") or "").strip().lower())
            if task is None or task.tries > 1:
                continue
            task.feedback = str(item.get("feedback") or "")[:800]
            fixes.append(task)
        note = str(data.get("note") or "").strip()
        if note:
            section.notes = note[:600]
        report = str(data.get("report") or "").strip() or fallback
        self._post(office, Message(id=new_id("msg"), by=manager.id, by_name=manager.name, kind="report",
                                   section_id=section.id, job_id=job.id, text=report[:1200]))
        return {"report": report, "fixes": fixes}

    # ------------------------------------------------------------------ wrap

    def _wrap(self, office: Office, job: Job, reports: Sequence[Dict[str, Any]], run: Run) -> None:
        top = office.top_manager()
        files = sorted({f for t in office.tasks.values() if t.job_id == job.id for f in t.files})
        if top is None:
            job.reply = "\n\n".join(r["text"] for r in reports)
            return
        self._set_agent(office, top, AGENT_WORKING, "Writing the answer")
        answer = talk.ask_lead([{"role": "user", "content": prompts.wrap(office, job, reports=reports, files=files,
                                                                          file_texts=self._small_files(office, files))}],
                               system=prompts.top_manager_system(office), max_tokens=PLAN_TOKENS,
                               timeout=PLAN_TIMEOUT, cancelled=run.cancel.is_set, router=self._router())
        data = talk.parse_json(answer.text) if answer.ok else None
        reply = ""
        if isinstance(data, dict):
            reply = str(data.get("reply") or "").strip()
            job.summary = str(data.get("summary") or "")[:1200]
            if job.summary:
                memory.add(office.id, job.summary, kind="summary", by=top.name, job_id=job.id)
            for decision in (data.get("decisions") or [])[:6]:
                memory.add(office.id, str(decision)[:500], kind="decision", by=top.name, job_id=job.id)
            for fact in (data.get("facts") or [])[:8]:
                memory.add(office.id, str(fact)[:500], kind="fact", by=top.name, job_id=job.id)
            open_items = [str(o)[:200] for o in (data.get("open") or [])[:6]]
            if open_items:
                memory.add(office.id, "Still open: " + "; ".join(open_items), kind="note", by=top.name, job_id=job.id)
        if not reply:
            reply = ("Here is what the office produced:\n\n"
                     + "\n\n".join(f"**{r['section']}**\n{r['text'][:1200]}" for r in reports))
            if not reports:
                reply = f"The office could not finish this one. {answer.error or ''}".strip()
        if files:
            reply += "\n\n**Files in this office's work folder:** " + ", ".join(files[:20])
        job.reply = reply[:8000]
        self._post(office, Message(id=new_id("msg"), by=top.id, by_name=top.name, kind="chat", job_id=job.id,
                                   text=job.reply))
        output = str(data.get("output") or "").strip() if isinstance(data, dict) else ""
        self._deliver_output(office, job, status="done" if reports else "failed", title=job.title or job.request[:80],
                             text=output or job.reply, files=files, by=top)
        self._set_agent(office, top, AGENT_IDLE, "")

    # ------------------------------------------------------------------ the Output box (Update 1, U41)

    _URL = re.compile(r"https?://[^\s<>()\[\]\"']+[^\s<>()\[\]\"'.,;:!?]")

    def _deliver_output(self, office: Office, job: Job, *, status: str, title: str, text: str,
                        files: Sequence[str] = (), by: Optional[Agent] = None) -> Output:
        """Put a result in the Output box: the deliverable, its files (opened in the app) and the links in it."""
        links: List[Dict[str, str]] = []
        for path in list(files)[:30]:
            links.append({"kind": "file", "label": path.split("/")[-1] or path, "path": path})
        for url in list(dict.fromkeys(self._URL.findall(text or "")))[:20]:
            links.append({"kind": "url", "label": url.split("//", 1)[-1][:80], "href": url})
        output = office.add_output(Output(id=new_id("out"), title=(title or "Result").strip()[:160], text=(text or "")[:20000],
                                          status=status, links=links, job_id=job.id,
                                          by=by.id if by else "office", by_name=by.name if by else "Office"))
        self._publish(office, "output", output=output.as_dict())
        self._save(office, force=True)
        return output

    @staticmethod
    def _small_files(office: Office, files: Sequence[str], *, each: int = 3000, total: int = 9000) -> Dict[str, str]:
        """The text of the small files a job produced, so the Output box quotes them instead of a model's retelling.

        Found live: asked for a haiku saved as haiku.txt, the office saved one poem and the Output box showed a
        different one, because the top manager only knew the file's name.
        """
        out: Dict[str, str] = {}
        try:
            work = library.work_dir(office.id)
        except Exception:  # noqa: BLE001 - no folder, nothing to quote
            return out
        used = 0
        for name in list(files)[:8]:
            path = work / officetools.safe_relative(name)
            try:
                if not path.is_file() or path.stat().st_size > each * 4:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")[:each]
            except OSError:
                continue
            if used + len(text) > total:
                break
            out[name] = text
            used += len(text)
        return out

    def deliver_now(self, office_id: str) -> Dict[str, Any]:
        """The Deliver now button: the office hands over what it has, even mid-job, without stopping the work."""
        office = self.open(office_id)
        job = office.current_job() or (office.jobs[-1] if office.jobs else None)
        if job is None:
            raise OfficeError("Nothing to deliver yet — give the office a job first.")
        running = job.status == "running"
        threading.Thread(target=self._deliver_now, args=(office, job, running), daemon=True,
                         name=f"office-deliver-{office.id[:6]}").start()
        self._post(office, Message(id=new_id("msg"), by="office", by_name="Office", kind="system", job_id=job.id,
                                   text="You asked for the output now — it will land in the Output box."))
        return self.snapshot(office_id)

    def _deliver_now(self, office: Office, job: Job, running: bool) -> None:
        done = [t for t in office.tasks.values() if t.job_id == job.id and t.status == TASK_DONE]
        reports = [{"section": (office.section(t.section_id).name if office.section(t.section_id) else "Office"),
                    "text": f"{t.title}: {t.result}"} for t in done]
        files = sorted({f for t in office.tasks.values() if t.job_id == job.id for f in t.files})
        top = office.top_manager()
        try:
            answer = talk.ask_lead([{"role": "user", "content": prompts.deliver(office, job, reports=reports, files=files,
                                                                                   running=running,
                                                                                   file_texts=self._small_files(office, files))}],
                                   system=prompts.top_manager_system(office), max_tokens=PLAN_TOKENS,
                                   timeout=PLAN_TIMEOUT, router=self._router())
            data = talk.parse_json(answer.text) if answer.ok else None
        except Exception as error:  # noqa: BLE001 - the button must always answer
            answer, data = None, None
            reports = reports or [{"section": "Office", "text": f"Could not write the output: {error}"}]
        if isinstance(data, dict) and str(data.get("output") or "").strip():
            text = str(data["output"]).strip()
            title = str(data.get("title") or job.title or job.request[:80])
            status = "done" if (data.get("complete") and not running) else "partial"
        elif job.reply and not running:
            text, title, status = job.reply, job.title or job.request[:80], "done"
        else:
            text = "\n\n".join(f"**{r['section']}** — {r['text'][:1500]}" for r in reports) or \
                "Nothing is finished yet. The office is still on its first tasks."
            title, status = job.title or job.request[:80], "partial"
        self._deliver_output(office, job, status=status, title=title, text=text, files=files, by=top)

    def set_options(self, office_id: str, *, auto_decisions: Optional[bool] = None,
                    review_rounds: Optional[int] = None, worker_steps: Optional[int] = None) -> Dict[str, Any]:
        """This office's own switches. Auto decisions: decide everything and produce the real result (U42).

        ``review_rounds`` and ``worker_steps`` are its effort — how many times managers may send work back, and how
        many tool steps a worker gets. An AI Environment world sets them from its speed (U38)."""
        office = self.open(office_id)
        if auto_decisions is not None:
            office.settings["auto_decisions"] = bool(auto_decisions)
        if review_rounds is not None:
            office.settings["review_rounds"] = max(0, min(3, int(review_rounds)))
        if worker_steps is not None:
            office.settings["worker_steps"] = max(2, min(8, int(worker_steps)))
        self._save(office, force=True)
        snapshot = self.snapshot(office_id)
        self._publish(office, "office", office=snapshot["office"])
        return snapshot

    @staticmethod
    def _effort(office: Office, key: str, default: int, low: int, high: int) -> int:
        try:
            return max(low, min(high, int(office.settings.get(key, default))))
        except (TypeError, ValueError):
            return default

    # ------------------------------------------------------------------ for the AI Environment (world/)

    def add_section(self, office_id: str, name: str, purpose: str = "", *, with_manager: bool = True) -> Dict[str, Any]:
        """A new section with its manager — how a world founds a start-up (U36)."""
        office = self.open(office_id)
        clean = (name or "").strip()[:40]
        if not clean:
            raise OfficeError("Give the section a name.")
        existing = office.section_by_name(clean)
        if existing is not None and existing.name.lower() == clean.lower():
            return existing.as_dict()
        section = self._make_section(office, clean, purpose)
        if with_manager:
            manager = self._add_agent(office, section.id, SECTION_MANAGER, origin="founding")
            section.manager_id = manager.id
            self._publish(office, "section", section=section.as_dict())
        self._save(office, force=True)
        return section.as_dict()

    def add_agent(self, office_id: str, section_id: str, role_words: str, *, origin: str = "hired",
                  why: str = "", exact: bool = False, domain: str = "") -> Dict[str, Any]:
        """One more agent at a desk, its kind found or invented from plain words — how a world's bots have a child
        ("finance" + "coder" → a Finance Coder, U35; ``exact`` keeps that a new kind) or bring a retired one back."""
        office = self.open(office_id)
        if office.section(section_id) is None:
            raise OfficeError("That section is gone.")
        if len(office.agents) >= max(1, office.capacity or self._capacity(office).agents):
            raise OfficeError("The office is full — this computer cannot hold another agent right now.")
        role_id = self._role_id_for(office, role_words, why=why, exact=exact, domain=domain)
        agent = self._add_agent(office, section_id, role_id, origin=origin)
        self._save(office, force=True)
        return agent.as_dict()

    # ------------------------------------------------------------------ amendments and replies

    def _amend(self, office: Office, job: Job, request: str) -> None:
        top = office.top_manager()
        run = self._runs.get(office.id)
        if top is None or run is None:
            return
        self._set_agent(office, top, AGENT_WORKING, "Reading what you said")
        answer = talk.ask_lead([{"role": "user", "content": prompts.amend(office, request, job=job)}],
                               system=prompts.top_manager_system(office), max_tokens=MANAGER_TOKENS,
                               timeout=MANAGER_TIMEOUT, cancelled=run.cancel.is_set, router=self._router())
        data = talk.parse_json(answer.text) if answer.ok else None
        self._set_agent(office, top, AGENT_IDLE, "")
        if not isinstance(data, dict):
            self._post(office, Message(id=new_id("msg"), by=top.id, by_name=top.name, kind="chat",
                                       text="I could not read that while the office is working — say it again when "
                                            "this job finishes, or halt it first."))
            return
        if data.get("stop"):
            self._halt(office, run)
            return
        reply = str(data.get("reply") or "").strip()
        if reply:
            self._post(office, Message(id=new_id("msg"), by=top.id, by_name=top.name, kind="chat", text=reply,
                                       job_id=job.id))
        for raw in (data.get("new_sections") or [])[:3]:
            if isinstance(raw, dict):
                self._apply_plan(office, job, {"sections": [raw]}, run)
        added = 0
        for item in (data.get("add_tasks") or [])[:20]:
            if not isinstance(item, dict) or len(job.task_ids) >= MAX_TASKS_PER_JOB:
                continue
            section = office.section_by_name(str(item.get("section") or "")) or next(
                (office.section(s) for s in job.section_ids if office.section(s)), None)
            title = str(item.get("title") or "").strip()[:120]
            if section is None or not title:
                continue
            task = Task(id=new_id("tsk"), title=title, detail=str(item.get("detail") or "")[:3000],
                        section_id=section.id, role=self._role_id_for(office, str(item.get("role") or "")),
                        job_id=job.id, created_by="owner")
            office.tasks[task.id] = task
            job.task_ids.append(task.id)
            self._publish(office, "task", task=task.as_dict())
            added += 1
        if added and job.phase in ("review", "wrap"):
            self._phase(office, job, "work")
            self._work_loop(office, job, run)
        self._save(office)

    def _reply_to_owner(self, office: Office, agent_id: str, text: str, others: int) -> None:
        """An agent answering a message from the second chat box."""
        agent = office.agent(agent_id)
        if agent is None:
            return
        section = office.section(agent.section_id)
        previous = agent.status
        self._set_agent(office, agent, AGENT_WORKING, "Reading your message")
        answer = talk.ask(agent.member, [{"role": "user", "content": prompts.message_reply(
            office, agent, text, from_name="The owner", others=others)}],
            system=prompts.worker_system(office, section, agent,
                                         allow_web=bool(settings_module.load().get("allow_web", True))),
            max_tokens=500, timeout=90, router=self._router())
        self._set_agent(office, agent, previous if previous != AGENT_WORKING else AGENT_IDLE, "")
        if not answer.ok:
            return
        reply = answer.clean
        tasks = list(_TASK_LINE.finditer(reply))
        clean_reply = _TASK_LINE.sub("", reply).strip()
        self._post(office, Message(id=new_id("msg"), by=agent.id, by_name=agent.name, kind="thread",
                                   section_id=agent.section_id, text=clean_reply[:1500]))
        for match in tasks[:2]:
            task = Task(id=new_id("tsk"), title=match.group("title").strip()[:120],
                        detail=match.group("detail").strip()[:2000], section_id=agent.section_id,
                        role=agent.role, agent_id=agent.id, created_by="owner")
            office.tasks[task.id] = task
            self._publish(office, "task", task=task.as_dict())
            self._queue_adhoc(office, task)
        self._save(office)

    def _queue_adhoc(self, office: Office, task: Task) -> None:
        """Work that came out of the targeted chat: run it now if the office is otherwise idle."""
        run = self._runs.get(office.id)
        if run is not None:
            job = office.job(run.job_id)
            if job is not None and job.status == "running":
                task.job_id = job.id
                job.task_ids.append(task.id)
                return
        self._check_room(office.id)
        job = self._start_job(office, task.title, kind="ad-hoc")
        task.job_id = job.id
        job.task_ids.append(task.id)

    # ------------------------------------------------------------------ what the tools call

    def on_file_written(self, office: Office, agent: Agent, path: str) -> None:
        self._publish(office, "file", path=path, by=agent.name, agent_id=agent.id)

    def agent_message(self, office: Office, agent: Agent, to: str, text: str) -> str:
        """One agent talking to another — the lines the floor draws between desks."""
        if not text.strip():
            return "Nothing was sent: the message was empty."
        ids = targeting.liaison_targets(office, to)
        ids = [i for i in ids if i != agent.id][:12]
        if not ids:
            return (f"Nobody here matches {to!r}. Use an agent's name, a section name, or a kind of agent "
                    "(\"the Backend manager\", \"reviewers\").")
        for agent_id in ids:
            other = office.agent(agent_id)
            if other is not None:
                other.inbox.append({"from": agent.name, "text": text[:1500], "ts": time.time()})
        label = targeting.describe(office, ids)
        self._post(office, Message(id=new_id("msg"), by=agent.id, by_name=agent.name, to=ids, to_label=label,
                                   kind="liaison", section_id=agent.section_id, text=text[:1500]))
        self._publish(office, "talk", **{"from": agent.id, "to": ids})
        idle = [i for i in ids if office.agent(i) and office.agent(i).status == AGENT_IDLE][:3]
        for agent_id in idle:
            self._replies.submit(self._reply_to_agent, office, agent_id, agent, text)
        return f"Sent to {label}. They will see it on their next step."

    def _reply_to_agent(self, office: Office, agent_id: str, asker: Agent, text: str) -> None:
        agent = office.agent(agent_id)
        if agent is None or agent.status != AGENT_IDLE:
            return
        section = office.section(agent.section_id)
        self._set_agent(office, agent, AGENT_WORKING, f"Answering {asker.name}")
        answer = talk.ask(agent.member, [{"role": "user", "content": prompts.message_reply(
            office, agent, text, from_name=asker.name, others=0)}],
            system=prompts.worker_system(office, section, agent), max_tokens=400, timeout=90,
            router=self._router())
        self._set_agent(office, agent, AGENT_IDLE, "")
        if not answer.ok:
            return
        reply = _TASK_LINE.sub("", answer.clean).strip()
        asker.inbox.append({"from": agent.name, "text": reply[:1200], "ts": time.time()})
        self._post(office, Message(id=new_id("msg"), by=agent.id, by_name=agent.name, to=[asker.id],
                                   to_label=asker.name, kind="liaison", section_id=agent.section_id,
                                   text=reply[:1200]))
        self._publish(office, "talk", **{"from": agent.id, "to": [asker.id]})

    def agent_delegate(self, office: Office, agent: Agent, to: str, title: str, detail: str,
                       parent: Any = None) -> str:
        if not title.strip():
            return "Say what the task is."
        ids = targeting.liaison_targets(office, to)
        ids = [i for i in ids if i != agent.id]
        target = office.agent(ids[0]) if ids else None
        if target is None:
            role = role_module.find(to)
            if role is None:
                return f"Nobody here matches {to!r}. Name an agent, or ask for a new one with hire()."
            return self.agent_hire(office, agent, role=to, why=f"To do: {title}", long_term="", count=1,
                                   section_id=agent.section_id)
        job = office.current_job()
        task = Task(id=new_id("tsk"), title=title[:120], detail=detail[:3000], section_id=target.section_id,
                    role=target.role, agent_id=target.id, job_id=job.id if job else "",
                    created_by=agent.id, parent_id=getattr(parent, "id", ""))
        office.tasks[task.id] = task
        if job is not None:
            job.task_ids.append(task.id)
        self._publish(office, "task", task=task.as_dict())
        self._post(office, Message(id=new_id("msg"), by=agent.id, by_name=agent.name, to=[target.id],
                                   to_label=target.name, kind="delegate", section_id=agent.section_id,
                                   text=f"{title} → {target.name}"))
        self._publish(office, "talk", **{"from": agent.id, "to": [target.id]})
        return f"{target.name} has it."

    def agent_hire(self, office: Office, agent: Agent, *, role: str, why: str, long_term: str = "", count: int = 1,
                   clone_of: str = "", section_id: str = "") -> str:
        """Somebody wants another agent. The Hiring Board answers once it exists; a manager answers before that."""
        wanted = (role or clone_of or "").strip()
        if not wanted:
            return "Say what kind of agent you need."
        request = HireRequest(id=new_id("hire"), role_words=wanted[:80], why=why[:600], long_term=long_term[:400],
                              count=max(1, min(8, count)), clone_of=clone_of[:60],
                              section_id=section_id or agent.section_id, by=agent.id, by_name=agent.name)
        known = role_module.find(wanted)
        request.role_id = known.id if known else ""
        request.new_type = known is None
        office.hires.append(request)
        self._publish(office, "hire", hire=request.as_dict())
        if gatekeeper.is_awake(office):
            self._replies.submit(self._decide_hire, office, request)
            return (f"Your request for {request.count} × {wanted} has gone to the Hiring Board. Carry on with what "
                    "you can do without it.")
        verdict = gatekeeper.manager_verdict(office, request)
        return self._apply_hire(office, request, verdict, decided_by="the section manager")

    def _decide_hire(self, office: Office, request: HireRequest) -> None:
        board = office.agent(office.gatekeeper_id)
        if board is None:
            return
        self._set_agent(office, board, AGENT_WORKING, f"Weighing up {request.role_words}")
        verdict = gatekeeper.decide(office, request, member=board.member, router=self._router())
        self._set_agent(office, board, AGENT_IDLE, "")
        self._apply_hire(office, request, verdict, decided_by=board.name)
        self._save(office)

    def _apply_hire(self, office: Office, request: HireRequest, verdict: Any, *, decided_by: str) -> str:
        request.status = {"approve": "approved", "clone": "approved", "reuse": "reuse", "deny": "denied"}.get(
            verdict.decision, "denied")
        request.reason = verdict.reason
        request.use_instead = verdict.use_instead
        request.decided_by = decided_by
        request.decided_at = time.time()
        made: List[str] = []
        if request.status == "approved":
            role_words = verdict.use_instead if verdict.decision == "clone" and verdict.use_instead else request.role_words
            role_id = self._role_id_for(office, role_words, why=request.why)
            request.role_id = role_id
            section_id = request.section_id or next(iter(office.sections), "")
            for _ in range(request.count):
                if len(office.agents) >= (office.capacity or 0):
                    break
                agent = self._add_agent(office, section_id, role_id,
                                        origin="cloned" if verdict.decision == "clone" else "hired")
                made.append(agent.name)
        self._publish(office, "hire", hire=request.as_dict())
        self._post(office, Message(id=new_id("msg"), by=office.gatekeeper_id or "office",
                                   by_name=decided_by, kind="hire", section_id=request.section_id,
                                   text=f"{request.by_name} asked for {request.count} × {request.role_words}. "
                                        f"{verdict.decision.title()}: {verdict.reason}"
                                        + (f" → {', '.join(made)}" if made else "")))
        self._maybe_wake_gatekeeper(office)
        if made:
            return f"Approved by {decided_by}: {', '.join(made)} joined. {verdict.reason}"
        if request.status == "reuse":
            return f"{decided_by} says to use {verdict.use_instead or 'someone already here'}: {verdict.reason}"
        return f"{decided_by} turned that down: {verdict.reason}"

    # ------------------------------------------------------------------ small helpers

    def _set_agent(self, office: Office, agent: Agent, status: str, step: str) -> None:
        agent.status, agent.step = status, step[:120]
        self._publish(office, "agent", agent=agent.as_dict(), throttle=0.25)

    def _post(self, office: Office, message: Message) -> Message:
        office.add_message(message)
        self._publish(office, "message", message=message.as_dict())
        return message

    def _publish(self, where: Office, kind: str, *, throttle: float = 0.0, **payload: Any) -> None:
        """One live change, named after what changed. The first argument is positional-only in spirit: a payload
        key called "office" (the office snapshot itself) must not collide with it."""
        if throttle:
            key = f"{kind}:{payload.get('agent', {}).get('id', '')}"
            now = time.time()
            if now - self._published.get(key, 0.0) < throttle:
                return
            self._published[key] = now
        try:
            from agent_events import publish_ui

            publish_ui("office.event", office_id=where.id, kind=kind, at=time.time(), **payload)
        except Exception:  # noqa: BLE001 - the office works whether or not anyone is watching
            pass

    def _save(self, office: Office, *, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._saved_at.get(office.id, 0.0) < SAVE_EVERY:
            return
        self._saved_at[office.id] = now
        try:
            library.save(office)
        except Exception:  # noqa: BLE001 - a save that fails must not stop the work in progress
            pass

    # ------------------------------------------------------------------ housekeeping

    def running_offices(self) -> List[str]:
        with self._lock:
            return list(self._runs)

    def running_office(self) -> str:
        """The first office working, for callers that only ask "is anything running"."""
        running = self.running_offices()
        return running[0] if running else ""

    def is_running(self, office_id: str) -> bool:
        return office_id in self._runs

    def watchdog(self) -> None:
        """Release focus mode if it is being held with nothing running (called from the routes layer)."""
        focus.release_if_idle(running=bool(self._runs))

    def reset_for_tests(self) -> None:
        with self._lock:
            self._offices.clear()
            self._saved_at.clear()
            self._runs.clear()
            self._published.clear()
        self._casting = casting.Casting()


ENGINE = Engine()
