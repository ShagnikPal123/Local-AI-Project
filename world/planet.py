"""What the planet itself is like — decided once from the world's seed, so no two worlds look the same.

The owner (2026-10-10): *"randomize how the planet actually looks and add a lot more size"*. The planet's type, size,
seas, mountains, air, rings and moons are a small descriptor made here from ``world.seed``; the tab turns it into
terrain (``panels/world/planet/surface.ts``). Nothing is stored: the same seed always gives the same planet, so an old
world file gets its planet the first time it is opened and keeps it.

The descriptor is data (colours as ``#rrggbb``, numbers in fixed ranges) — the renderer never runs anything from it.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Tuple

#: Each type: label, a line about it, land colours (low, high, peak), sea colours (deep, shallow), sea level (how much
#: of the planet is under water, -1..1 of the noise), mountain strength, ice caps, air colour, cloud cover, and whether
#: life greens it as the eras pass (terraforming).
TYPES: Dict[str, Dict[str, Any]] = {
    "terran": {"label": "Terran world", "about": "Blue seas, green and brown continents, white poles.",
               "land": ("#4f7a43", "#7a6a4f", "#e8ecef"), "sea": ("#0f2a4a", "#1f5f8f"), "sea_level": 0.02,
               "mountains": 0.8, "ice": 0.86, "air": "#8fb4ff", "clouds": 0.55, "greens": True},
    "desert": {"label": "Desert world", "about": "Dune seas and dry canyons; water only in a few deep basins.",
               "land": ("#c9a36b", "#a8683f", "#f1dcb0"), "sea": ("#1d4a5c", "#2f7f8a"), "sea_level": -0.38,
               "mountains": 0.9, "ice": 0.97, "air": "#ffc48a", "clouds": 0.15, "greens": True},
    "ocean": {"label": "Ocean world", "about": "An archipelago scattered across one great ocean.",
              "land": ("#5f8f4f", "#8f8a5f", "#eef2f4"), "sea": ("#08304f", "#1a8fb0"), "sea_level": 0.3,
              "mountains": 0.6, "ice": 0.9, "air": "#7fd0ff", "clouds": 0.7, "greens": True},
    "ice": {"label": "Ice world", "about": "Glaciers and frozen seas; the cities keep warm under glass.",
            "land": ("#c9d6e3", "#9fb0c4", "#ffffff"), "sea": ("#132a40", "#3d6f8f"), "sea_level": -0.05,
            "mountains": 0.7, "ice": 0.55, "air": "#bfe4ff", "clouds": 0.4, "greens": False},
    "volcanic": {"label": "Volcanic world", "about": "Black basalt plains split by rivers of lava.",
                 "land": ("#2e2a28", "#4a3b33", "#8a7a70"), "sea": ("#3a0a00", "#ff5a1f"), "sea_level": -0.22,
                 "mountains": 1.2, "ice": 1.1, "air": "#ff8a5c", "clouds": 0.35, "greens": False, "lava": True},
    "jungle": {"label": "Jungle world", "about": "Rainforest from pole to pole, wide brown rivers and warm seas.",
               "land": ("#2f6b2f", "#4f7a3a", "#a8b89a"), "sea": ("#0f3a3a", "#2a8a7a"), "sea_level": -0.02,
               "mountains": 0.7, "ice": 0.95, "air": "#a8ffcf", "clouds": 0.75, "greens": True},
    "alien": {"label": "Alien world", "about": "Violet forests, teal seas and a magenta sky.",
              "land": ("#5a3f8a", "#8a4f7a", "#e0d0ff"), "sea": ("#08303a", "#1fa8a0"), "sea_level": 0.05,
              "mountains": 0.9, "ice": 0.9, "air": "#ff8af0", "clouds": 0.45, "greens": False},
    "tundra": {"label": "Tundra world", "about": "Grey-green steppe, cold steel seas and wide ice caps.",
               "land": ("#6f7a5f", "#7f7a6f", "#f0f2f4"), "sea": ("#14283a", "#3f6a80"), "sea_level": 0.0,
               "mountains": 0.65, "ice": 0.7, "air": "#a8c4e0", "clouds": 0.5, "greens": True},
    "rust": {"label": "Rust world", "about": "Red dust, old craters and thin air — no seas at all, yet.",
             "land": ("#9a4a2a", "#7a3a24", "#d8a080"), "sea": ("#3a1a10", "#6a2a18"), "sea_level": -0.9,
             "mountains": 1.0, "ice": 0.93, "air": "#ffb08a", "clouds": 0.08, "greens": True},
}
TYPE_ORDER = tuple(TYPES)

#: The base radius in scene units; a planet is 1.0–1.4 times it (the tab multiplies).
BASE_RADIUS = 16.0

_MOON_COLORS = ("#b8b2a8", "#8f8a84", "#d8c8a8", "#a8b8c8", "#c8a890")
_RING_COLORS = ("#d8c8a8", "#a8b8d8", "#c8a8d8", "#e0d0b0")


def _jitter(color: str, rng: random.Random, amount: float = 0.08) -> str:
    """The type's colour, shifted a little so two terran worlds are not the same green."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    shift = [rng.uniform(-amount, amount) * 255 for _ in range(3)]
    return "#" + "".join(f"{max(0, min(255, int(c + s))):02x}" for c, s in zip((r, g, b), shift))


def describe(seed: int) -> Dict[str, Any]:
    """The planet for ``seed``: always the same answer for the same seed."""
    rng = random.Random(int(seed) * 2654435761 % (2 ** 32) or 1)
    kind = TYPE_ORDER[rng.randrange(len(TYPE_ORDER))]
    base = TYPES[kind]
    moons: List[Dict[str, Any]] = []
    for index in range(rng.choice((0, 1, 1, 2, 2, 3))):
        moons.append({"size": round(rng.uniform(0.08, 0.26), 3), "distance": round(rng.uniform(2.2, 4.2) + index * 0.9, 2),
                      "speed": round(rng.uniform(0.01, 0.05), 4), "tilt": round(rng.uniform(-0.5, 0.5), 3),
                      "color": rng.choice(_MOON_COLORS)})
    rings = rng.random() < 0.3
    land: Tuple[str, ...] = tuple(_jitter(c, rng) for c in base["land"])
    sea: Tuple[str, ...] = tuple(_jitter(c, rng, 0.05) for c in base["sea"])
    return {
        "type": kind, "label": base["label"], "about": base["about"],
        "radius": round(rng.uniform(1.0, 1.4), 3),
        "land": list(land), "sea": list(sea),
        "sea_level": round(base["sea_level"] + rng.uniform(-0.08, 0.08), 3),
        "mountains": round(base["mountains"] * rng.uniform(0.8, 1.25), 3),
        "ice": round(base["ice"] + rng.uniform(-0.04, 0.04), 3),
        "air": _jitter(base["air"], rng, 0.06), "clouds": round(max(0.0, base["clouds"] + rng.uniform(-0.1, 0.1)), 3),
        "greens": bool(base["greens"]), "lava": bool(base.get("lava")),
        "rings": rings, "ring_color": rng.choice(_RING_COLORS), "ring_tilt": round(rng.uniform(0.15, 0.6), 3),
        "moons": moons, "noise": rng.randrange(1, 2 ** 31), "day_hours": rng.choice((18, 20, 24, 26, 30, 36)),
        "tilt": round(rng.uniform(-0.4, 0.4), 3),
    }


def words(seed: int) -> str:
    """One line for the government's prompts, so the plans fit the planet."""
    planet = describe(seed)
    extra = []
    if planet["rings"]:
        extra.append("rings")
    if planet["moons"]:
        extra.append(f"{len(planet['moons'])} moon{'s' if len(planet['moons']) != 1 else ''}")
    return f"{planet['label']} — {planet['about']}" + (f" ({', '.join(extra)})" if extra else "")
