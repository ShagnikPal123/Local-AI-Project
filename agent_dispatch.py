"""Several copies of an agent at once, each with its own task (Request J6/J7).

The owner (2026-09-16): "when I make a sub agent or there is one the AI makes it also adds its name to /
commands so that I can say /coder and it pulls up the coder agent and in [] I add how many of that agent to
be made. Also when using the drag drop method or when the AI calls on it for specific situations it has a
box … to say how many I want or I can drag a second one and it will show a second box. In each I can say
what I want each to specifically do."

A **dispatch** is that set of boxes: a list of *instances* ("Coder #1", "Coder #2", "Designer #1"), each with
its own task, run in parallel (bounded by the Power setting) through ``agent_runtime.run_specialist``.
It can be started three ways and looks the same in all of them:

* the composer (``/coder [3] build the login page`` opens the boxes; Run starts it),
* the Core view's project dock (agents dragged in or added with +),
* Nyx itself, through the ``dispatch_agents`` tool, when a request needs several copies.

While it runs anyone can add another box (``add``). Each instance streams its steps into the registry, the
UI hears ``agents.dispatch`` events, and when the last one finishes a summary is written into the chat the
dispatch belongs to (``chat.appended``) so the results are kept with the conversation.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

_LOG = logging.getLogger("nyx.agent_dispatch")

MAX_INSTANCES = 12
MAX_PER_AGENT = 8
_KEEP = 40


class DispatchError(ValueError):
    """A dispatch that cannot start (unknown agent, no task, too many copies)."""


@dataclass
class Instance:
    index: int
    agent: str
    label: str
    task: str
    emoji: str = ""
    status: str = "queued"          # queued | working | done | error | stopped
    step: str = ""
    understanding: str = ""
    report: str = ""
    seconds: float = 0.0
    started_at: Optional[float] = None
    ended_at: Optional[float] = None


@dataclass
class Dispatch:
    dispatch_id: str
    chat_id: str
    origin: str                      # owner | nyx
    context: str = ""
    project: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    instances: List[Instance] = field(default_factory=list)
    status: str = "running"          # running | done | stopped
    posted: bool = False
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def view(self) -> Dict[str, Any]:
        # Not asdict(self): it would deep-copy the cancel Event, which holds a lock.
        data = {k: getattr(self, k) for k in ("dispatch_id", "chat_id", "origin", "context", "created_at", "status", "posted")}
        data["project"] = dict(self.project)
        data["instances"] = [asdict(i) for i in self.instances]
        data["counts"] = {s: sum(1 for i in self.instances if i.status == s) for s in ("queued", "working", "done", "error", "stopped")}
        data["agents"] = _count_by_agent(self.instances)
        return data


def _count_by_agent(instances: List[Instance]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for inst in instances:
        counts[inst.agent] = counts.get(inst.agent, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# "/coder [3] build the login page" — parsing
# ---------------------------------------------------------------------------

_INVOKE_RE = re.compile(r"(?:(?<=\s)|^)/([a-z0-9][a-z0-9-]{0,31})(?:\s*\[\s*(\d{1,2})\s*\])?(?=$|[\s.,;:!?)])", re.IGNORECASE)


def agent_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:32]


def parse_invocations(text: str, agent_names: Dict[str, str]) -> Dict[str, Any]:
    """Agent commands in a message, with counts and the part of the message each one owns.

    ``agent_names`` maps slug → agent name. Text after a command (up to the next agent command) is that
    agent's task; an agent with nothing after it shares the rest of the message.
    """
    matches = [m for m in _INVOKE_RE.finditer(text or "") if m.group(1).lower() in agent_names]
    if not matches:
        return {"invocations": [], "shared": (text or "").strip()}
    pieces: List[Dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        own = text[match.end():end].strip(" \t\n,;:-")
        count = max(1, min(MAX_PER_AGENT, int(match.group(2) or 1)))
        pieces.append({"agent": agent_names[match.group(1).lower()], "slug": match.group(1).lower(), "count": count, "task": own})
    shared = text[: matches[0].start()].strip()
    if len(pieces) == 1:
        pieces[0]["task"] = " ".join(x for x in (shared, pieces[0]["task"]) if x)
    else:
        fallback = shared or next((p["task"] for p in pieces if p["task"]), "")
        for piece in pieces:
            piece["task"] = piece["task"] or fallback
    return {"invocations": pieces, "shared": shared}


def expand(invocations: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Counts → one item per box."""
    items: List[Dict[str, str]] = []
    for inv in invocations:
        for _ in range(int(inv.get("count") or 1)):
            items.append({"agent": inv["agent"], "task": inv.get("task", "")})
    return items[:MAX_INSTANCES]


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


class DispatchRegistry:
    def __init__(self, *, runner: Optional[Callable[..., str]] = None, threaded: bool = True,
                 poster: Optional[Callable[[str, str], None]] = None, limit_fn: Optional[Callable[[], int]] = None) -> None:
        self._runner = runner
        self._threaded = threaded
        self._poster = poster
        self._limit_fn = limit_fn
        self._lock = threading.RLock()
        self._dispatches: Dict[str, Dispatch] = {}
        self._slots: Optional[threading.BoundedSemaphore] = None
        self._last_publish = 0.0

    # --- reads -------------------------------------------------------------------

    def get(self, dispatch_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            found = self._dispatches.get(dispatch_id)
            return found.view() if found else None

    def list(self, active_only: bool = False, chat_id: str = "") -> List[Dict[str, Any]]:
        with self._lock:
            rows = sorted(self._dispatches.values(), key=lambda d: -d.created_at)
            return [d.view() for d in rows if (not active_only or d.status == "running") and (not chat_id or d.chat_id == chat_id)]

    def working_counts(self) -> Dict[str, int]:
        """How many copies of each agent are working right now (the Core view's gauges)."""
        counts: Dict[str, int] = {}
        with self._lock:
            for dispatch in self._dispatches.values():
                for inst in dispatch.instances:
                    if inst.status == "working":
                        counts[inst.agent] = counts.get(inst.agent, 0) + 1
        return counts

    # --- writes -------------------------------------------------------------------

    def start(self, items: List[Dict[str, Any]], *, chat_id: str = "", origin: str = "owner", context: str = "",
              project: Optional[Dict[str, Any]] = None, wait: bool = False) -> Dict[str, Any]:
        clean = self._clean_items(items)
        dispatch = Dispatch(dispatch_id=uuid.uuid4().hex[:10], chat_id=chat_id or "", origin=origin,
                            context=(context or "")[:4000], project=dict(project or {}))
        with self._lock:
            for item in clean:
                dispatch.instances.append(self._instance(dispatch, item))
            self._dispatches[dispatch.dispatch_id] = dispatch
            self._trim()
        self._publish(dispatch, force=True)
        threads = [self._launch(dispatch, inst) for inst in list(dispatch.instances)]
        if wait:
            for thread in threads:
                if thread is not None:
                    thread.join()
        return dispatch.view()

    def add(self, dispatch_id: str, agent: str, task: str) -> Dict[str, Any]:
        with self._lock:
            dispatch = self._dispatches.get(dispatch_id)
            if dispatch is None:
                raise DispatchError("That dispatch is gone.")
            if len(dispatch.instances) >= MAX_INSTANCES:
                raise DispatchError(f"At most {MAX_INSTANCES} boxes in one dispatch.")
            item = self._clean_items([{"agent": agent, "task": task}])[0]
            inst = self._instance(dispatch, item)
            dispatch.instances.append(inst)
            dispatch.status, dispatch.posted = "running", False
        self._publish(dispatch, force=True)
        self._launch(dispatch, inst)
        return dispatch.view()

    def stop(self, dispatch_id: str) -> Dict[str, Any]:
        with self._lock:
            dispatch = self._dispatches.get(dispatch_id)
            if dispatch is None:
                raise DispatchError("That dispatch is gone.")
            dispatch.cancel.set()
            for inst in dispatch.instances:
                if inst.status == "queued":
                    inst.status, inst.ended_at = "stopped", time.time()
        self._publish(dispatch, force=True)
        return dispatch.view()

    # --- internals ---------------------------------------------------------------------

    def _clean_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        from agent_runtime import load_roster, roster_entry_exact, roster_entry

        if not isinstance(items, list) or not items:
            raise DispatchError("Add at least one agent box.")
        if len(items) > MAX_INSTANCES:
            raise DispatchError(f"At most {MAX_INSTANCES} boxes at once.")
        clean: List[Dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("agent") or "").strip()
            entry = roster_entry_exact(name) or roster_entry(name)
            if entry is None:
                team = ", ".join(a["name"] for a in load_roster() if a.get("role") != "master")
                raise DispatchError(f"No agent called {name!r}. The team is: {team}.")
            if entry.get("role") == "master":
                raise DispatchError("The Manager runs the chat itself; pick a specialist.")
            task = str(item.get("task") or "").strip()
            if not task:
                raise DispatchError(f"Say what {entry['name']} should do.")
            clean.append({"agent": entry["name"], "task": task[:4000], "emoji": entry.get("emoji", "")})
        per_agent = _count_by_agent([Instance(0, c["agent"], "", "") for c in clean])
        too_many = [a for a, n in per_agent.items() if n > MAX_PER_AGENT]
        if too_many:
            raise DispatchError(f"At most {MAX_PER_AGENT} copies of {too_many[0]} at once.")
        return clean

    def _instance(self, dispatch: Dispatch, item: Dict[str, str]) -> Instance:
        same = sum(1 for i in dispatch.instances if i.agent == item["agent"]) + 1
        return Instance(index=len(dispatch.instances), agent=item["agent"], label=f"{item['agent']} #{same}",
                        task=item["task"], emoji=item.get("emoji", ""))

    def _trim(self) -> None:
        finished = sorted((d for d in self._dispatches.values() if d.status != "running"), key=lambda d: d.created_at)
        for old in finished[: max(0, len(self._dispatches) - _KEEP)]:
            self._dispatches.pop(old.dispatch_id, None)

    def _semaphore(self) -> threading.BoundedSemaphore:
        with self._lock:
            if self._slots is None:
                size = 3
                try:
                    size = self._limit_fn() if self._limit_fn else __import__("resource_governor").GOVERNOR.ceiling().max_agents
                except Exception:  # noqa: BLE001
                    size = 3
                self._slots = threading.BoundedSemaphore(max(2, min(int(size or 3), 6)))
            return self._slots

    def _launch(self, dispatch: Dispatch, inst: Instance) -> Optional[threading.Thread]:
        if not self._threaded:
            self._run(dispatch, inst)
            return None
        thread = threading.Thread(target=self._run, args=(dispatch, inst), daemon=True,
                                  name=f"nyx-dispatch-{dispatch.dispatch_id}-{inst.index}")
        thread.start()
        return thread

    def _run(self, dispatch: Dispatch, inst: Instance) -> None:
        slots = self._semaphore()
        with slots:
            if dispatch.cancel.is_set() or inst.status == "stopped":
                self._finish_if_done(dispatch)
                return
            with self._lock:
                inst.status, inst.started_at, inst.step = "working", time.time(), "Reading the task"
            self._publish(dispatch, force=True)
            context = dispatch.context
            if dispatch.project:
                where = dispatch.project.get("path") or dispatch.project.get("name") or ""
                context = f"Project: {dispatch.project.get('name', '')} {('(' + where + ')') if where else ''}\n{context}".strip()
            others = [i for i in dispatch.instances if i is not inst and i.agent == inst.agent]
            if others:
                context += (f"\n\nYou are {inst.label}. {len(others)} other cop{'y' if len(others) == 1 else 'ies'} of you work "
                            "on other parts at the same time — do only your own task:\n"
                            + "\n".join(f"- {o.label}: {o.task[:160]}" for o in others))
            try:
                report = self._run_specialist(dispatch, inst, context.strip())
                with self._lock:
                    inst.report = report
                    inst.status = "stopped" if dispatch.cancel.is_set() else ("error" if " could not finish:" in report[:200] else "done")
            except Exception as error:  # noqa: BLE001 - one copy failing must not stop the others
                with self._lock:
                    inst.status, inst.report = "error", f"{type(error).__name__}: {error}"
            finally:
                with self._lock:
                    inst.ended_at = time.time()
                    inst.seconds = round(inst.ended_at - (inst.started_at or inst.ended_at), 1)
                    inst.step = {"done": "Reported back", "error": "Failed", "stopped": "Stopped"}.get(inst.status, inst.step)
        self._publish(dispatch, force=True)
        self._finish_if_done(dispatch)

    def _run_specialist(self, dispatch: Dispatch, inst: Instance, context: str) -> str:
        if self._runner is not None:
            return self._runner(inst.agent, inst.task, context)
        from agent_runtime import run_specialist
        from tool_context import ToolContext, use_context

        def sink(event: Dict[str, Any]) -> None:
            if event.get("type") != "agent.update":
                return
            with self._lock:
                if event.get("step"):
                    inst.step = str(event["step"])[:200]
                if event.get("understanding"):
                    inst.understanding = str(event["understanding"])[:300]
            self._publish(dispatch)

        ctx = ToolContext(turn_id=f"dispatch-{dispatch.dispatch_id}-{inst.index}", chat_id=dispatch.chat_id or "dispatch",
                          role="local", sink=sink)
        ctx.cancelled = dispatch.cancel
        with use_context(ctx):
            report = run_specialist(inst.agent, inst.task, context=context)
        return re.sub(r"^Report from [^\n]*\(\d+s\):\n", "", report)

    def _finish_if_done(self, dispatch: Dispatch) -> None:
        with self._lock:
            if any(i.status in ("queued", "working") for i in dispatch.instances) or dispatch.posted:
                return
            dispatch.status = "stopped" if dispatch.cancel.is_set() else "done"
            dispatch.posted = True
            summary = self.summary(dispatch)
        self._publish(dispatch, force=True)
        if dispatch.chat_id:
            self._post(dispatch.chat_id, summary)

    @staticmethod
    def summary(dispatch: Dispatch) -> str:
        counts = _count_by_agent(dispatch.instances)
        head = " + ".join(f"{n}× {a}" if n > 1 else a for a, n in counts.items())
        lines = [f"**Agents finished — {head}**"]
        for inst in dispatch.instances:
            mark = {"done": "✓", "error": "▲", "stopped": "■"}.get(inst.status, "•")
            lines.append(f"\n### {mark} {inst.emoji} {inst.label} ({inst.seconds:.0f}s)\n*Task:* {inst.task[:300]}\n\n{inst.report[:3000]}")
        return "\n".join(lines)

    def _post(self, chat_id: str, text: str) -> None:
        if self._poster is not None:
            self._poster(chat_id, text)
            return
        try:
            import server

            store = server._shared_chat_store()
            if store.exists(chat_id):
                store.append("assistant", text, chat_id=chat_id)
                from agent_events import publish_ui

                publish_ui("chat.appended", chat_id=chat_id, by="agents")
        except Exception as error:  # noqa: BLE001 - the boxes still show every report
            _LOG.warning("could not post dispatch results to chat %s: %s", chat_id, error)

    def _publish(self, dispatch: Dispatch, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_publish < 0.4:
            return
        self._last_publish = now
        try:
            from agent_events import publish_ui

            publish_ui("agents.dispatch", dispatch=dispatch.view())
        except Exception:  # noqa: BLE001
            pass


DISPATCHES = DispatchRegistry()


# ---------------------------------------------------------------------------
# The tool Nyx uses
# ---------------------------------------------------------------------------


def tool_dispatch_agents(agent: str = "", count: Any = 1, task: str = "", tasks: Any = None, context: str = "",
                         agents: Any = None) -> str:
    """Several copies of one agent (or several agents), each with its own task, in parallel; waits for the reports."""
    import json

    from tool_context import current

    items: List[Dict[str, str]] = []
    if agents:
        try:
            listed = json.loads(agents) if isinstance(agents, str) else list(agents)
        except (ValueError, TypeError):
            return 'Error: agents must be a JSON list like [{"agent": "Coder", "task": "..."}].'
        items = [{"agent": str(a.get("agent", "")), "task": str(a.get("task", ""))} for a in listed if isinstance(a, dict)]
    else:
        task_list: List[str] = []
        if tasks:
            try:
                task_list = json.loads(tasks) if isinstance(tasks, str) and tasks.strip().startswith("[") else (
                    list(tasks) if isinstance(tasks, list) else [str(tasks)])
            except (ValueError, TypeError):
                task_list = [str(tasks)]
        try:
            n = max(1, min(MAX_PER_AGENT, int(count or 1)))
        except (TypeError, ValueError):
            n = 1
        n = max(n, len(task_list))
        items = [{"agent": agent, "task": (task_list[i] if i < len(task_list) else task)} for i in range(n)]
    ctx = current()
    try:
        view = DISPATCHES.start(items, chat_id=ctx.chat_id if ctx else "", origin="nyx", context=context, wait=True)
    except DispatchError as error:
        return f"Error: {error}"
    if ctx is not None:
        ctx.emit("agents.dispatch", dispatch=view)
    final = DISPATCHES.get(view["dispatch_id"]) or view
    parts = [f"{i['label']} ({i['status']}, {i['seconds']:.0f}s):\n{i['report']}" for i in final["instances"]]
    return "Reports from the agents you dispatched (the owner saw a box for each):\n\n" + "\n\n---\n\n".join(parts)


def register_dispatch_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="dispatch_agents",
        description=("Run several copies of a specialist at once, each on its own part of the work (e.g. 3 Coders on "
                     "3 files), or several different specialists. Use count + tasks for one agent, or agents=[{agent, task}] "
                     "for a mix. The owner sees a box per copy and can add more. Returns every report."),
        parameters=[
            ToolParam("agent", "string", "Specialist name, e.g. Coder", required=False),
            ToolParam("count", "integer", "How many copies (1-8)", required=False),
            ToolParam("task", "string", "The shared task when every copy does the same kind of work", required=False),
            ToolParam("tasks", "array", "One task per copy (overrides task)", required=False),
            ToolParam("agents", "array", "Mixed dispatch: list of {agent, task}", required=False),
            ToolParam("context", "string", "Facts every copy needs; they do not see the chat", required=False),
        ],
        handler=tool_dispatch_agents,
        category="agents",
        label=lambda a: f"Dispatching {a.get('count') or len(a.get('tasks') or a.get('agents') or []) or 1}× {a.get('agent') or 'agents'}",
    )
