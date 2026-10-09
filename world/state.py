"""The records a world is made of, and their compact form (U40: small files).

In memory a world is ordinary dataclasses. On disk it is arrays of numbers and short strings: sectors are referred to
by their position, building kinds and statuses by a code, bots by their genetic code (``genome.py``), and role and
model names are written once in the world's tables. Every list is capped (``world.KEEP_*``), so a world that runs for
months does not grow a file nobody can open.

The office keeps the agents' names, tasks, chat and files; a world only keeps what the office does not know: where
things are on the planet, who governs, the laws, the wars, the start-ups, the graves and the world's own calendar.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from world import (DEFAULT_SPEED, ERAS, KEEP_BUILDINGS, KEEP_COMMANDS, KEEP_GRAVES, KEEP_PROJECTS, KEEP_TIMELINE,
                   SPEEDS)

FORMAT = 1

#: Workplace and building kinds. The position in this tuple is the code written to disk — append, never reorder.
KINDS = ("capitol", "house", "office", "lab", "data_center", "mine", "farm", "factory", "refinery", "archive",
         "studio", "bank", "tower", "council", "station", "planet")
WORKPLACES = ("office", "lab", "data_center", "mine", "farm", "factory", "refinery", "archive", "studio", "bank",
              "tower")
KIND_LABELS = {"capitol": "Capitol", "house": "Homes", "office": "Office", "lab": "Laboratory",
               "data_center": "Data centre", "mine": "Mine", "farm": "Farm", "factory": "Factory",
               "refinery": "Refinery", "archive": "Archive", "studio": "Studio", "bank": "Bank", "tower": "Tower",
               "council": "Council hall", "station": "Space station", "planet": "Artificial planet"}
BUILD_STATES = ("constructing", "standing", "demolishing")
LAW_STATUSES = ("proposed", "testing", "enforced", "repealed", "rejected")
LAW_SCOPES = ("world", "sector", "firm")
WAR_STATUSES = ("open", "hearing", "awaiting", "resolved")
STARTUP_STATUSES = ("proposed", "approved", "declined", "founded")
EVENT_KINDS = ("founded", "project", "done", "era", "law", "war", "startup", "birth", "death", "build", "teardown",
               "station", "census", "owner", "stall", "note", "retool", "rejoin")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _keep_last(items: List[Any], limit: int) -> List[Any]:
    return items[-limit:] if len(items) > limit else items


def _code(table: tuple, value: str, default: int = 0) -> int:
    return table.index(value) if value in table else default


def _word(table: tuple, code: Any, default: str) -> str:
    try:
        return table[int(code)]
    except (ValueError, TypeError, IndexError):
        return default


@dataclass
class Sector:
    """One office section seen as a region of the planet, with its own government."""

    sid: str
    name: str
    lat: float
    lon: float
    kind: str = "office"
    gov: str = ""
    influence: int = 0
    founded_day: float = 0.0
    startup: bool = False
    important: bool = False
    full: bool = False


@dataclass
class Bot:
    """One office agent as a citizen. ``code`` is its genetic code; the rest is where and how it lives."""

    aid: str
    code: str
    born_day: float = 0.0
    parents: List[str] = field(default_factory=list)
    state: str = "awake"            # awake | asleep
    home: int = 0                   # house plot in its sector
    name: str = ""
    role: str = ""
    sector: str = ""
    last_busy: int = 0              # the project number it last had work in


@dataclass
class Building:
    bid: int
    sector: str
    kind: str
    floors: int = 1
    era: int = 0
    plot: int = 0
    built_day: float = 0.0
    state: str = "constructing"
    progress: float = 0.0
    why: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Law:
    lid: int
    text: str
    scope: str = "world"
    sector: str = ""
    status: str = "proposed"
    by: str = ""
    day: float = 0.0
    note: str = ""
    trial_job: str = ""
    code: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class War:
    """An idea contest between two factions — never a literal war (the owner: "it helps to show whose ideas are
    better"). It always carries its reason."""

    wid: str
    a: str
    b: str
    a_stance: str
    b_stance: str
    reason: str
    status: str = "open"
    cases: Dict[str, str] = field(default_factory=dict)
    winner: str = ""                # "a" | "b" | "owner"
    decision: str = ""
    by: str = ""                    # "owner" | "government"
    why: str = ""
    opened_at: float = field(default_factory=time.time)
    deadline: float = 0.0
    resolved_at: float = 0.0
    day: float = 0.0
    applied: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Startup:
    suid: str
    name: str
    idea: str
    why: str = ""
    founders: List[str] = field(default_factory=list)
    status: str = "proposed"
    sector: str = ""
    day: float = 0.0
    by: str = ""
    from_war: str = ""
    applied: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Grave:
    gid: int
    aid: str
    name: str
    role: str
    sector: str
    born_day: float
    died_day: float
    epitaph: str = ""
    retired: bool = True            # retired may rejoin; the owner can always bring one back
    code: str = ""
    rejoined: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Project:
    n: int
    title: str
    request: str = ""
    why: str = ""
    job_id: str = ""
    status: str = "running"         # running | done | failed | stopped
    started_at: float = field(default_factory=time.time)
    ended_at: float = 0.0
    day: float = 0.0
    summary: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Event:
    ts: float
    day: float
    kind: str
    text: str
    ref: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class World:
    id: str
    name: str
    office_id: str = ""
    goal: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "idle"
    speed: str = DEFAULT_SPEED
    run_until: float = 0.0          # real time; 0 = until the government says the goal is met
    duration: int = 0               # what the owner asked for, in seconds (for the timeline)
    started_at: float = 0.0         # when this run began
    real_seconds: float = 0.0       # how long the world has been running, all runs together
    spent: float = 0.0              # running seconds counted against ``duration`` (pauses do not use it up)
    game_days: float = 0.0
    era: int = 0
    tech_points: int = 0
    techs: List[Dict[str, Any]] = field(default_factory=list)
    sectors: Dict[str, Sector] = field(default_factory=dict)
    bots: Dict[str, Bot] = field(default_factory=dict)
    buildings: List[Building] = field(default_factory=list)
    next_building: int = 1
    stations: int = 0
    planets: int = 0
    laws: List[Law] = field(default_factory=list)
    next_law: int = 1
    wars: List[War] = field(default_factory=list)
    startups: List[Startup] = field(default_factory=list)
    graves: List[Grave] = field(default_factory=list)
    next_grave: int = 1
    projects: List[Project] = field(default_factory=list)
    timeline: List[Event] = field(default_factory=list)
    commands: List[str] = field(default_factory=list)
    tables: Dict[str, List[str]] = field(default_factory=lambda: {"roles": [], "members": [], "skills": []})
    settings: Dict[str, Any] = field(default_factory=dict)
    seed: int = 0
    stalled: str = ""
    note: str = ""
    births: int = 0
    deaths: int = 0

    # --- reads ------------------------------------------------------------------

    def sector_list(self) -> List[Sector]:
        return list(self.sectors.values())

    def sector_by_name(self, name: str) -> Optional[Sector]:
        wanted = (name or "").strip().lower()
        if not wanted:
            return None
        return (next((s for s in self.sectors.values() if s.name.lower() == wanted), None)
                or next((s for s in self.sectors.values() if wanted in s.name.lower() or s.name.lower() in wanted),
                        None))

    def capital(self) -> Optional[Sector]:
        return next((s for s in self.sectors.values() if s.important), None) or next(iter(self.sectors.values()), None)

    def law(self, lid: int) -> Optional[Law]:
        return next((law for law in self.laws if law.lid == int(lid)), None)

    def war(self, wid: str) -> Optional[War]:
        return next((war for war in self.wars if war.wid == wid), None)

    def startup(self, suid: str) -> Optional[Startup]:
        return next((s for s in self.startups if s.suid == suid), None)

    def grave(self, gid: int) -> Optional[Grave]:
        return next((g for g in self.graves if g.gid == int(gid)), None)

    def current_project(self) -> Optional[Project]:
        return next((p for p in reversed(self.projects) if p.status == "running"), None)

    def projects_done(self) -> int:
        return sum(1 for p in self.projects if p.status == "done")

    def laws_in_force(self) -> List[Law]:
        return [law for law in self.laws if law.status in ("enforced", "testing")]

    def standing(self, sector: str = "") -> List[Building]:
        return [b for b in self.buildings if b.state != "demolishing" and (not sector or b.sector == sector)]

    # --- writes -----------------------------------------------------------------

    def log(self, kind: str, text: str, ref: str = "") -> Event:
        event = Event(ts=time.time(), day=round(self.game_days, 2), kind=kind if kind in EVENT_KINDS else "note",
                      text=str(text)[:240], ref=str(ref)[:40])
        self.timeline.append(event)
        self.timeline = _keep_last(self.timeline, KEEP_TIMELINE)
        self.updated_at = time.time()
        return event

    def add_grave(self, grave: Grave) -> Grave:
        self.graves.append(grave)
        self.graves = _keep_last(self.graves, KEEP_GRAVES)
        return grave

    def add_project(self, project: Project) -> Project:
        self.projects.append(project)
        self.projects = _keep_last(self.projects, KEEP_PROJECTS)
        return project

    def add_command(self, text: str) -> None:
        self.commands.append(str(text)[:2000])
        self.commands = _keep_last(self.commands, KEEP_COMMANDS)

    def trim(self) -> None:
        if len(self.buildings) > KEEP_BUILDINGS:
            # Oldest demolished first, then the oldest standing in the oldest era — the planet keeps its newest skyline.
            ordered = sorted(self.buildings, key=lambda b: (b.state != "demolishing", b.era, b.built_day))
            drop = {id(b) for b in ordered[: len(self.buildings) - KEEP_BUILDINGS]}
            self.buildings = [b for b in self.buildings if id(b) not in drop]

    # --- the compact form -------------------------------------------------------

    def to_compact(self) -> Dict[str, Any]:
        """What goes on disk: arrays, codes and indexes instead of named records."""
        self.trim()
        order = list(self.sectors)
        where = {sid: index for index, sid in enumerate(order)}

        def at(sid: str) -> int:
            return where.get(sid, -1)

        return {
            "f": FORMAT, "id": self.id, "n": self.name, "o": self.office_id, "g": self.goal,
            "t": [round(self.created_at, 1), round(self.updated_at, 1), round(self.started_at, 1)],
            "st": self.status, "sp": self.speed,
            "run": [round(self.run_until, 1), int(self.duration), round(self.real_seconds, 1), round(self.game_days, 3),
                    round(self.spent, 1)],
            "era": self.era, "tp": self.tech_points, "tech": self.techs[-12:],
            "T": {k: list(v) for k, v in self.tables.items()},
            "S": [[s.sid, s.name, round(s.lat, 2), round(s.lon, 2), _code(KINDS, s.kind, 2), s.gov, s.influence,
                   round(s.founded_day, 2), int(s.startup), int(s.important)] for s in self.sectors.values()],
            "B": [[b.aid, b.code, round(b.born_day, 2), b.parents[:2], int(b.state == "asleep"), b.home, b.name,
                   b.role, at(b.sector), b.last_busy] for b in self.bots.values()],
            "U": [[u.bid, at(u.sector), _code(KINDS, u.kind, 2), u.floors, u.era, u.plot, round(u.built_day, 2),
                   _code(BUILD_STATES, u.state), round(u.progress, 3), u.why] for u in self.buildings],
            "nb": self.next_building, "sky": [self.stations, self.planets],
            "L": [[w.lid, w.text, _code(LAW_SCOPES, w.scope), at(w.sector), _code(LAW_STATUSES, w.status), w.by,
                   round(w.day, 2), w.note, w.trial_job, w.code] for w in self.laws],
            "nl": self.next_law,
            "W": [[w.wid, at(w.a), at(w.b), w.a_stance, w.b_stance, w.reason, _code(WAR_STATUSES, w.status),
                   w.cases, w.winner, w.decision, w.by, w.why, round(w.opened_at, 1), round(w.deadline, 1),
                   round(w.resolved_at, 1), round(w.day, 2), int(w.applied)] for w in self.wars[-60:]],
            "SU": [[s.suid, s.name, s.idea, s.why, s.founders, _code(STARTUP_STATUSES, s.status), at(s.sector),
                    round(s.day, 2), s.by, s.from_war, int(s.applied)] for s in self.startups[-60:]],
            "G": [[g.gid, g.aid, g.name, g.role, g.sector, round(g.born_day, 2), round(g.died_day, 2), g.epitaph,
                   int(g.retired), g.code, int(g.rejoined)] for g in self.graves],
            "ng": self.next_grave,
            "P": [[p.n, p.title, p.request[:1200], p.why, p.job_id, p.status, round(p.started_at, 1),
                   round(p.ended_at, 1), round(p.day, 2), p.summary[:600]] for p in self.projects],
            "E": [[round(e.ts, 1), e.day, _code(EVENT_KINDS, e.kind, len(EVENT_KINDS) - 1), e.text, e.ref]
                  for e in self.timeline],
            "C": list(self.commands), "set": dict(self.settings), "seed": self.seed, "stall": self.stalled,
            "note": self.note, "bd": [self.births, self.deaths],
        }

    @classmethod
    def from_compact(cls, raw: Dict[str, Any]) -> "World":
        world = cls(id=str(raw.get("id") or new_id("wld")), name=str(raw.get("n") or "World"))
        world.office_id = str(raw.get("o") or "")
        world.goal = str(raw.get("g") or "")
        created, updated, started = (list(raw.get("t") or []) + [0, 0, 0])[:3]
        world.created_at, world.updated_at, world.started_at = float(created or time.time()), float(updated or 0), float(started or 0)
        world.status = str(raw.get("st") or "idle")
        world.speed = str(raw.get("sp") or DEFAULT_SPEED) if raw.get("sp") in SPEEDS else DEFAULT_SPEED
        run_until, duration, real_seconds, game_days, spent = (list(raw.get("run") or []) + [0, 0, 0, 0, 0])[:5]
        world.run_until, world.duration = float(run_until or 0), int(duration or 0)
        world.real_seconds, world.game_days = float(real_seconds or 0), float(game_days or 0)
        world.spent = float(spent or 0)
        world.era = max(0, min(len(ERAS) - 1, int(raw.get("era") or 0)))
        world.tech_points = int(raw.get("tp") or 0)
        world.techs = [t for t in (raw.get("tech") or []) if isinstance(t, dict)]
        tables = raw.get("T") or {}
        world.tables = {k: [str(x) for x in (tables.get(k) or [])] for k in ("roles", "members", "skills")}
        order: List[str] = []
        for row in raw.get("S") or []:
            try:
                sid, name, lat, lon, kind, gov, influence, founded, startup, important = (list(row) + [0] * 10)[:10]
                world.sectors[str(sid)] = Sector(sid=str(sid), name=str(name), lat=float(lat), lon=float(lon),
                                                 kind=_word(KINDS, kind, "office"), gov=str(gov or ""),
                                                 influence=int(influence or 0), founded_day=float(founded or 0),
                                                 startup=bool(startup), important=bool(important))
                order.append(str(sid))
            except (TypeError, ValueError):
                continue

        def sid_at(index: Any) -> str:
            try:
                position = int(index)
            except (TypeError, ValueError):
                return ""
            return order[position] if 0 <= position < len(order) else ""

        for row in raw.get("B") or []:
            try:
                aid, code, born, parents, asleep, home, name, role, sector, busy = (list(row) + [0] * 10)[:10]
                world.bots[str(aid)] = Bot(aid=str(aid), code=str(code), born_day=float(born or 0),
                                           parents=[str(p) for p in (parents or [])][:2],
                                           state="asleep" if asleep else "awake", home=int(home or 0),
                                           name=str(name or ""), role=str(role or ""), sector=sid_at(sector),
                                           last_busy=int(busy or 0))
            except (TypeError, ValueError):
                continue
        for row in raw.get("U") or []:
            try:
                bid, sector, kind, floors, era, plot, built, state, progress, why = (list(row) + [0] * 10)[:10]
                world.buildings.append(Building(bid=int(bid), sector=sid_at(sector), kind=_word(KINDS, kind, "office"),
                                                floors=int(floors or 1), era=int(era or 0), plot=int(plot or 0),
                                                built_day=float(built or 0), state=_word(BUILD_STATES, state, "standing"),
                                                progress=float(progress or 0), why=str(why or "")))
            except (TypeError, ValueError):
                continue
        world.next_building = int(raw.get("nb") or (max((b.bid for b in world.buildings), default=0) + 1))
        sky = list(raw.get("sky") or [0, 0]) + [0, 0]
        world.stations, world.planets = int(sky[0] or 0), int(sky[1] or 0)
        for row in raw.get("L") or []:
            try:
                lid, text, scope, sector, status, by, day, note, trial, code = (list(row) + [0] * 10)[:10]
                world.laws.append(Law(lid=int(lid), text=str(text), scope=_word(LAW_SCOPES, scope, "world"),
                                      sector=sid_at(sector), status=_word(LAW_STATUSES, status, "proposed"),
                                      by=str(by or ""), day=float(day or 0), note=str(note or ""),
                                      trial_job=str(trial or ""), code=int(code or 0)))
            except (TypeError, ValueError):
                continue
        world.next_law = int(raw.get("nl") or (max((w.lid for w in world.laws), default=0) + 1))
        for row in raw.get("W") or []:
            try:
                (wid, a, b, a_stance, b_stance, reason, status, cases, winner, decision, by, why, opened, deadline,
                 resolved, day, applied) = (list(row) + [0] * 17)[:17]
                world.wars.append(War(wid=str(wid), a=sid_at(a), b=sid_at(b), a_stance=str(a_stance),
                                      b_stance=str(b_stance), reason=str(reason),
                                      status=_word(WAR_STATUSES, status, "open"),
                                      cases=dict(cases) if isinstance(cases, dict) else {}, winner=str(winner or ""),
                                      decision=str(decision or ""), by=str(by or ""), why=str(why or ""),
                                      opened_at=float(opened or 0), deadline=float(deadline or 0),
                                      resolved_at=float(resolved or 0), day=float(day or 0), applied=bool(applied)))
            except (TypeError, ValueError):
                continue
        for row in raw.get("SU") or []:
            try:
                suid, name, idea, why, founders, status, sector, day, by, from_war, applied = (list(row) + [0] * 11)[:11]
                world.startups.append(Startup(suid=str(suid), name=str(name), idea=str(idea), why=str(why or ""),
                                              founders=[str(f) for f in (founders or [])],
                                              status=_word(STARTUP_STATUSES, status, "proposed"),
                                              sector=sid_at(sector), day=float(day or 0), by=str(by or ""),
                                              from_war=str(from_war or ""), applied=bool(applied)))
            except (TypeError, ValueError):
                continue
        for row in raw.get("G") or []:
            try:
                gid, aid, name, role, sector, born, died, epitaph, retired, code, rejoined = (list(row) + [0] * 11)[:11]
                world.graves.append(Grave(gid=int(gid), aid=str(aid), name=str(name), role=str(role),
                                          sector=str(sector or ""), born_day=float(born or 0),
                                          died_day=float(died or 0), epitaph=str(epitaph or ""), retired=bool(retired),
                                          code=str(code or ""), rejoined=bool(rejoined)))
            except (TypeError, ValueError):
                continue
        world.next_grave = int(raw.get("ng") or (max((g.gid for g in world.graves), default=0) + 1))
        for row in raw.get("P") or []:
            try:
                n, title, request, why, job_id, status, started_at, ended_at, day, summary = (list(row) + [0] * 10)[:10]
                world.projects.append(Project(n=int(n), title=str(title), request=str(request or ""), why=str(why or ""),
                                              job_id=str(job_id or ""), status=str(status or "done"),
                                              started_at=float(started_at or 0), ended_at=float(ended_at or 0),
                                              day=float(day or 0), summary=str(summary or "")))
            except (TypeError, ValueError):
                continue
        for row in raw.get("E") or []:
            try:
                ts, day, kind, text, ref = (list(row) + [0] * 5)[:5]
                world.timeline.append(Event(ts=float(ts), day=float(day or 0),
                                            kind=_word(EVENT_KINDS, kind, "note"), text=str(text),
                                            ref=str(ref or "")))
            except (TypeError, ValueError):
                continue
        world.commands = [str(c) for c in (raw.get("C") or [])][-KEEP_COMMANDS:]
        world.settings = dict(raw.get("set") or {})
        world.seed = int(raw.get("seed") or 0)
        world.stalled = str(raw.get("stall") or "")
        world.note = str(raw.get("note") or "")
        births, deaths = (list(raw.get("bd") or []) + [0, 0])[:2]
        world.births, world.deaths = int(births or 0), int(deaths or 0)

        # A world is never re-opened mid-run: the thread that ran it did not survive the engine stopping. It comes
        # back paused, so the owner sees it was interrupted and can resume it — never a ghost that looks alive.
        if world.status == "running":
            world.status = "paused"
            world.note = "Paused when Nyx stopped. Press Resume to carry on."
        for project in world.projects:
            if project.status == "running":
                project.status, project.ended_at = "stopped", project.ended_at or time.time()
        return world
