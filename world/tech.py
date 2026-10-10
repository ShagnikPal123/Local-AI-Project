"""The technology tree — from footpaths and carts to railways, maglev, hover vehicles and warp gates.

The owner (2026-10-10): *"Tech should be able to get super advanced, from trains to hover vehicles, it shows the user
their idea is growing."* Every technology here is earned with tech points (``sim.tech_points``: the office's finished
work, plus what the world's labs and data centres research while it runs), and each one changes something you can
see: a new vehicle on the roads, faster building, brighter grids, a new government ministry, stations in orbit.

The tree is fixed data, the same in every world, so "Hover vehicles" means the same thing everywhere. What differs is
the order: the Ministry of Science picks a *focus* branch, and that branch costs a quarter less.

Once researched, a technology stays researched (``world.researched``) — a repealed law or a failed project never takes
a railway away.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from world.state import World

BRANCHES: Dict[str, str] = {
    "transport": "Transport", "energy": "Energy", "construction": "Construction", "computing": "Computing",
    "space": "Space", "society": "Society",
}
FOCUS_DISCOUNT = 0.75

#: What moves people and goods, by transport level — the tab draws the vehicles for the highest level reached.
TRANSPORT_LEVELS = ("Footpaths", "Roads and carts", "Steam railways", "Motorways and cars", "Electric rail",
                    "Maglev lines", "Delivery drones", "Hover vehicles", "Skyways", "Space elevator", "Warp gates",
                    "Star lanes")


def _t(tid: str, name: str, branch: str, cost: int, needs: Tuple[str, ...], about: str, **effects: Any) -> Dict[str, Any]:
    return {"id": tid, "name": name, "branch": branch, "cost": cost, "needs": needs, "about": about, **effects}


#: The tree. Every tech's needs cost less than it does, so one pass in cost order settles it.
TREE: Tuple[Dict[str, Any], ...] = (
    # --- the start: every world has these from its first day
    _t("footpaths", "Footpaths", "transport", 0, (), "People walk between the first buildings.", transport=0),
    _t("fire", "Fire and shelter", "energy", 0, (), "A council fire and the first huts."),
    _t("timber", "Timber frames", "construction", 0, (), "Wooden halls, one or two floors."),
    _t("counting", "Counting", "computing", 0, (), "Tallies and ledgers — the first records."),
    _t("councils", "Councils", "society", 0, (),
       "A government of its own, apart from every sector: a chancellery, an assembly and the first ministries."),
    # --- settlement
    _t("stone", "Stone and mortar", "construction", 6, ("timber",), "Stone walls; buildings reach a second floor.",
       build=1.05),
    _t("carts", "Roads and carts", "transport", 8, ("footpaths",), "Dirt roads join the sectors; carts carry goods.",
       transport=1),
    _t("printing", "Printing", "computing", 10, ("counting",), "Plans are copied, not retold.", research=1.1),
    _t("watermills", "Water mills", "energy", 12, ("fire",), "Mills turn the first machines.", yields=1.15),
    _t("written_law", "Written law", "society", 14, ("councils",), "Laws are written down and a High Court opens."),
    _t("currency", "Currency", "society", 24, ("written_law",), "A Treasury keeps the world's accounts."),
    # --- township, city
    _t("steel", "Steel frames", "construction", 22, ("stone",), "Steel lets buildings climb past eight floors.",
       build=1.15),
    _t("telegraph", "Telegraph", "computing", 28, ("printing",), "Talk lines strung between the sectors.",
       research=1.1),
    _t("railways", "Steam railways", "transport", 30, ("carts", "steel"), "The first trains run between sectors.",
       transport=2, unlock="transit"),
    _t("coal_power", "Coal power", "energy", 35, ("watermills",), "Power plants rise beside the workplaces.",
       yields=1.3, unlock="power"),
    _t("glass", "Glass curtain walls", "construction", 48, ("steel",), "Lit glass towers; the city works at night.",
       build=1.1),
    _t("power_grid", "The power grid", "energy", 55, ("coal_power",), "Every building is wired; the night side glows.",
       yields=1.2),
    _t("motorways", "Motorways and cars", "transport", 60, ("railways", "coal_power"),
       "Paved motorways; cars and trucks fill them.", transport=3),
    _t("computers", "Computers", "computing", 65, ("telegraph", "power_grid"), "Machines that calculate.",
       research=1.25),
    # --- metropolis
    _t("internet", "The network", "computing", 95, ("computers",), "Every sector on one network.", research=1.25),
    _t("electric_rail", "Electric rail", "transport", 100, ("motorways", "power_grid"),
       "Quiet electric trains and metros.", transport=4),
    _t("solar", "Solar fields", "energy", 120, ("power_grid",), "Clean power from the sun.", yields=1.2),
    _t("arcologies", "Arcologies", "construction", 140, ("glass",), "Whole districts in one building.", build=1.25),
    _t("superconductors", "Superconductors", "energy", 150, ("solar", "computers"), "Power without loss.",
       yields=1.15),
    _t("ai_clusters", "AI clusters", "computing", 160, ("internet",), "Thinking machines help the research.",
       research=1.4),
    _t("maglev", "Maglev lines", "transport", 170, ("electric_rail", "superconductors"),
       "Trains float on magnets along raised guideways.", transport=5),
    # --- orbital
    _t("rocketry", "Rocketry", "space", 180, ("computers",), "A spaceport and a Space Agency.", unlock="spaceport"),
    _t("orbital_lift", "Orbital lift", "space", 220, ("rocketry",), "Stations in orbit for the advanced agents."),
    _t("drones", "Delivery drones", "transport", 220, ("maglev", "ai_clusters"), "Swarms of drones over every city.",
       transport=6),
    _t("fusion", "Fusion power", "energy", 260, ("superconductors",), "A star in a bottle.", yields=1.6),
    _t("quantum", "Quantum computing", "computing", 280, ("ai_clusters",), "Problems solved all at once.",
       research=1.6),
    _t("nanotubes", "Carbon nanotubes", "construction", 300, ("arcologies",), "Towers a kilometre tall.", build=1.4),
    _t("hover", "Hover vehicles", "transport", 320, ("drones", "fusion"),
       "Hover cars and freighters leave the roads behind.", transport=7),
    # --- stellar
    _t("fusion_drive", "Fusion drive", "space", 380, ("orbital_lift", "fusion"), "Ships between the stations."),
    _t("stellar_forge", "Stellar forges", "space", 420, ("fusion_drive",), "Artificial planets built to think."),
    _t("skyways", "Skyways", "transport", 450, ("hover",), "Glowing lanes in the sky for the hover traffic.",
       transport=8),
    _t("space_elevator", "Space elevator", "transport", 560, ("skyways", "nanotubes", "orbital_lift"),
       "A cable from the government district to orbit.", transport=9),
    _t("neural_lattice", "Neural lattice", "computing", 620, ("quantum",), "The world thinks as one mind.",
       research=2.0),
    # --- interstellar, ascendant
    _t("interstellar_probes", "Interstellar probes", "space", 650, ("stellar_forge",),
       "Probes to other stars; an Office of Interstellar Affairs."),
    _t("zero_point", "Zero-point energy", "energy", 700, ("fusion",), "Power from empty space.", yields=2.0),
    _t("programmable_matter", "Programmable matter", "construction", 800, ("nanotubes",),
       "Buildings that reshape themselves.", build=1.8),
    _t("warp_gates", "Warp gates", "transport", 900, ("space_elevator", "zero_point"),
       "Rings of light: step through in one sector, out in another.", transport=10),
    _t("dyson_swarm", "Dyson swarm", "energy", 1050, ("zero_point", "stellar_forge"),
       "Mirrors around the sun collect all its light.", yields=2.5),
    _t("star_lanes", "Star lanes", "transport", 1250, ("warp_gates", "interstellar_probes"),
       "Routes to other worlds.", transport=11),
)
BY_ID: Dict[str, Dict[str, Any]] = {t["id"]: t for t in TREE}
STARTING = tuple(t["id"] for t in TREE if t["cost"] == 0)


def cost(tech: Dict[str, Any], focus: str = "") -> int:
    return int(math.ceil(tech["cost"] * (FOCUS_DISCOUNT if focus and tech["branch"] == focus else 1.0)))


def has(world: World, tid: str) -> bool:
    return tid in world.researched


def advance(world: World) -> List[Dict[str, Any]]:
    """Research whatever the world can now afford. Returns the technologies that are new."""
    known = set(world.researched)
    new: List[Dict[str, Any]] = []
    changed = True
    while changed:  # a focus discount can make a tech cheaper than what it needs: settle in rounds
        changed = False
        for tech in sorted(TREE, key=lambda t: cost(t, world.focus)):
            if tech["id"] in known:
                continue
            if world.tech_points >= cost(tech, world.focus) and all(n in known for n in tech["needs"]):
                known.add(tech["id"])
                world.researched.append(tech["id"])
                new.append(tech)
                changed = True
    return new


def level(world: World) -> int:
    """The highest transport level the world has reached (``TRANSPORT_LEVELS``)."""
    return max((BY_ID[t].get("transport", 0) for t in world.researched if t in BY_ID), default=0)


def multiplier(world: World, key: str) -> float:
    """``build``, ``research`` or ``yields``: the product of every researched technology's bonus."""
    total = 1.0
    for tid in world.researched:
        tech = BY_ID.get(tid)
        if tech and key in tech:
            total *= float(tech[key])
    return total


def unlocked_kinds(world: World) -> set:
    return {BY_ID[t]["unlock"] for t in world.researched if t in BY_ID and BY_ID[t].get("unlock")}


def research_rate(world: World, floors: int, speed_factor: float) -> float:
    """Tech points per real second from the world's own labs and data centres while it runs. Square-rooted, so a
    bigger city researches faster but never runs away from the work its office actually does."""
    if floors <= 0:
        return 0.0
    return 0.02 * math.sqrt(floors) * multiplier(world, "research") * speed_factor


def next_up(world: World, count: int = 4) -> List[Dict[str, Any]]:
    known = set(world.researched)
    ready = [t for t in TREE if t["id"] not in known and all(n in known for n in t["needs"])]
    return sorted(ready, key=lambda t: cost(t, world.focus))[:count]


def status(world: World) -> Dict[str, Any]:
    """What the tab's Progress panel reads: every technology with done/ready/locked, and the transport ladder."""
    known = set(world.researched)
    rows = []
    for tech in TREE:
        done = tech["id"] in known
        ready = not done and all(n in known for n in tech["needs"])
        rows.append({"id": tech["id"], "name": tech["name"], "branch": tech["branch"], "cost": cost(tech, world.focus),
                     "needs": list(tech["needs"]), "about": tech["about"],
                     "state": "done" if done else "ready" if ready else "locked",
                     "transport": tech.get("transport")})
    upcoming = next_up(world, 1)
    return {"tree": rows, "branches": BRANCHES, "focus": world.focus, "transport": level(world),
            "transport_levels": list(TRANSPORT_LEVELS), "researched": len(known), "total": len(TREE),
            "next": ({"id": upcoming[0]["id"], "name": upcoming[0]["name"], "cost": cost(upcoming[0], world.focus)}
                     if upcoming else None),
            "research_bonus": round(multiplier(world, "research"), 2), "build_bonus": round(multiplier(world, "build"), 2),
            "yield_bonus": round(multiplier(world, "yields"), 2)}


def pick_focus(world: World, kinds: List[str]) -> str:
    """The Ministry of Science's focus when nobody chose one: what the world's sectors mostly do."""
    score: Dict[str, int] = {}
    table = {"lab": "computing", "data_center": "computing", "archive": "computing", "factory": "construction",
             "mine": "construction", "refinery": "energy", "farm": "energy", "bank": "society", "office": "society",
             "studio": "society", "tower": "construction"}
    for kind in kinds:
        branch = table.get(kind)
        if branch:
            score[branch] = score.get(branch, 0) + 1
    if not score:
        return "transport"
    return max(sorted(score), key=lambda b: score[b])


def clean_focus(value: Optional[str]) -> str:
    value = (value or "").strip().lower()
    return value if value in BRANCHES else ""
