"""The government as its own place — never a head office (owner, 2026-10-10: *"No head office but a separate
government with splits and more"*).

Before this, the office's first section was the capital: its sector held the capitol, its council was "World
Government", and it was also an ordinary workplace. Now every sector is a sector, and the government is a district of
its own on the planet, split into branches:

* **The Chancellery** (executive) — led by the office's top manager (Big Kahuna when it is up). It plans every
  project, and it is who the office hears the projects from.
* **The Assembly** (legislature) — one seat per sector, held by that sector's manager. Every law the government
  proposes goes to a vote before it is tried; the owner's own laws do not (the owner is above the government).
* **The High Court** (judiciary) — three justices, once the world has written law. It judges the contests of ideas.
* **Ministries** — opened as technology allows: Works and Science from the start, then the Treasury, Transport,
  Energy, the Space Agency and the Office of Interstellar Affairs. Each has a minister (a real agent of the office),
  a building in the district, and a job the sim actually does (Science sets the research focus; Works supplies the
  building sites; the Treasury keeps the stock …).

Seats are filled from the office's own agents every tick — nobody is invented — and the votes are worked out here
without a model (seeded, so the same law in the same world gets the same vote).
"""

from __future__ import annotations

import math
import random
import zlib
from typing import Any, Dict, List, Optional, Tuple

from world import ERAS, tech
from world.state import GOV_SID, Law, World

#: Where the district sits on a new world; sectors take the places after it (``sim.place_sector``).
SEAT_LAT, SEAT_LON = 18.0, 0.0

BRANCHES = (
    ("executive", "The Chancellery", "Chancellor", "Plans every project and speaks for the world to its office."),
    ("legislature", "The Assembly", "Speaker", "One seat per sector; votes on every law the government proposes."),
    ("judiciary", "The High Court", "Chief Justice", "Judges the contests of ideas between sectors."),
)

#: (key, name, the technology that opens it, what it does, the role words that make a good minister)
MINISTRIES: Tuple[Tuple[str, str, str, str, Tuple[str, ...]], ...] = (
    ("works", "Ministry of Works", "councils",
     "Plans the roads, power and buildings, and keeps the building sites supplied.",
     ("engineer", "architect", "builder", "devops", "infra")),
    ("science", "Ministry of Science", "councils", "Chooses what the world researches next.",
     ("research", "scien", "analyst", "data")),
    ("treasury", "The Treasury", "currency", "Keeps the world's stock of materials, energy and compute.",
     ("financ", "account", "budget", "trad")),
    ("transport", "Ministry of Transport", "railways", "Runs the rail lines and, later, the skyways.",
     ("plan", "operat", "logist")),
    ("energy", "Ministry of Energy", "coal_power", "Builds and runs the power plants.",
     ("engineer", "devops", "ops")),
    ("space", "Space Agency", "rocketry", "Launches the stations, the elevator and the artificial planets.",
     ("research", "engineer", "scien")),
    ("interstellar", "Office of Interstellar Affairs", "interstellar_probes", "Speaks for the world to other stars.",
     ("writ", "design", "research")),
)
MINISTRY_NAMES = {key: name for key, name, *_ in MINISTRIES}


def _angle(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Degrees between two places on the sphere."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d = math.radians(lon2 - lon1)
    cos = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(d)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def _free_spot(world: World) -> Tuple[float, float]:
    """The seat for a world that had none (an old file): the classic spot if it is free, else the open place on a
    golden spiral farthest from every sector."""
    places = [(s.lat, s.lon) for s in world.sectors.values()]
    if all(_angle(SEAT_LAT, SEAT_LON, lat, lon) > 24 for lat, lon in places):
        return SEAT_LAT, SEAT_LON
    golden = math.pi * (3 - math.sqrt(5))
    best, best_gap = (SEAT_LAT, SEAT_LON), -1.0
    for index in range(120):
        t = (index + 0.5) / 120
        lat = math.degrees(math.asin(1 - 2 * t)) * 0.8
        lon = math.degrees((index * golden) % (2 * math.pi)) - 180
        gap = min((_angle(lat, lon, a, b) for a, b in places), default=180.0)
        if gap > best_gap:
            best, best_gap = (round(lat, 2), round(lon, 2)), gap
    return best


def ensure(world: World) -> bool:
    """Give the world its government district if it has none. True when it was just made."""
    gov = world.government
    if gov.get("lat") is not None:
        return False
    lat, lon = (SEAT_LAT, SEAT_LON) if not world.sectors else _free_spot(world)
    gov.update({"name": f"Government of {world.name}", "lat": lat, "lon": lon, "head": "", "seats": {},
                "justices": [], "ministers": {}, "opened": [], "last_vote": None})
    world.log("founded", f"The government of {world.name} was seated in its own district — apart from every sector, "
                         "with a Chancellery, an Assembly and ministries.")
    return True


def name(world: World) -> str:
    return str(world.government.get("name") or f"Government of {world.name}")


def signer(world: World, branch: str = "executive") -> str:
    """Who signs what the government sends: "The Chancellery of Testland"."""
    title = next((label for key, label, *_ in BRANCHES if key == branch), "The Government")
    return f"{title} of {world.name}"[:60]


def court_name(world: World) -> str:
    return signer(world, "judiciary")


def location(world: World) -> Tuple[float, float]:
    ensure(world)
    return float(world.government["lat"]), float(world.government["lon"])


def open_ministries(world: World) -> List[str]:
    return [key for key, _name, needs, *_ in MINISTRIES if needs in world.researched or needs in tech.STARTING]


def seat(world: World, view: Any) -> bool:
    """Fill the seats from the office's agents. Returns True when anything changed (the tab is told)."""
    ensure(world)
    gov = world.government
    before = (gov.get("head"), dict(gov.get("seats") or {}), list(gov.get("justices") or []),
              dict(gov.get("ministers") or {}), list(gov.get("opened") or []))
    agents = list(view.agents)
    by_id = {a.id: a for a in agents}
    gov["head"] = view.top_id if view.top_id in by_id else ""

    seats: Dict[str, str] = {}
    for sector in world.sectors.values():
        people = [a for a in agents if a.section == sector.sid and a.id != gov["head"]]
        managers = sorted((a for a in people if a.kind == "manager"), key=lambda a: (-a.rank, a.id))
        pick = managers[0] if managers else (sorted(people, key=lambda a: (-a.rank, -a.tasks_done, a.id)) or [None])[0]
        if pick is not None:
            seats[sector.sid] = pick.id
    gov["seats"] = seats

    taken = {gov["head"], *seats.values()}
    justices: List[str] = []
    if tech.has(world, "written_law") or "written_law" in tech.STARTING:
        senior = sorted((a for a in agents if a.id not in taken), key=lambda a: (-a.rank, -a.tasks_done, a.id))
        justices = [a.id for a in senior[:3]]
    gov["justices"] = justices
    taken |= set(justices)

    opened = open_ministries(world)
    newly = [key for key in opened if key not in (gov.get("opened") or [])]
    gov["opened"] = opened
    ministers: Dict[str, str] = {}
    pool = [a for a in agents if a.id not in taken] or agents
    for key in opened:
        words = next(w for k, _n, _t, _d, w in MINISTRIES if k == key)
        current = (gov.get("ministers") or {}).get(key, "")
        if current in by_id and current not in ministers.values():
            ministers[key] = current
            continue
        fit = [a for a in pool if a.id not in ministers.values()
               and any(w in f"{a.role} {a.title} {a.domain}".lower() for w in words)]
        rest = [a for a in pool if a.id not in ministers.values()]
        choice = (fit or rest or [None])[0]
        if choice is not None:
            ministers[key] = choice.id
    gov["ministers"] = ministers
    for key in newly:
        if before[4] or key not in ("works", "science"):
            world.log("ministry", f"The {MINISTRY_NAMES[key]} opened: "
                                  f"{next(d for k, _n, _t, d, _w in MINISTRIES if k == key)}")
    after = (gov.get("head"), seats, justices, ministers, opened)
    return after != before


def _stable(text: str) -> random.Random:
    return random.Random(zlib.crc32(text.encode("utf-8")))


def vote(world: World, law: Law) -> Dict[str, Any]:
    """The Assembly votes on a law the government proposed. Seeded per world, law and seat — no model is asked, so
    a vote never costs the owner anything and the same law always gets the same vote. Passes on more yes than no."""
    ensure(world)
    seats = dict(world.government.get("seats") or {})
    yes = no = abstain = 0
    for sid in sorted(seats):
        sector = world.sectors.get(sid)
        influence = sector.influence if sector else 0
        rng = _stable(f"{world.seed}:{law.lid}:{law.text}:{sid}")
        if law.scope == "sector" and law.sector and law.sector != sid:
            # Another sector's rule: most stay out of it.
            if rng.random() < 0.6:
                abstain += 1
                continue
            p_yes = 0.8
        elif law.scope == "sector" and law.sector == sid:
            p_yes = 0.55 + 0.05 * max(-3, min(3, influence))
        else:
            p_yes = 0.68 + 0.04 * max(-4, min(4, influence))
        if rng.random() < p_yes:
            yes += 1
        else:
            no += 1
    passed = yes > no or not seats
    law.votes = f"{yes}-{no}-{abstain}"
    tally = {"lid": law.lid, "yes": yes, "no": no, "abstain": abstain, "passed": passed,
             "day": round(world.game_days, 2), "text": law.text[:120]}
    world.government["last_vote"] = tally
    if not passed:
        law.status = "rejected"
        law.note = f"The Assembly voted it down, {yes} for and {no} against."
    elif seats:
        law.note = (law.note + " " if law.note else "") + f"The Assembly passed it {yes}–{no}."
    world.log("vote", f"The Assembly {'passed' if passed else 'rejected'} “{law.text[:90]}” ({yes}–{no}"
                      f"{f', {abstain} abstained' if abstain else ''}).", ref=str(law.lid))
    return tally


def snapshot(world: World) -> Dict[str, Any]:
    """The government as the tab reads it: branches with who sits where, ministries, and the last vote."""
    ensure(world)
    gov = world.government

    def who(aid: str) -> Dict[str, Any]:
        bot = world.bots.get(aid)
        return {"aid": aid, "name": bot.name if bot else "—", "role": bot.role if bot else "",
                "sector": bot.sector if bot else ""}

    seats = gov.get("seats") or {}
    branches = []
    for key, label, title, about in BRANCHES:
        if key == "judiciary" and not gov.get("justices"):
            branches.append({"key": key, "name": label, "title": title, "about": about, "open": False,
                             "members": [], "note": "Opens with written law."})
            continue
        members = ([who(gov["head"])] if key == "executive" and gov.get("head") else
                   [{**who(aid), "seat": world.sectors[sid].name if sid in world.sectors else ""}
                    for sid, aid in seats.items()] if key == "legislature" else
                   [who(aid) for aid in gov.get("justices") or []] if key == "judiciary" else [])
        branches.append({"key": key, "name": label, "title": title, "about": about, "open": True, "members": members})
    ministries = []
    for key, label, needs, about, _words in MINISTRIES:
        opened = key in (gov.get("opened") or [])
        minister = (gov.get("ministers") or {}).get(key, "")
        entry = {"key": key, "name": label, "about": about, "open": opened, "needs": tech.BY_ID[needs]["name"],
                 "minister": who(minister) if minister else None}
        if key == "science":
            entry["focus"] = world.focus
            entry["focus_by"] = world.focus_by
        if key == "treasury":
            entry["stock"] = {k: round(v, 1) for k, v in world.stock.items()}
        ministries.append(entry)
    return {"name": name(world), "lat": gov.get("lat"), "lon": gov.get("lon"), "branches": branches,
            "ministries": ministries, "last_vote": gov.get("last_vote"), "signer": signer(world),
            "era": ERAS[world.era]}


def ministry_for(building_tag: str) -> Optional[str]:
    return MINISTRY_NAMES.get(building_tag)
