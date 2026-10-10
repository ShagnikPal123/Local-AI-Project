"""How a world grows from the work its office did (U34, U35, U37) — pure functions, seeded, no model calls.

The owner: *"The world starts from nothing, as the ai grows and make more discovery the world itself grows til even we
can see it from a larger vantage point."* Nothing on the planet is decoration: every workplace floor is finished
tasks, every home is AIs who live there, every era is tech earned by work, and every grave is an agent the office let
go. The engine calls these once a second while the world runs; tests call them directly.

The rules, in one place (``docs/WORLD.md`` §5):

* each sector has a council hall (the capital has the capitol), ``1 + tasks_done // 6`` workplaces whose floors rise
  with its finished tasks, and one home per four AIs;
* a building is capped by the era it was built in — to grow past that cap it is torn down and rebuilt taller in the
  current era (*"old buildings are torn down when there's no use and newer taller, more fancy buildings are made"*);
* a sector has ``12 + 6 × era`` plots; when every sector is full, Orbital technology builds space stations and Stellar
  technology artificial planets — before that the world is stalled and says what it needs.

The upscale (owner, 2026-10-10: *"Building new structures and more should be more complex"*):

* building is done in phases (survey → foundation → frame → facade → fit-out, ``state.PHASES``), takes longer the
  taller it is, and **uses materials** that the workplaces produce (mines, factories and refineries most) — a site
  with nothing in stock waits, and says so;
* technology adds infrastructure: power plants (Coal power), transit stations (Steam railways), a spaceport in the
  government district (Rocketry), and it speeds building up (``tech.multiplier``);
* the government is a district of its own (``civics``) whose buildings — the Assembly, the Chancellery, the High
  Court and one per open ministry — rise here like everything else.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from world import (ERA_MAX_FLOORS, ERA_THRESHOLDS, ERAS, KEEP_BUILDINGS, ORBITAL_ERA, STELLAR_ERA, civics, genome,
                   tech)
from world.state import GOV_SID, WORKPLACES, Bot, Building, Grave, Sector, World, phase_of

CAPITAL_LAT = 18.0
AIS_PER_HOME = 4
TASKS_PER_WORKPLACE = 6
MAX_STATIONS = 6
MAX_PLANETS = 3

#: Materials a building costs: a base plus a share per floor. The government's buildings cost half again.
COST_BASE = 4.0
COST_PER_FLOOR = 3.0
#: Materials each standing building makes, per unit of ``build_rate`` and second (times ``PRODUCTION``).
YIELDS = {"mine": 3.0, "factory": 3.0, "refinery": 2.5, "farm": 1.5, "council": 1.0, "capitol": 1.0}
PRODUCTION = 4.0
MAX_STOCK = 5000.0
WAITING = "Waiting for materials — the mines and factories are behind."
#: The district's fixed layout: what stands on each plot around the seat.
GOV_PLOTS = ("capitol", "chancellery", "court", "ministry:works", "ministry:science", "ministry:treasury",
             "ministry:transport", "ministry:energy", "ministry:space", "ministry:interstellar", "spaceport")

#: The sector's purpose → the kind of workplace it works in (owner: "a workplace can be a normal office or a coal mine
#: or a data center or just a farm").
_KIND_WORDS: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("test", "qa", "review", "check", "verify", "audit", "quality", "refine"), "refinery"),
    (("code", "coder", "software", "backend", "frontend", "api", "engineer", "build", "app", "program", "server",
      "deploy", "devops", "infrastructure"), "data_center"),
    (("research", "science", "experiment", "study", "analysis", "analyse", "analyze", "investigat", "explore"), "lab"),
    (("design", "ui", "ux", "art", "brand", "visual", "creative", "video", "audio", "music", "game"), "studio"),
    (("finance", "money", "budget", "trading", "invest", "account", "pricing", "cost"), "bank"),
    (("data", "scrape", "mining", "mine", "collect", "crawl", "dataset", "gather"), "mine"),
    (("writ", "doc", "content", "copy", "knowledge", "archive", "report", "blog", "article"), "archive"),
    (("growth", "marketing", "seo", "outreach", "community", "sales", "audience", "farm"), "farm"),
    (("manufactur", "factory", "produc", "assembl", "hardware", "3d"), "factory"),
)

#: How a workplace kind modernises as the era rises — unless its sector is important (the capital).
_EVOLVE: Dict[str, Tuple[Tuple[int, str], ...]] = {
    "farm": ((3, "factory"),),
    "mine": ((3, "refinery"),),
    "archive": ((4, "data_center"),),
    "office": ((4, "tower"),),
}


# ---------------------------------------------------------------------------
# What the office looks like, from the world's side
# ---------------------------------------------------------------------------


@dataclass
class AgentView:
    id: str
    name: str
    role: str
    title: str = ""
    domain: str = ""
    kind: str = "worker"             # manager | worker | messenger | special
    section: str = ""
    status: str = "idle"
    employment: str = "full"
    rank: int = 0
    member: str = ""
    tasks_done: int = 0
    busy: bool = False               # has a task in the current project


@dataclass
class SectionView:
    id: str
    name: str
    purpose: str = ""
    order: int = 0
    color: str = ""


@dataclass
class OfficeView:
    """The handful of facts the sim needs from an office, so the sim never imports the office."""

    sections: List[SectionView] = field(default_factory=list)
    agents: List[AgentView] = field(default_factory=list)
    done_by_section: Dict[str, int] = field(default_factory=dict)
    top_id: str = ""
    let_go: Dict[str, str] = field(default_factory=dict)       # agent id → why (the office's staffing note)

    def tasks_done(self) -> int:
        return sum(self.done_by_section.values())


# ---------------------------------------------------------------------------
# Places
# ---------------------------------------------------------------------------


def place_sector(index: int, seed: int = 0) -> Tuple[float, float]:
    """Where sector number ``index`` sits: the capital near the top, the rest on a golden spiral, a little jittered."""
    if index <= 0:
        return CAPITAL_LAT, 0.0
    rng = random.Random(seed * 7919 + index)
    golden = math.pi * (3 - math.sqrt(5))
    # Spread over the band most visible from the default camera, then outwards as the world fills.
    t = (index + 0.5) / max(8.0, index + 2.0)
    lat = math.degrees(math.asin(max(-0.92, min(0.92, 1 - 2 * t)))) * 0.85 + rng.uniform(-6, 6)
    lon = math.degrees((index * golden) % (2 * math.pi)) - 180 + rng.uniform(-8, 8)
    return round(lat, 2), round(lon, 2)


def plots_for(era: int) -> int:
    return 12 + 6 * max(0, int(era))


def workplace_kind(purpose: str, *, era: int = 0, important: bool = False, current: str = "") -> str:
    """The kind of place a sector works in, from what it is for — and how that modernises with the era."""
    text = (purpose or "").lower()
    kind = current if current in WORKPLACES else ""
    if not kind:
        kind = next((k for words, k in _KIND_WORDS if any(w in text for w in words)), "office")
    if important:
        return kind
    for era_needed, newer in _EVOLVE.get(kind, ()):
        if era >= era_needed:
            kind = newer
    return kind


def era_for(points: int) -> int:
    era = 0
    for index, threshold in enumerate(ERA_THRESHOLDS):
        if points >= threshold:
            era = index
    return era


def tech_points(world: World, view: OfficeView) -> int:
    """Tech is earned by work: tasks, finished projects, laws that held, ideas settled, start-ups founded."""
    laws = sum(1 for law in world.laws if law.status == "enforced")
    wars = sum(1 for war in world.wars if war.status == "resolved")
    startups = sum(1 for s in world.startups if s.status == "founded")
    return int(view.tasks_done() + 3 * world.projects_done() + 2 * laws + 2 * wars + 3 * startups
               + int(world.research))


def next_era_at(era: int) -> Optional[int]:
    return ERA_THRESHOLDS[era + 1] if era + 1 < len(ERA_THRESHOLDS) else None


# ---------------------------------------------------------------------------
# Sectors and bots follow the office
# ---------------------------------------------------------------------------


def sync_sectors(world: World, view: OfficeView) -> List[Dict[str, Any]]:
    """A sector for every office section; names follow the office. Returns what changed."""
    changes: List[Dict[str, Any]] = []
    ordered = sorted(view.sections, key=lambda s: s.order)
    for index, section in enumerate(ordered):
        sector = world.sectors.get(section.id)
        if sector is None:
            # No sector is the head office any more: the government has its own district (``civics``), on place 0.
            first = not world.sectors
            lat, lon = place_sector(len(world.sectors) + 1, world.seed)
            sector = Sector(sid=section.id, name=section.name, lat=lat, lon=lon,
                            kind=workplace_kind(section.purpose, era=world.era),
                            gov=f"{section.name} Council", founded_day=round(world.game_days, 2))
            world.sectors[section.id] = sector
            world.log("founded", (f"{world.name}'s first sector, {section.name}, was settled." if first
                                  else f"A new sector, {section.name}, was settled."), ref=section.id)
            changes.append({"kind": "sector", "sector": sector_dict(sector)})
        elif sector.name != section.name:
            sector.name = section.name
            if not sector.important:
                sector.gov = f"{section.name} Council"
            changes.append({"kind": "sector", "sector": sector_dict(sector)})
    return changes


def _genome_for(world: World, agent: AgentView, *, generation: int = 0) -> str:
    tables = world.tables
    role_code = genome.code_of(tables.setdefault("roles", []), agent.role)
    model_code = genome.code_of(tables.setdefault("members", []), agent.member or "")
    extra = tables.setdefault("skills", [])
    skills = [genome.skill_code(word, extra) for word in genome.skills_for(agent.title or agent.role, agent.domain)]
    return genome.encode(generation=generation, role=role_code, rank=agent.rank,
                         part_time=agent.employment == "part_time", model=model_code, skills=skills)


def add_bot(world: World, agent: AgentView, *, parents: Iterable[str] = (), code: str = "") -> Bot:
    """A citizen for an office agent. ``parents`` and ``code`` are given when it was born, not hired."""
    parent_ids = [p for p in parents if p][:2]
    bot = Bot(aid=agent.id, code=code or _genome_for(world, agent), born_day=round(world.game_days, 2),
              parents=parent_ids, name=agent.name, role=agent.title or agent.role, sector=agent.section)
    world.bots[agent.id] = bot
    return bot


def sync_bots(world: World, view: OfficeView, *, project: int = 0) -> List[Dict[str, Any]]:
    """Bots follow the office: hires arrive, promotions and part time rewrite the code, the let-go get graves."""
    changes: List[Dict[str, Any]] = []
    present = {agent.id: agent for agent in view.agents}
    for agent in view.agents:
        bot = world.bots.get(agent.id)
        if bot is None:
            bot = add_bot(world, agent)
            changes.append({"kind": "bot", "bot": bot_dict(world, bot)})
            continue
        new_code = genome.with_employment(bot.code, rank=agent.rank, part_time=agent.employment == "part_time")
        moved = bot.sector != agent.section or bot.name != agent.name
        if new_code != bot.code or moved:
            bot.code, bot.sector, bot.name = new_code, agent.section, agent.name
            bot.role = agent.title or agent.role
            changes.append({"kind": "bot", "bot": bot_dict(world, bot)})
        if agent.busy or agent.status == "working":
            bot.last_busy = max(bot.last_busy, project)
    for aid in [aid for aid in world.bots if aid not in present]:
        bot = world.bots.pop(aid)
        why = view.let_go.get(aid, "")
        sector = world.sectors.get(bot.sector)
        grave = Grave(gid=world.next_grave, aid=aid, name=bot.name or "An AI", role=bot.role,
                      sector=sector.name if sector else "", born_day=bot.born_day,
                      died_day=round(world.game_days, 2),
                      epitaph=(why or "No longer needed — retired, and may rejoin.")[:200], retired=True,
                      code=bot.code)
        world.next_grave += 1
        world.add_grave(grave)
        world.deaths += 1
        world.log("death", f"{grave.name} ({grave.role}) was laid to rest. {grave.epitaph}", ref=str(grave.gid))
        changes.append({"kind": "grave", "grave": grave.as_dict(), "aid": aid})
    return changes


def sleep(world: World, view: OfficeView, *, project: int = 0) -> List[Dict[str, Any]]:
    """*"Ai pop up when needed, sleep when unneeded."* Part-time AIs sleep unless working; idle workers fall asleep
    two projects after they last had work; managers and anyone working are awake."""
    changes: List[Dict[str, Any]] = []
    for agent in view.agents:
        bot = world.bots.get(agent.id)
        if bot is None:
            continue
        state = "asleep" if _resting(agent, bot, project) else "awake"
        if state != bot.state:
            bot.state = state
            changes.append({"kind": "bot", "bot": bot_dict(world, bot)})
    return changes


def _resting(agent: AgentView, bot: Optional[Bot], project: int) -> bool:
    """Asleep: part time and not working, or a worker with nothing to do for two projects. Managers stay up."""
    if agent.status == "working" or agent.busy:
        return False
    if agent.employment == "part_time":
        return True
    if agent.kind == "manager":
        return False
    last = bot.last_busy if bot is not None else project
    return project >= 2 and project - last >= 2


def census_plan(world: World, view: OfficeView, *, project: int = 0) -> List[Dict[str, Any]]:
    """U40: *"it goes by sector and slowly checks each one to ensure they are needed or not. Going from gov, to ceo,
    to department and worker managers, to the works, to basically the slaves."* One step per sector and level."""
    by_sector: Dict[str, List[AgentView]] = {}
    for agent in view.agents:
        by_sector.setdefault(agent.section, []).append(agent)
    order = sorted(world.sectors.values(), key=lambda s: (not s.important, s.founded_day))  # stable: founding order
    steps: List[Dict[str, Any]] = []
    for sector in order:
        people = by_sector.get(sector.sid, [])
        top = [a for a in people if a.id == view.top_id]
        leaders = [a for a in people if a.kind == "manager" and a.id != view.top_id]
        heads, managers = (top, leaders) if top else (leaders[:1], leaders[1:])
        workers = [a for a in people if a.kind != "manager" and a.id != view.top_id]
        levels = (("government", heads), ("managers", managers), ("workers", workers))
        for level, group in levels:
            if not group and level != "workers":
                continue
            needed, resting = [], []
            for agent in group:
                (resting if _resting(agent, world.bots.get(agent.id), project) else needed).append(agent.id)
            steps.append({"sector": sector.sid, "sector_name": sector.name, "level": level,
                          "checked": len(group), "needed": needed, "resting": resting})
        builders = common_bots(world).get(sector.sid, 0)
        steps.append({"sector": sector.sid, "sector_name": sector.name, "level": "common bots",
                      "checked": builders, "needed": [], "resting": []})
    return steps


def apply_census(world: World, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    changes = []
    for step in steps:
        for aid, state in [(a, "awake") for a in step["needed"]] + [(a, "asleep") for a in step["resting"]]:
            bot = world.bots.get(aid)
            if bot is not None and bot.state != state:
                bot.state = state
                changes.append({"kind": "bot", "bot": bot_dict(world, bot)})
    return changes


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def _target(world: World, sector: Sector, view: OfficeView, people: int) -> List[Tuple[str, int]]:
    """What a sector should have standing right now: [(kind, floors)], most important first."""
    era_cap = ERA_MAX_FLOORS[world.era]
    done = view.done_by_section.get(sector.sid, 0)
    wanted: List[Tuple[str, int]] = [("capitol" if sector.important else "council", 1 + world.era // 2)]
    workplaces = 1 + done // TASKS_PER_WORKPLACE
    for index in range(workplaces):
        floors = 1 + max(0, done - TASKS_PER_WORKPLACE * index) // 2
        wanted.append((sector.kind, max(1, min(era_cap, floors))))
    unlocked = tech.unlocked_kinds(world)
    if "power" in unlocked and workplaces >= 2:
        for _ in range(min(3, 1 + workplaces // 6)):
            wanted.append(("power", max(1, min(era_cap, 1 + world.era // 3))))
    if "transit" in unlocked and (people or workplaces >= 2):
        wanted.append(("transit", max(1, min(era_cap, 1 + tech.level(world) // 3))))
    homes = max(1, math.ceil(people / AIS_PER_HOME)) if people else 0
    for _ in range(homes):
        wanted.append(("house", 1 + world.era // 2))
    return wanted


def _free_plot(used: Set[int], capacity: int) -> Optional[int]:
    return next((p for p in range(capacity) if p not in used), None)


def grow(world: World, view: OfficeView, *, dt: float, build_rate: float) -> List[Dict[str, Any]]:
    """One step of building: construction moves, the skyline follows the work, space opens when the planet is full."""
    changes: List[Dict[str, Any]] = []
    people: Dict[str, int] = {}
    for agent in view.agents:
        people[agent.section] = people.get(agent.section, 0) + 1
    civics.ensure(world)
    produce(world, dt=dt, build_rate=build_rate)

    # Construction and demolition move first, so a finished building counts below.
    faster = tech.multiplier(world, "build")
    for building in list(world.buildings):
        before = phase_of(building)
        if building.state == "constructing":
            speed = build_rate * faster / (1.0 + building.floors / 8.0)
            step = min(1.0 - building.progress, dt * speed)
            cost = build_cost(building) * step
            have = world.stock.get("materials", 0.0)
            if cost > have:
                step = step * have / cost if cost > 0 else step
                cost = have
            world.stock["materials"] = max(0.0, have - cost)
            if step <= 1e-6 and building.progress < 1.0:
                if building.why != WAITING:
                    building.why = WAITING
                    changes.append({"kind": "building", "building": building.as_dict()})
                continue
            if building.why == WAITING:
                building.why = ""
            building.progress = min(1.0, building.progress + step)
            if building.progress >= 1.0 - 1e-9:
                building.state, building.progress = "standing", 1.0
                changes.append({"kind": "building", "building": building.as_dict()})
            elif phase_of(building) != before:
                changes.append({"kind": "building", "building": building.as_dict()})
        elif building.state == "demolishing":
            building.progress = max(0.0, building.progress - dt * build_rate * faster * 2 / (1.0 + building.floors / 16.0))
            if building.progress <= 0.0:
                world.buildings.remove(building)
                changes.append({"kind": "building.gone", "bid": building.bid})

    capacity = plots_for(world.era)
    full_sectors = 0
    for sector in world.sectors.values():
        if not sector.important:
            evolved = workplace_kind("", era=world.era, important=False, current=sector.kind)
            if evolved != sector.kind:
                world.log("retool", f"{sector.name} modernised: its {sector.kind.replace('_', ' ')}s become "
                                    f"{evolved.replace('_', ' ')}s.", ref=sector.sid)
                sector.kind = evolved
                changes.append({"kind": "sector", "sector": sector_dict(sector)})
        wanted = _target(world, sector, view, people.get(sector.sid, 0))
        mine = [b for b in world.buildings if b.sector == sector.sid and b.state != "demolishing"]
        used = {b.plot for b in world.buildings if b.sector == sector.sid}
        busy = any(b.state != "standing" for b in world.buildings if b.sector == sector.sid)
        unmatched = list(mine)
        missing: List[Tuple[str, int]] = []
        for kind, floors in wanted:
            match = next((b for b in unmatched if b.kind == kind), None)
            if match is None and kind in WORKPLACES:
                match = next((b for b in unmatched if b.kind in WORKPLACES), None)
            if match is None:
                missing.append((kind, floors))
                continue
            unmatched.remove(match)
            if match.state != "standing":
                continue
            past_its_era = floors > ERA_MAX_FLOORS[match.era] and match.era < world.era
            wrong_trade = match.kind != kind
            if (past_its_era or wrong_trade) and not busy:
                # Torn down and rebuilt: taller, newer, or a different trade — one at a time per sector.
                match.state, match.why = "demolishing", (
                    f"Outdated: a {match.kind.replace('_', ' ')} from the {ERAS[match.era]} era, making way for a "
                    f"taller {kind.replace('_', ' ')}." if match.kind == kind else
                    f"{sector.name} now works as a {kind.replace('_', ' ')}.")
                world.log("teardown", f"{sector.name}: {match.why}", ref=str(match.bid))
                changes.append({"kind": "building", "building": match.as_dict()})
                busy = True
            elif floors > match.floors:
                match.floors = min(floors, ERA_MAX_FLOORS[match.era])
                changes.append({"kind": "building", "building": match.as_dict()})
        for kind, floors in missing:
            if busy and kind not in ("capitol", "council"):
                break
            plot = 0 if kind in ("capitol", "council") and 0 not in used else _free_plot(used | {0}, capacity)
            if plot is None:
                sector.full = True
                break
            used.add(plot)
            building = Building(bid=world.next_building, sector=sector.sid, kind=kind, floors=floors, era=world.era,
                                plot=plot, built_day=round(world.game_days, 2), state="constructing", progress=0.0)
            world.next_building += 1
            world.buildings.append(building)
            changes.append({"kind": "building", "building": building.as_dict()})
            busy = True
        else:
            sector.full = len(wanted) > capacity
        if sector.full:
            full_sectors += 1

    changes.extend(_grow_government(world))
    changes.extend(_space(world, full_sectors))
    return changes


def build_cost(building: Building) -> float:
    """Materials for the whole building; the government builds grander, so half again."""
    cost = COST_BASE + COST_PER_FLOOR * max(1, building.floors)
    return cost * (1.5 if building.sector == GOV_SID else 1.0)


def produce(world: World, *, dt: float, build_rate: float) -> None:
    """The economy (the Treasury's books): materials pile up from what stands; energy and compute are capacities."""
    materials = energy = compute = 0.0
    for building in world.buildings:
        if building.state != "standing":
            continue
        if building.kind == "power":
            energy += 6.0 * (1 + building.floors / 4.0)
        elif building.kind in ("data_center", "lab"):
            compute += building.floors
        made = YIELDS.get(building.kind, 1.0 if building.kind in WORKPLACES else 0.0)
        materials += made * (1 + building.floors / 10.0)
    gain = materials * tech.multiplier(world, "yields") * PRODUCTION * build_rate * dt
    world.stock["materials"] = min(MAX_STOCK, world.stock.get("materials", 0.0) + gain)
    world.stock["energy"] = round(energy * tech.multiplier(world, "yields"), 1)
    world.stock["compute"] = float(compute)


def _gov_wanted(world: World) -> List[Tuple[int, str, str, int]]:
    """The district right now: (plot, kind, ministry, floors). Plots are fixed, so a ministry keeps its place."""
    cap = ERA_MAX_FLOORS[world.era]
    era = world.era
    wanted = [(0, "capitol", "", max(1, min(cap, 1 + era // 2))),
              (1, "chancellery", "", max(1, min(cap, 2 + era * 2)))]
    if tech.has(world, "written_law"):
        wanted.append((2, "court", "", max(1, min(cap, 1 + era // 2))))
    for key in civics.open_ministries(world):
        wanted.append((GOV_PLOTS.index(f"ministry:{key}"), "ministry", key, max(1, min(cap, 1 + era))))
    if "spaceport" in tech.unlocked_kinds(world):
        wanted.append((GOV_PLOTS.index("spaceport"), "spaceport", "", 1))
    return wanted


def _grow_government(world: World) -> List[Dict[str, Any]]:
    changes: List[Dict[str, Any]] = []
    mine = [b for b in world.buildings if b.sector == GOV_SID]
    busy = sum(1 for b in mine if b.state != "standing")
    for plot, kind, tag, floors in _gov_wanted(world):
        match = next((b for b in mine if b.kind == kind and b.tag == tag and b.state != "demolishing"), None)
        if match is None:
            if busy >= 2 or any(b.plot == plot for b in mine):
                continue
            building = Building(bid=world.next_building, sector=GOV_SID, kind=kind, floors=floors, era=world.era,
                                plot=plot, built_day=round(world.game_days, 2), state="constructing", progress=0.0,
                                tag=tag)
            world.next_building += 1
            world.buildings.append(building)
            changes.append({"kind": "building", "building": building.as_dict()})
            busy += 1
        elif match.state == "standing" and floors > match.floors:
            if floors > ERA_MAX_FLOORS[match.era] and match.era < world.era:
                if busy < 2:
                    match.state = "demolishing"
                    match.why = (f"Rebuilt for the {ERAS[world.era]} era: the old "
                                 f"{civics.ministry_for(tag) or kind.replace('_', ' ')} is too small.")
                    world.log("teardown", f"The government: {match.why}", ref=str(match.bid))
                    changes.append({"kind": "building", "building": match.as_dict()})
                    busy += 1
            else:
                match.floors = min(floors, ERA_MAX_FLOORS[match.era])
                changes.append({"kind": "building", "building": match.as_dict()})
    return changes


def _space(world: World, full_sectors: int) -> List[Dict[str, Any]]:
    """When the planet is full: stations at Orbital, artificial planets at Stellar; before that, stalled."""
    changes: List[Dict[str, Any]] = []
    everything_full = bool(world.sectors) and full_sectors >= len(world.sectors)
    crowded = len(world.buildings) >= KEEP_BUILDINGS - 40
    if not (everything_full or crowded):
        if world.stalled:
            world.stalled = ""
            changes.append({"kind": "stall", "stalled": ""})
        return changes
    orbital = world.era >= ORBITAL_ERA or tech.has(world, "orbital_lift")
    stellar = world.era >= STELLAR_ERA or tech.has(world, "stellar_forge")
    if orbital:
        if world.stalled:
            world.stalled = ""
            changes.append({"kind": "stall", "stalled": ""})
        if world.stations < MAX_STATIONS and (world.stations < 1 or full_sectors >= len(world.sectors)):
            world.stations += 1
            world.log("station", f"The planet is full — station {world.stations} went up in orbit for the more "
                                 "advanced agents.")
            changes.append({"kind": "sky", "stations": world.stations, "planets": world.planets})
        if stellar and world.stations >= 3 and world.planets < MAX_PLANETS:
            world.planets += 1
            world.log("station", f"Artificial planet {world.planets} was built.")
            changes.append({"kind": "sky", "stations": world.stations, "planets": world.planets})
        return changes
    need = ERA_THRESHOLDS[ORBITAL_ERA] - world.tech_points
    reason = (f"The planet is full: every sector has built on all its plots. It grows again with more plots each era "
              f"and expands into space at {ERAS[ORBITAL_ERA]} ({max(0, need)} more tech points).")
    if world.stalled != reason:
        if not world.stalled:
            world.log("stall", "The world stopped growing: the planet is full.")
        world.stalled = reason
        changes.append({"kind": "stall", "stalled": reason})
    return changes


def common_bots(world: World) -> Dict[str, int]:
    """Low-power common bots per sector: builders on every site, keepers for the infrastructure. No model."""
    counts: Dict[str, int] = {}
    for building in world.buildings:
        if building.state in ("constructing", "demolishing"):
            add = 2 + world.era // 2
        elif building.kind in WORKPLACES and building.floors >= 4:
            add = 1
        else:
            continue
        counts[building.sector] = counts.get(building.sector, 0) + add
    return {sid: min(40, n) for sid, n in counts.items()}


# ---------------------------------------------------------------------------
# What the tab reads
# ---------------------------------------------------------------------------


def sector_dict(sector: Sector) -> Dict[str, Any]:
    return {"sid": sector.sid, "name": sector.name, "lat": sector.lat, "lon": sector.lon, "kind": sector.kind,
            "gov": sector.gov, "influence": sector.influence, "founded_day": sector.founded_day,
            "startup": sector.startup, "important": sector.important, "full": sector.full}


def bot_dict(world: World, bot: Bot) -> Dict[str, Any]:
    parts = genome.decode(bot.code) or {}
    extra = world.tables.get("skills", [])
    return {"aid": bot.aid, "code": bot.code, "pretty": genome.pretty(bot.code), "born_day": bot.born_day,
            "parents": bot.parents, "state": bot.state, "home": bot.home, "name": bot.name, "role": bot.role,
            "sector": bot.sector, "generation": parts.get("generation", 0),
            "skills": [genome.skill_word(c, extra) for c in parts.get("skills", [])]}
