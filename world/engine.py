"""The world at work: census, the clock, the government's projects through the office, contests, start-ups, births.

One world runs at a time, because it runs on the one office engine (``office.engine.ENGINE``): each project the world
government decides on is an office job, so the planning, the agents, their tools, the reviews, the Output box and the
staffing rules are the office's own — and so is everything the owner already knows how to read in Office Space.
What this module adds is the world around that work (``docs/WORLD.md`` §4).

A run is a thread named ``world-<id>``. It never blocks on a model: the government, the hearings, the judges and the
technology names are asked on a small pool while the clock, the building and the sleeping keep going every second.
Everything that changes is published as a ``world.event``; everything that matters is written to the world's one file.
"""

from __future__ import annotations

import random
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from world import (ERAS, MAX_PROJECTS_UNTIL_DONE, POPULATION_BY_WORKERS, SPEED_BY_WORKERS, SPEED_ORDER, SPEEDS,
                   clock, genome, government, laws as law_module, sim, store)
from world.state import Project, Startup, War, World, new_id

#: How often the run looks at the world. Tests make it faster.
TICK_SECONDS = 1.0
#: How long the census lingers on each step so the owner can watch it (scaled down at higher speeds).
CENSUS_STEP_SECONDS = 0.35
SAVE_EVERY = 5.0
CLOCK_EVERY = 2.0
PLAN_TIMEOUT = 150.0
ASK_TIMEOUT = 90.0
MOOD_TIMEOUT = 45.0
WORLDS_FOLDER = "Worlds"
MAKER_WORDS = ("coder", "writer", "designer", "developer", "engineer", "builder", "tester", "artist", "analyst")


class WorldError(ValueError):
    """Something the owner can act on: no goal yet, another world or office working, a record that is gone."""


@dataclass
class Run:
    world_id: str
    stop: threading.Event = field(default_factory=threading.Event)
    paused: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None
    job_id: str = ""
    plan: Optional[Future] = None
    rest_until: float = 0.0
    census: Optional[Dict[str, Any]] = None
    saved_at: float = 0.0
    clock_at: float = 0.0
    stopping_by_world: bool = False
    goal_met: bool = False


def _office_engine() -> Any:
    from office.engine import ENGINE

    return ENGINE


def _publish(world_id: str, kind: str, **payload: Any) -> None:
    try:
        from agent_events import publish_ui

        publish_ui("world.event", world_id=world_id, kind=kind, at=time.time(), **payload)
    except Exception:  # noqa: BLE001 - the world works whether or not anyone is watching
        pass


def limits() -> Dict[str, Any]:
    """How big a world this computer may hold and how fast it may run (U34, U38)."""
    from office import casting

    workers = 2
    try:
        device = casting._device()
        workers = int(getattr(device, "max_workers", 2) or 2)
    except Exception:  # noqa: BLE001
        pass
    cap = next(value for needed, value in POPULATION_BY_WORKERS if workers >= needed)
    fastest = next(value for needed, value in SPEED_BY_WORKERS if workers >= needed)
    try:
        cap = max(1, min(cap, int(casting.capacity(focus=True).agents)))
    except Exception:  # noqa: BLE001
        pass
    allowed = SPEED_ORDER[: SPEED_ORDER.index(fastest) + 1]
    machine = "high-end" if workers >= 8 else "medium" if workers >= 4 else "small"
    return {
        "population": cap, "workers": workers, "machine": machine, "max_speed": fastest,
        "speeds": [{"id": s, "label": SPEEDS[s]["label"], "what": SPEEDS[s]["what"], "allowed": s in allowed}
                   for s in SPEED_ORDER],
        "reason": (f"This is a {machine} machine ({workers} agents can think at once), so a world may hold up to "
                   f"{cap} AIs and run at most at {SPEEDS[fastest]['label']}."),
    }


def clamp_speed(name: str) -> str:
    fastest = limits()["max_speed"]
    name = name if name in SPEEDS else "steady"
    return name if SPEED_ORDER.index(name) <= SPEED_ORDER.index(fastest) else fastest


class Engine:
    """Every open world, the one that is running, and everything that changes them."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._worlds: Dict[str, World] = {}
        self._run: Optional[Run] = None
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="world-ask")
        self._asking: Dict[str, Future] = {}

    # ------------------------------------------------------------------ opening

    def open(self, world_id: str) -> World:
        with self._lock:
            world = self._worlds.get(world_id)
            if world is None:
                try:
                    world = store.load(world_id)
                except store.StoreError as error:
                    raise WorldError(str(error)) from error
                self._worlds[world_id] = world
            return world

    def _save(self, world: World) -> None:
        try:
            store.save(world)
        except Exception:  # noqa: BLE001 - a failed save must not stop a world in progress
            pass

    def running_world(self) -> str:
        run = self._run
        return run.world_id if run and run.thread and run.thread.is_alive() else ""

    def overview(self) -> Dict[str, Any]:
        from office import focus, library

        offices = []
        try:
            linked = {w["office_id"] for w in store.worlds()}
            for item in library.scan():
                if item.kind == "office":
                    offices.append({"id": item.id, "name": item.name, "agents": item.card.get("agents", 0),
                                    "goal": item.card.get("goal", ""), "has_world": item.id in linked})
        except Exception:  # noqa: BLE001
            offices = []
        return {"worlds": store.worlds(), "running": self.running_world(), "limits": limits(),
                "offices": offices, "office_running": _office_engine().running_office(), "focus": focus.status()}

    # ------------------------------------------------------------------ making worlds

    def _view(self, world: World) -> sim.OfficeView:
        """The office as the sim sees it (``sim.OfficeView``)."""
        from office import roles as role_module
        from office.state import TASK_DONE

        office = _office_engine().open(world.office_id)
        catalogue = {r.id: r for r in role_module.catalogue()}
        job = office.current_job()
        # Copies first: the office's own threads add tasks and agents while this reads them.
        tasks = list(office.tasks.values())
        members = list(office.agents.values())
        busy = {t.agent_id for t in tasks if job is not None and t.job_id == job.id and t.agent_id}
        done: Dict[str, int] = {}
        for task in tasks:
            if task.status == TASK_DONE:
                done[task.section_id] = done.get(task.section_id, 0) + 1
        agents = []
        for agent in members:
            role = catalogue.get(agent.role)
            agents.append(sim.AgentView(
                id=agent.id, name=agent.name, role=agent.role, title=role.title if role else agent.role,
                domain=role.domain if role else "", kind=role.kind if role else "worker", section=agent.section_id,
                status=agent.status, employment=agent.employment, rank=agent.rank, member=agent.member,
                tasks_done=agent.tasks_done, busy=agent.id in busy))
        sections = [sim.SectionView(id=s.id, name=s.name, purpose=s.purpose, order=s.order, color=s.color)
                    for s in list(office.sections.values())]
        top = office.top_manager()
        let_go = {c.agent_id: c.why for c in list(office.staffing) if c.change == "let_go"}
        return sim.OfficeView(sections=sections, agents=agents, done_by_section=done, top_id=top.id if top else "",
                              let_go=let_go)

    def _found(self, world: World) -> None:
        """The first moment of a world: its sectors and people from the office, and a camp already standing."""
        view = self._view(world)
        sim.sync_sectors(world, view)
        sim.sync_bots(world, view)
        world.tech_points = sim.tech_points(world, view)
        world.era = sim.era_for(world.tech_points)
        for _ in range(30):
            sim.grow(world, view, dt=60.0, build_rate=1.0)
        for building in world.buildings:
            if building.state == "constructing":
                building.state, building.progress = "standing", 1.0
        if not world.techs:
            world.techs.append({**government.parse_tech(None, world.era), "era": world.era,
                                "day": round(world.game_days, 2), "ts": time.time()})
        self._apply_effort(world)

    def create(self, *, name: str = "", goal: str = "", duration: str = "", speed: str = "") -> Dict[str, Any]:
        """A brand-new world, with its own office in Office Space → Worlds."""
        from office import library

        goal = (goal or "").strip()[:4000]
        title = store.clean_name(name or (goal[:40] if goal else "New world"))
        folder = next((i for i in library.scan(force=True) if i.kind == "folder" and i.name == WORLDS_FOLDER
                       and not i.parent), None)
        folder_id = folder.id if folder else library.create_folder(WORLDS_FOLDER)["id"]
        office, _directory = library.create_office(title, folder_id)
        _office_engine().open(office.id)
        return self._make(office.id, title, goal, duration, speed, how="founded")

    def upscale(self, office_id: str, *, name: str = "", goal: str = "", duration: str = "",
                speed: str = "") -> Dict[str, Any]:
        """*"when the user wants basically a super large scale project they can press upscale for the office"*.
        The office's team become the first citizens; one office has at most one world."""
        existing = next((w for w in store.worlds() if w["office_id"] == office_id), None)
        if existing is not None:
            return self.snapshot(existing["id"])
        office = _office_engine().open(office_id)
        title = store.clean_name(name or f"{office.name} World")
        return self._make(office_id, title, (goal or office.goal or "").strip()[:4000], duration, speed,
                          how="upscaled")

    def _make(self, office_id: str, title: str, goal: str, duration: str, speed: str, *, how: str) -> Dict[str, Any]:
        world = World(id=new_id("wld"), name=title, office_id=office_id, goal=goal, speed=clamp_speed(speed),
                      seed=random.randint(1, 10_000_000))
        seconds = clock.parse_duration(duration) if duration else clock.parse_duration(goal)
        world.duration = int(seconds or 0)
        world.settings = {"share_machine": False}
        with self._lock:
            self._worlds[world.id] = world
            self._found(world)
            world.log("founded", f"{world.name} was {how} from an office of {len(world.bots)} AI"
                                 f"{'s' if len(world.bots) != 1 else ''}.")
            self._save(world)
        return self.snapshot(world.id)

    # ------------------------------------------------------------------ reading

    def snapshot(self, world_id: str) -> Dict[str, Any]:
        world = self.open(world_id)
        with self._lock:
            run = self._run if self._run and self._run.world_id == world_id else None
            awake = sum(1 for b in world.bots.values() if b.state == "awake")
            commons = sim.common_bots(world)
            leader = self._leader(world)
            current = world.current_project()
            time_left = max(0.0, world.duration - world.spent) if world.duration else None
            return {
                "world": {
                    "id": world.id, "name": world.name, "office_id": world.office_id, "goal": world.goal,
                    "status": world.status, "speed": world.speed, "speed_label": SPEEDS[world.speed]["label"],
                    "walk": SPEEDS[world.speed]["walk"], "duration": world.duration, "spent": round(world.spent, 1),
                    "time_left": time_left, "real_seconds": round(world.real_seconds, 1),
                    "game_days": round(world.game_days, 2), "game_date": clock.game_date_words(world.game_days),
                    "era": world.era, "era_name": ERAS[world.era], "tech_points": world.tech_points,
                    "next_era_at": sim.next_era_at(world.era), "techs": world.techs[-8:],
                    "stations": world.stations, "planets": world.planets, "stalled": world.stalled,
                    "note": world.note, "births": world.births, "deaths": world.deaths,
                    "created_at": world.created_at, "updated_at": world.updated_at, "started_at": world.started_at,
                    "leader": leader, "settings": dict(world.settings),
                    "population": {"ais": len(world.bots), "awake": awake, "asleep": len(world.bots) - awake,
                                   "common": sum(commons.values())},
                    "projects_done": world.projects_done(),
                    "project": current.as_dict() if current else None,
                    "running": bool(run and run.thread and run.thread.is_alive()),
                    "census": run.census if run else None,
                    "thinking": bool(run and run.plan is not None and not run.plan.done()),
                },
                "sectors": [sim.sector_dict(s) for s in world.sectors.values()],
                "bots": [sim.bot_dict(world, b) for b in world.bots.values()],
                "buildings": [b.as_dict() for b in world.buildings],
                "common": commons,
                "laws": [law.as_dict() for law in world.laws[-80:]],
                "wars": [w.as_dict() for w in world.wars[-40:]],
                "startups": [s.as_dict() for s in world.startups[-40:]],
                "graves": [g.as_dict() for g in world.graves[-160:]],
                "projects": [p.as_dict() for p in world.projects[-40:]],
                "timeline": [e.as_dict() for e in world.timeline[-240:]],
                "commands": list(world.commands),
                "limits": limits(),
            }

    def _leader(self, world: World) -> Dict[str, Any]:
        """U44: who leads — Big Kahuna when the top manager's seat is Identity 0."""
        try:
            office = _office_engine().open(world.office_id)
            top = office.top_manager()
            member = top.member if top else ""
        except Exception:  # noqa: BLE001
            top, member = None, ""
        kahuna = member.startswith("identity0")
        return {"aid": top.id if top else "", "name": "Big Kahuna" if kahuna else (top.name if top else "—"),
                "member": member, "kahuna": kahuna}

    # ------------------------------------------------------------------ the owner's controls

    def control(self, world_id: str, action: str, *, halt_office: bool = False) -> Dict[str, Any]:
        action = (action or "").strip().lower()
        if action == "start":
            self._start(world_id, halt_office=halt_office)
        elif action == "pause":
            self._pause(world_id)
        elif action == "resume":
            self._start(world_id, halt_office=halt_office, resuming=True)
        elif action == "stop":
            self._stop(world_id, why="Stopped by you.")
        else:
            raise WorldError("Use start, pause, resume or stop.")
        return self.snapshot(world_id)

    def _start(self, world_id: str, *, halt_office: bool = False, resuming: bool = False) -> None:
        from office import focus

        world = self.open(world_id)
        with self._lock:
            running = self._run
            if running is not None and running.thread and running.thread.is_alive():
                if running.world_id == world_id:
                    if running.paused.is_set():
                        self._resume(world)
                    return
                other = self._worlds.get(running.world_id)
                raise WorldError(f"“{other.name if other else 'Another world'}” is running. One world runs at "
                                 "a time — pause or stop that one first.")
            if not world.goal and not world.commands:
                raise WorldError("Give the world a goal first — what should its AIs work toward?")
            office_engine = _office_engine()
            busy = office_engine.running_office()
            if busy and busy != world.office_id:
                if not halt_office:
                    other = office_engine.opened(busy)
                    raise WorldError(f"The office “{other.name if other else busy}” is working. A world needs "
                                     "the machine to itself — halt that office first.")
                office_engine.control(busy, "halt")
            if world.duration and world.spent >= world.duration:
                world.spent = 0.0          # a new run of the same length
            world.status = "running"
            world.note = ""
            world.started_at = time.time()
            if world.duration:
                world.run_until = time.time() + max(0.0, world.duration - world.spent)
            if not world.settings.get("share_machine"):
                focus.enter(world.office_id, f"AI Environment — {world.name}")
                focus.pin(world.id)
            self._apply_effort(world)
            run = Run(world_id=world.id)
            run.goal_met = False
            # Whatever the backing office is already doing becomes this world's first project.
            office = office_engine.open(world.office_id)
            job = office.current_job()
            if job is not None and office_engine.running_office() == world.office_id:
                run.job_id = job.id
                if not world.current_project():
                    world.add_project(Project(n=len(world.projects) + 1, title=job.title or job.request[:60],
                                              request=job.request, job_id=job.id, day=round(world.game_days, 2)))
            elif office.status == "paused":
                office_engine.control(world.office_id, "resume")
            world.log("owner", "You resumed the world." if resuming else "You started the world.")
            run.thread = threading.Thread(target=self._loop, args=(run,), daemon=True, name=f"world-{world.id[4:12]}")
            self._run = run
            self._save(world)
        run.thread.start()
        _publish(world.id, "world", world=self.snapshot(world.id)["world"])

    def _resume(self, world: World) -> None:
        from office import focus

        run = self._run
        if run is None:
            return
        world.status, world.note = "running", ""
        if world.duration:
            world.run_until = time.time() + max(0.0, world.duration - world.spent)
        if not world.settings.get("share_machine"):
            focus.enter(world.office_id, f"AI Environment — {world.name}")
            focus.pin(world.id)
        office_engine = _office_engine()
        if office_engine.opened(world.office_id) is not None and office_engine.open(world.office_id).status == "paused":
            office_engine.control(world.office_id, "resume")
        run.census = None
        run.paused.clear()
        world.log("owner", "You resumed the world.")
        self._save(world)

    def _pause(self, world_id: str, *, note: str = "") -> None:
        from office import focus

        world = self.open(world_id)
        with self._lock:
            run = self._run if self._run and self._run.world_id == world_id else None
            if world.status != "running":
                return
            world.status = "paused"
            world.note = note
            if run is not None:
                run.paused.set()
            office_engine = _office_engine()
            if office_engine.running_office() == world.office_id:
                office_engine.control(world.office_id, "pause")
            focus.unpin()
            focus.leave()
            world.log("owner", note or "You paused the world. Nyx's background work carries on until you resume.")
            self._save(world)
        _publish(world.id, "world", world=self.snapshot(world.id)["world"])

    def _stop(self, world_id: str, *, why: str, status: str = "stopped") -> None:
        from office import focus

        world = self.open(world_id)
        with self._lock:
            run = self._run if self._run and self._run.world_id == world_id else None
            if run is not None:
                run.stopping_by_world = True
                run.stop.set()
                run.paused.clear()
            office_engine = _office_engine()
            if status == "stopped" and office_engine.running_office() == world.office_id:
                office_engine.control(world.office_id, "halt")
            current = world.current_project()
            if current is not None and status == "stopped":
                current.status, current.ended_at = "stopped", time.time()
            if world.status in ("running", "paused"):
                world.status = status
            world.note = why
            if focus.pinned() == world.id or not focus.pinned():
                focus.unpin()
                focus.leave(force=True)
            world.log("done" if status == "complete" else "owner", why)
            self._save(world)
        _publish(world.id, "world", world=self.snapshot(world.id)["world"])

    def set_speed(self, world_id: str, speed: str) -> Dict[str, Any]:
        world = self.open(world_id)
        if speed not in SPEEDS:
            raise WorldError("Use deliberate, steady, fast or rush.")
        chosen = clamp_speed(speed)
        with self._lock:
            world.speed = chosen
            self._apply_effort(world)
            note = "" if chosen == speed else f" ({SPEEDS[speed]['label']} is more than this computer can run.)"
            world.log("owner", f"Speed set to {SPEEDS[chosen]['label']}.{note}")
            self._save(world)
        snapshot = self.snapshot(world_id)
        _publish(world.id, "world", world=snapshot["world"])
        return snapshot

    def _apply_effort(self, world: World) -> None:
        """U38: the speed is the office's effort — review rounds and steps per task."""
        config = SPEEDS[world.speed]
        try:
            _office_engine().set_options(world.office_id, review_rounds=config["review_rounds"],
                                         worker_steps=config["worker_steps"])
        except Exception:  # noqa: BLE001 - an office that cannot take its effort still works at its own
            pass

    def patch(self, world_id: str, *, name: Optional[str] = None, goal: Optional[str] = None,
              duration: Optional[str] = None, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        world = self.open(world_id)
        with self._lock:
            if name is not None and name.strip() and name.strip() != world.name:
                store.rename(world, name)
            if goal is not None and goal.strip() != world.goal:
                world.goal = goal.strip()[:4000]
                world.log("owner", f"You set the goal: {world.goal[:200]}")
            if duration is not None:
                seconds = clock.parse_duration(duration)
                if seconds is None:
                    raise WorldError("Say how long, like “5 days”, “3 hours” or “until done”.")
                world.duration, world.spent = int(seconds), 0.0
                world.run_until = time.time() + seconds if seconds and world.status == "running" else 0.0
                world.log("owner", f"Run time set to {clock.describe_seconds(seconds) if seconds else 'until the goal is met'}.")
            for key, value in (settings or {}).items():
                if key in ("share_machine",):
                    world.settings[key] = bool(value)
            self._save(world)
        return self.snapshot(world_id)

    def trash(self, world_id: str) -> Dict[str, Any]:
        if self.running_world() == world_id:
            raise WorldError("Stop the world before deleting it.")
        with self._lock:
            self._worlds.pop(world_id, None)
            try:
                where = store.trash(world_id)
            except store.StoreError as error:
                raise WorldError(str(error)) from error
        return {"trashed": where, "note": "The world file is in worlds/.trash. Its office and files stay in Office Space."}

    # ------------------------------------------------------------------ the owner's word

    def say(self, world_id: str, text: str) -> Dict[str, Any]:
        """*"Commands go to everyone. And they decide how to function together."*"""
        body = (text or "").strip()
        if not body:
            raise WorldError("Say what the world should do.")
        world = self.open(world_id)
        with self._lock:
            run = self._run if self._run and self._run.world_id == world_id else None
            world.log("owner", f"You: {body[:200]}")
            if not world.goal:
                world.goal = body[:4000]
                seconds = clock.parse_duration(body)
                if seconds:
                    world.duration = seconds
            elif run is not None and run.job_id and world.status == "running":
                # Mid-project: the government hears it now and passes it down.
                _office_engine().say(world.office_id, body)
                self._save(world)
                return {"note": "The government has it — passed on to the project under way.", "queued": False}
            else:
                world.add_command(body)
            self._save(world)
        if world.status not in ("running", "paused"):
            self._start(world_id)
            return {"note": "The world is starting with this.", "queued": True}
        return {"note": "Queued: it becomes the next project." if world.status == "running"
                else "Queued for when you resume the world.", "queued": True}

    # ------------------------------------------------------------------ laws, contests, start-ups

    def propose_law(self, world_id: str, text: str, *, scope: str = "world", sector: str = "") -> Dict[str, Any]:
        world = self.open(world_id)
        with self._lock:
            law = law_module.propose(world, text, scope=scope, sector=sector, by="You")
            self._save(world)
        _publish(world.id, "law", law=law.as_dict())
        return law.as_dict()

    def law_action(self, world_id: str, lid: int, action: str) -> Dict[str, Any]:
        if action not in ("enforce", "repeal"):
            raise WorldError("Use enforce or repeal.")
        world = self.open(world_id)
        with self._lock:
            law = law_module.owner_action(world, lid, action)
            if law is None:
                raise WorldError("That law is gone.")
            if action == "enforce" and law.status != "enforced":
                raise WorldError(law.note or "That law cannot be enforced.")
            self._save(world)
        _publish(world.id, "law", law=law.as_dict())
        return law.as_dict()

    def _declare_war(self, world: World, rivals: Dict[str, str]) -> Optional[War]:
        if any(w.status != "resolved" for w in world.wars):
            return None
        minutes = float(SPEEDS[world.speed]["war_minutes"])
        war = War(wid=new_id("war"), a=rivals["a"], b=rivals["b"], a_stance=rivals["a_stance"],
                  b_stance=rivals["b_stance"], reason=rivals["reason"], deadline=time.time() + minutes * 60,
                  day=round(world.game_days, 2))
        world.wars.append(war)
        a, b = world.sectors[war.a], world.sectors[war.b]
        world.log("war", f"{a.name} and {b.name} went to a contest of ideas: {war.reason}", ref=war.wid)
        _publish(world.id, "war", war=war.as_dict())
        return war

    def war_hearing(self, world_id: str, wid: str) -> Dict[str, Any]:
        """*"I can click on it and even say open a resolution and ask each faction to tell me why their option is
        better and to explain why they war"*. Each side's leader answers with its own model."""
        world = self.open(world_id)
        with self._lock:
            war = world.war(wid)
            if war is None:
                raise WorldError("That contest is gone.")
            if war.status == "resolved":
                raise WorldError("That contest is already settled.")
            war.status = "hearing"
            world.log("owner", f"You opened a resolution on {world.sectors[war.a].name if war.a in world.sectors else 'a'}"
                               f" vs {world.sectors[war.b].name if war.b in world.sectors else 'b'}.", ref=war.wid)
            self._save(world)
        _publish(world.id, "war", war=war.as_dict())
        self._pool.submit(self._hear, world, war)
        return war.as_dict()

    def _hear(self, world: World, war: War) -> None:
        from office import talk

        cases: Dict[str, str] = {}
        for side in ("a", "b"):
            member = self._speaker(world, war.a if side == "a" else war.b)
            prompt = government.hearing_prompt(world, war, side)
            answer = talk.ask(member, [{"role": "user", "content": prompt}], max_tokens=320, timeout=ASK_TIMEOUT) \
                if member else None
            stance = war.a_stance if side == "a" else war.b_stance
            cases[side] = (answer.clean[:900] if answer is not None and answer.ok else
                           f"(No model answered for this side.) Its position stands as given: {stance}")
        with self._lock:
            war.cases = cases
            if war.status == "hearing":
                war.status = "awaiting"
            self._save(world)
        _publish(world.id, "war", war=war.as_dict())

    def _speaker(self, world: World, sid: str) -> str:
        try:
            office = _office_engine().open(world.office_id)
            manager = office.manager_of(sid)
            if manager is not None and manager.member:
                return manager.member
            top = office.top_manager()
            return top.member if top else ""
        except Exception:  # noqa: BLE001
            return ""

    def war_decide(self, world_id: str, wid: str, *, choice: str, text: str = "") -> Dict[str, Any]:
        world = self.open(world_id)
        with self._lock:
            war = world.war(wid)
            if war is None:
                raise WorldError("That contest is gone.")
            if war.status == "resolved":
                raise WorldError("That contest is already settled.")
            choice = (choice or "").strip().lower()
            if choice not in ("a", "b", "own"):
                raise WorldError("Pick a side, or write what you want instead.")
            if choice == "own" and len((text or "").strip()) < 4:
                raise WorldError("Write what you want instead.")
            self._resolve(world, war, winner=choice if choice != "own" else "owner", by="owner",
                          decision=(text or "").strip()[:600] if choice == "own" else "",
                          why="The owner decided.")
            self._save(world)
        return war.as_dict()

    def _resolve(self, world: World, war: War, *, winner: str, by: str, decision: str = "", why: str = "") -> None:
        a, b = world.sectors.get(war.a), world.sectors.get(war.b)
        war.winner, war.by, war.why = winner, by, why[:300]
        war.decision = decision or (war.a_stance if winner == "a" else war.b_stance)
        war.status, war.resolved_at = "resolved", time.time()
        win, lose = (a, b) if winner == "a" else (b, a) if winner == "b" else (None, None)
        if win is not None:
            win.influence += 2
        if lose is not None:
            lose.influence -= 1
        capital = world.capital()
        who = "You" if by == "owner" else capital.gov if capital else "The government"
        world.log("war", f"{who} settled {a.name if a else '?'} vs {b.name if b else '?'}: "
                         f"{(win.name + ' wins') if win else 'your own way'} — {war.decision[:160]}", ref=war.wid)
        _publish(world.id, "war", war=war.as_dict())
        if lose is not None:
            # *"start ups, this is how we id a new direction the ai explores with a new group since they get into
            # disagreements"* — the losing idea may still be worth a small group of its own.
            losing = war.b_stance if winner == "a" else war.a_stance
            self._propose_startup(world, name=f"{lose.name} Ventures", idea=losing,
                                  why=f"Lost the contest over {war.reason[:120]} and wants to try its own way.",
                                  founders_from=lose.sid, from_war=war.wid, by=lose.gov)

    def _judge(self, world: World, war: War) -> None:
        from office import talk

        answer = talk.ask_lead([{"role": "user", "content": government.judge_prompt(world, war)}],
                               max_tokens=300, timeout=ASK_TIMEOUT)
        verdict = government.parse_verdict(talk.parse_json(answer.text)) if answer.ok else None
        with self._lock:
            if war.status != "open":
                return
            if verdict is None:
                a, b = world.sectors.get(war.a), world.sectors.get(war.b)
                winner = "b" if (b.influence if b else 0) > (a.influence if a else 0) else "a"
                verdict = {"winner": winner, "why": "No model answered; the more influential sector carried it."}
            self._resolve(world, war, winner=verdict["winner"], by="government", why=verdict["why"])
            self._save(world)

    def _propose_startup(self, world: World, *, name: str, idea: str, why: str, founders_from: str = "",
                         from_war: str = "", by: str = "") -> Startup:
        founders: List[str] = []
        try:
            office = _office_engine().open(world.office_id)
            manager = office.manager_of(founders_from) if founders_from else None
            if manager is not None:
                founders.append(manager.id)
        except Exception:  # noqa: BLE001
            pass
        startup = Startup(suid=new_id("su"), name=name[:40], idea=idea[:300], why=why[:300], founders=founders,
                          day=round(world.game_days, 2), by=by[:60], from_war=from_war)
        world.startups.append(startup)
        world.log("startup", f"Start-up proposed: {startup.name} — {startup.idea[:140]}", ref=startup.suid)
        _publish(world.id, "startup", startup=startup.as_dict())
        if self._auto_decisions(world):
            self._found_startup(world, startup, by="government")
        return startup

    def _auto_decisions(self, world: World) -> bool:
        try:
            return bool(_office_engine().open(world.office_id).settings.get("auto_decisions"))
        except Exception:  # noqa: BLE001
            return False

    def startup_action(self, world_id: str, suid: str, action: str) -> Dict[str, Any]:
        world = self.open(world_id)
        with self._lock:
            startup = world.startup(suid)
            if startup is None:
                raise WorldError("That start-up is gone.")
            if startup.status != "proposed":
                raise WorldError(f"That start-up was already {startup.status}.")
            if action == "approve":
                self._found_startup(world, startup, by="owner")
            elif action == "decline":
                startup.status = "declined"
                world.log("startup", f"You declined the start-up {startup.name}.", ref=startup.suid)
            else:
                raise WorldError("Use approve or decline.")
            self._save(world)
        _publish(world.id, "startup", startup=startup.as_dict())
        return startup.as_dict()

    def _found_startup(self, world: World, startup: Startup, *, by: str) -> None:
        if len(world.bots) + 2 > limits()["population"]:
            startup.status = "approved"
            world.log("startup", f"{startup.name} was approved but waits for room: the world is at its population cap.",
                      ref=startup.suid)
            return
        office_engine = _office_engine()
        section = office_engine.add_section(world.office_id, startup.name, startup.idea)
        try:
            office_engine.add_agent(world.office_id, section["id"], "researcher", origin="founding",
                                    why=f"Founding member of {startup.name}: {startup.idea[:120]}")
        except Exception:  # noqa: BLE001 - a full office still gets its section and manager
            pass
        view = self._view(world)
        sim.sync_sectors(world, view)
        sim.sync_bots(world, view, project=len(world.projects))
        sector = world.sectors.get(section["id"])
        if sector is not None:
            sector.startup = True
            if world.status != "running":
                # Nothing builds while the world is stopped, so a start-up founded now settles its first buildings at
                # once instead of leaving an empty territory until the next run.
                for _ in range(4):
                    sim.grow(world, view, dt=60.0, build_rate=1.0)
                for building in world.buildings:
                    if building.sector == sector.sid and building.state == "constructing":
                        building.state, building.progress = "standing", 1.0
        startup.status, startup.sector = "founded", section["id"]
        who = "You approved" if by == "owner" else "The government approved"
        world.log("startup", f"{who} the start-up {startup.name}; it settled its own sector.", ref=startup.suid)
        _publish(world.id, "startup", startup=startup.as_dict())

    # ------------------------------------------------------------------ people

    def mood(self, world_id: str, agent_id: str) -> Dict[str, Any]:
        """U39: *"we can see theoretical mood but … it is basically just asking the ai"*. Asked now, never stored."""
        from office import talk

        world = self.open(world_id)
        office = _office_engine().open(world.office_id)
        agent = office.agent(agent_id)
        if agent is None:
            raise WorldError("That AI is not in this world any more.")
        section = office.section(agent.section_id)
        task = office.tasks.get(agent.task_id) if agent.task_id else None
        doing = agent.step or (f"working on “{task.title}”" if task else "")
        prompt = government.mood_prompt(world, name=agent.name, role=agent.role.replace("-", " "),
                                        doing=doing, sector=section.name if section else "")
        answer = talk.ask(agent.member, [{"role": "user", "content": prompt}], max_tokens=140,
                          timeout=MOOD_TIMEOUT) if agent.member else None
        if answer is not None and answer.ok:
            return {"agent_id": agent_id, "mood": answer.clean[:400], "live": True,
                    "note": "Asked just now and not saved anywhere."}
        fallback = (f"Busy — {doing}." if agent.status == "working" and doing else
                    "Resting until it is needed." if agent.employment == "part_time" else "Idle, waiting for work.")
        return {"agent_id": agent_id, "mood": fallback, "live": False,
                "note": "No model answered, so this is read from what it is doing. Not saved anywhere."}

    def rejoin(self, world_id: str, gid: int) -> Dict[str, Any]:
        """*"they remove and fire ai bots thats are not needed or can retire and join later"*."""
        world = self.open(world_id)
        with self._lock:
            grave = world.grave(gid)
            if grave is None:
                raise WorldError("That grave is gone.")
            if grave.rejoined:
                raise WorldError(f"{grave.name} already rejoined.")
            if len(world.bots) + 1 > limits()["population"]:
                raise WorldError("The world is at its population cap.")
            sector = world.sector_by_name(grave.sector) or world.capital()
            if sector is None:
                raise WorldError("The world has nowhere to put them.")
            agent = _office_engine().add_agent(world.office_id, sector.sid, grave.role or "researcher",
                                               origin="rejoined", why=f"{grave.name} rejoined the world.")
            view = self._view(world)
            match = next((a for a in view.agents if a.id == agent["id"]), None)
            if match is not None:
                code = grave.code if genome.decode(grave.code) else ""
                sim.add_bot(world, match, code=code)
            grave.rejoined = True
            world.log("rejoin", f"{grave.name} came back to work in {sector.name} as {agent['name']}.", ref=str(gid))
            self._save(world)
        _publish(world.id, "world", world=self.snapshot(world.id)["world"])
        return {"agent": agent, "grave": grave.as_dict()}

    def _maybe_birth(self, world: World, job_id: str) -> None:
        """U35: two of the project's best workers of different trades make a bot with both skill sets."""
        if len(world.bots) + 1 > limits()["population"]:
            return
        office_engine = _office_engine()
        office = office_engine.open(world.office_id)
        from office import roles as role_module
        from office.state import TASK_DONE

        tally: Dict[str, int] = {}
        for task in office.tasks.values():
            if task.job_id == job_id and task.status == TASK_DONE and task.agent_id:
                tally[task.agent_id] = tally.get(task.agent_id, 0) + 1
        ranked = sorted(tally, key=lambda aid: -tally[aid])
        picked: List[Any] = []
        for aid in ranked:
            agent = office.agent(aid)
            role = role_module.get(agent.role) if agent else None
            if agent is None or role is None or role.kind != "worker":
                continue
            if all(p[0].role != agent.role for p in picked):
                picked.append((agent, role))
            if len(picked) == 2:
                break
        if len(picked) < 2:
            return
        (first, first_role), (second, second_role) = picked
        # The trade comes from the maker ("Coder"), the qualifier from the other ("Finance") → "Finance Coder".
        if any(second_role.title.lower().endswith(w) for w in MAKER_WORDS) is False and \
                any(first_role.title.lower().endswith(w) for w in MAKER_WORDS):
            (first, first_role), (second, second_role) = (second, second_role), (first, first_role)
        title = genome.child_title(first_role.title, first_role.domain, second_role.title)
        mother, father = world.bots.get(first.id), world.bots.get(second.id)
        if mother is None or father is None:
            return
        try:
            child = office_engine.add_agent(world.office_id, second.section_id, title, origin="born", exact=True,
                                            domain=second_role.domain,
                                            why=f"Born from {first.name} and {second.name}: both skill sets in one.")
        except Exception:  # noqa: BLE001 - a full office simply has no birth this time
            return
        view = self._view(world)
        match = next((a for a in view.agents if a.id == child["id"]), None)
        if match is None:
            return
        role_code = genome.code_of(world.tables.setdefault("roles", []), match.role)
        a_parts, b_parts = genome.decode(mother.code) or {}, genome.decode(father.code) or {}
        better = mother if first.tasks_done >= second.tasks_done else father
        model = (genome.decode(better.code) or {}).get("model", a_parts.get("model", b_parts.get("model", 0)))
        code = genome.child(mother.code, father.code, role=role_code, model=model)
        bot = sim.add_bot(world, match, parents=[first.id, second.id], code=code)
        world.births += 1
        world.log("birth", f"{first.name} and {second.name} made {match.name}, a {title} with both their skills.",
                  ref=bot.aid)
        _publish(world.id, "bot", bot=sim.bot_dict(world, bot), birth=True)

    # ------------------------------------------------------------------ the run

    def _loop(self, run: Run) -> None:
        world = self.open(run.world_id)
        try:
            self._census(world, run)
            last = time.time()
            while not run.stop.is_set():
                now = time.time()
                dt = min(5.0, max(0.0, now - last))
                last = now
                if run.paused.is_set():
                    time.sleep(min(0.5, TICK_SECONDS))
                    continue
                self._tick(world, run, dt)
                if run.stop.is_set():
                    break
                out_of_time = bool(world.duration) and world.spent >= world.duration
                if run.job_id:
                    # Time running out never cuts a project in half: it finishes, then the world stops.
                    self._watch_job(world, run)
                elif out_of_time:
                    self._finish(world, run, f"Ran for the {clock.describe_seconds(world.duration)} you asked for.",
                                 status="complete")
                    break
                elif run.plan is not None:
                    if run.plan.done():
                        self._begin_project(world, run, run.plan.result())
                        run.plan = None
                elif time.time() >= run.rest_until:
                    if self._goal_met(world, run):
                        self._finish(world, run, "The government says the goal is met.", status="complete")
                        break
                    run.plan = self._pool.submit(self._ask_plan, world)
                time.sleep(TICK_SECONDS)
        except Exception as error:  # noqa: BLE001 - a broken run is reported, never a dead engine
            with self._lock:
                world.status = "paused"
                world.note = f"The world stopped on an error: {type(error).__name__}: {str(error)[:200]}"
                world.log("note", world.note)
                self._save(world)
            from office import focus

            focus.unpin()
            focus.leave()
            _publish(world.id, "world", world=self.snapshot(world.id)["world"])
        finally:
            with self._lock:
                self._save(world)

    def _census(self, world: World, run: Run) -> None:
        """U40, on every start: sector by sector, from the government down, who is still needed."""
        view = self._view(world)
        with self._lock:
            sim.sync_sectors(world, view)
            sim.sync_bots(world, view, project=len(world.projects))
        steps = sim.census_plan(world, view, project=len(world.projects))
        pause = CENSUS_STEP_SECONDS / max(1.0, SPEEDS[world.speed]["walk"])
        for index, step in enumerate(steps):
            if run.stop.is_set():
                return
            run.census = {**step, "index": index + 1, "total": len(steps)}
            _publish(world.id, "census", census=run.census)
            if pause:
                time.sleep(pause)
        with self._lock:
            changes = sim.apply_census(world, steps)
            needed = sum(len(s["needed"]) for s in steps)
            resting = sum(len(s["resting"]) for s in steps)
            world.log("census", f"Census: {len(world.sectors)} sector{'s' if len(world.sectors) != 1 else ''} checked "
                                f"from the government down — {needed} needed, {resting} resting.")
            run.census = None
            self._save(world)
        for change in changes:
            _publish(world.id, change.pop("kind"), **change)
        _publish(world.id, "census", census=None)

    def _tick(self, world: World, run: Run, dt: float) -> None:
        config = SPEEDS[world.speed]
        try:
            view = self._view(world)
        except Exception:  # noqa: BLE001 - the office is being saved or moved; try again next second
            return
        project = len(world.projects)
        with self._lock:
            world.real_seconds += dt
            if world.duration:
                world.spent += dt
            world.game_days = clock.advance(world.game_days, dt, config["days_per_minute"])
            changes = sim.sync_sectors(world, view)
            changes += sim.sync_bots(world, view, project=project)
            changes += sim.sleep(world, view, project=project)
            changes += sim.grow(world, view, dt=dt, build_rate=config["build_rate"])
            world.tech_points = sim.tech_points(world, view)
            era = sim.era_for(world.tech_points)
            if era > world.era:
                world.era = era
                world.log("era", f"{world.name} entered the {ERAS[era]} era.")
                changes.append({"kind": "era", "era": era, "era_name": ERAS[era]})
                self._pool.submit(self._name_tech, world, era)
            for war in world.wars:
                if war.status == "open" and war.deadline and time.time() >= war.deadline and \
                        f"judge:{war.wid}" not in self._asking:
                    self._asking[f"judge:{war.wid}"] = self._pool.submit(self._judge, world, war)
            now = time.time()
            if now - run.saved_at >= SAVE_EVERY:
                run.saved_at = now
                self._save(world)
        for change in changes:
            kind = change.pop("kind")
            _publish(world.id, kind, **change)
        if time.time() - run.clock_at >= CLOCK_EVERY:
            run.clock_at = time.time()
            _publish(world.id, "clock", game_days=round(world.game_days, 2),
                     game_date=clock.game_date_words(world.game_days), spent=round(world.spent, 1),
                     real_seconds=round(world.real_seconds, 1), tech_points=world.tech_points,
                     population={"ais": len(world.bots),
                                 "awake": sum(1 for b in world.bots.values() if b.state == "awake"),
                                 "common": sum(sim.common_bots(world).values())})

    def _name_tech(self, world: World, era: int) -> None:
        from office import talk

        answer = talk.ask_lead([{"role": "user", "content": government.tech_prompt(world, era)}], max_tokens=260,
                               timeout=ASK_TIMEOUT)
        tech = government.parse_tech(talk.parse_json(answer.text) if answer.ok else None, era)
        with self._lock:
            entry = {**tech, "era": era, "day": round(world.game_days, 2), "ts": time.time()}
            world.techs.append(entry)
            world.techs = world.techs[-12:]
            world.log("era", f"New technology: {tech['tech']} — {tech['about']}")
            self._save(world)
        _publish(world.id, "tech", tech=entry)

    def _ask_plan(self, world: World) -> Dict[str, Any]:
        """The government's next project, or the plain one when no model answers. Runs on the pool."""
        from office import talk

        try:
            view = self._view(world)
            people: Dict[str, int] = {}
            for agent in view.agents:
                people[agent.section] = people.get(agent.section, 0) + 1
            last = next((p for p in reversed(world.projects) if p.status == "done"), None)
            left = (clock.describe_seconds(max(0.0, world.duration - world.spent)) if world.duration
                    else "no deadline — stop when the goal is met")
            prompt = government.plan_prompt(world, people=people, done=view.done_by_section,
                                            last_summary=(last.summary if last else ""), time_left=left,
                                            population_cap=limits()["population"], commands=list(world.commands))
            answer = talk.ask_lead([{"role": "user", "content": prompt}], max_tokens=1100, timeout=PLAN_TIMEOUT,
                                   turn_id=f"world-{world.id}-{len(world.projects) + 1}")
            plan = government.parse_plan(talk.parse_json(answer.text), world) if answer.ok else None
        except Exception:  # noqa: BLE001
            plan = None
        return plan or government.offline_plan(world)

    def _begin_project(self, world: World, run: Run, plan: Dict[str, Any]) -> None:
        with self._lock:
            if run.stop.is_set() or world.status != "running":
                return
            commands, world.commands = list(world.commands), []
            if plan.get("done") and not commands:
                run.goal_met = True
                if not world.duration:
                    return
            for law in plan.get("laws") or []:
                made = law_module.propose(world, law["text"], scope=law["scope"], sector=law["sector"],
                                          by=world.capital().gov if world.capital() else "The government")
                _publish(world.id, "law", law=made.as_dict())
            if plan.get("rivals"):
                self._declare_war(world, plan["rivals"])
            if plan.get("startup"):
                startup = plan["startup"]
                self._propose_startup(world, name=startup["name"], idea=startup["idea"], why=startup["why"],
                                      by=world.capital().gov if world.capital() else "The government")
            if plan.get("teardown"):
                self._teardown(world, plan["teardown"])
            if plan.get("retool"):
                sector = world.sectors.get(plan["retool"]["sector"])
                if sector is not None:
                    world.log("retool", f"{sector.name} retooled into a {plan['retool']['into'].replace('_', ' ')}: "
                                        f"{plan['retool']['why']}", ref=sector.sid)
                    sector.kind = plan["retool"]["into"]
            decisions = []
            for war in world.wars:
                if war.status == "resolved" and not war.applied:
                    decisions.append(war.decision)
                    war.applied = True
            startups = []
            for startup in world.startups:
                if startup.status == "founded" and not startup.applied:
                    startups.append(f"{startup.name}: {startup.idea}")
                    startup.applied = True
            if commands:
                plan = {**plan, "project": plan["project"] if not plan.get("offline") else commands[0],
                        "title": plan["title"] if not plan.get("offline") else "Your command"}
            request = government.brief(world, plan, commands=commands, law_lines=law_module.brief_lines(world),
                                       decisions=decisions, startups=startups)
            gov = world.capital().gov if world.capital() else "World Government"
            try:
                result = _office_engine().say(world.office_id, request, by="world", by_name=gov)
            except Exception as error:  # noqa: BLE001
                world.commands = commands + world.commands
                self._save(world)
                run.rest_until = time.time() + 30
                world.note = f"The office could not take the project: {str(error)[:200]}"
                _publish(world.id, "world", world=self.snapshot(world.id)["world"])
                return
            run.job_id = str(result.get("job_id") or "")
            project = Project(n=len(world.projects) + 1, title=plan["title"][:80], request=request, why=plan.get("why", ""),
                              job_id=run.job_id, day=round(world.game_days, 2))
            world.add_project(project)
            law_module.assign_trials(world, run.job_id)
            world.log("project", f"Project {project.n}: {project.title}"
                                 f"{' (the plain plan — no model answered)' if plan.get('offline') else ''}",
                      ref=run.job_id)
            self._save(world)
        _publish(world.id, "project", project=project.as_dict())

    def _teardown(self, world: World, order: Dict[str, str]) -> None:
        """*"so a ceo of a specific company hates this building, they remove and restart"*."""
        standing = sorted((b for b in world.buildings if b.sector == order["sector"] and b.state == "standing"
                           and b.kind not in ("capitol", "council")), key=lambda b: (b.era, b.built_day))
        if not standing:
            return
        building = standing[0]
        building.state, building.why = "demolishing", order["why"][:200]
        sector = world.sectors.get(order["sector"])
        world.log("teardown", f"{sector.gov if sector else 'A government'} had its {building.kind.replace('_', ' ')} "
                              f"torn down: {building.why}", ref=str(building.bid))
        _publish(world.id, "building", building=building.as_dict())

    def _watch_job(self, world: World, run: Run) -> None:
        office_engine = _office_engine()
        office = office_engine.open(world.office_id)
        job = office.job(run.job_id)
        if job is None or job.status == "running":
            return
        with self._lock:
            project = next((p for p in world.projects if p.job_id == job.id), None)
            if project is not None:
                project.status, project.ended_at = job.status, time.time()
                project.summary = (job.summary or job.title or "")[:600]
            for law in law_module.settle_trials(world, job.id, job.status):
                _publish(world.id, "law", law=law.as_dict())
            run.job_id = ""
            run.rest_until = time.time() + float(SPEEDS[world.speed]["rest"])
            if job.status == "done":
                world.log("done", f"Project {project.n if project else ''} delivered: "
                                  f"{(job.summary or job.title or 'see the Output box')[:180]}", ref=job.id)
                try:
                    self._maybe_birth(world, job.id)
                except Exception:  # noqa: BLE001 - a birth that fails is simply not a birth
                    pass
            elif job.status != "stopped":
                world.log("done", f"Project {project.n if project else ''} did not finish: {job.error[:160]}", ref=job.id)
            self._save(world)
        if job.status == "stopped" and not run.stopping_by_world:
            # Halted from Office Space: the owner meant to stop the work, so the world waits for them.
            self._pause(world.id, note="The project was halted in Office Space, so the world paused. Resume to carry on.")
        if project is not None:
            _publish(world.id, "project", project=project.as_dict())

    def _goal_met(self, world: World, run: Run) -> bool:
        if world.duration:
            return False
        if run.goal_met and not world.commands:
            return True
        return world.projects_done() >= MAX_PROJECTS_UNTIL_DONE and not world.commands

    def _finish(self, world: World, run: Run, why: str, *, status: str) -> None:
        self._stop(world.id, why=why, status=status)

    # ------------------------------------------------------------------ housekeeping

    def reset_for_tests(self) -> None:
        run = self._run
        if run is not None:
            run.stop.set()
            if run.thread is not None:
                run.thread.join(10)
        with self._lock:
            self._worlds.clear()
            self._run = None
            self._asking.clear()


ENGINE = Engine()
