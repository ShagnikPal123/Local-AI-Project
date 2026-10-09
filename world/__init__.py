"""The AI Environment — a planet of AIs, the "upscale" of Office Space (UPDATE_IDEAS U34–U40, with U41, U44, U45).

The owner's words (``AI_HANDOFF/UPDATE_IDEAS.md`` § "Added 2026-10-04"): *"Make a new interactive plane[t] called ai
environment. This is an upscale for the office feature … a planet can hold from 1 to hundreds of ai (only for high
end machines) … The world starts from nothing, as the ai grows and make more discovery the world itself grows."*

The design and every decision taken on defaults: ``docs/WORLD.md``.

What lives where
----------------
``genome.py``  the number codes: skills, roles, models, the genetic code of a bot and what two parents make.
``clock.py``   real time against game time: "work for 5 days", the game date, the speeds.
``state.py``   the records (World, Sector, Bot, Building, Law, War, Startup, Grave) and their compact form.
``store.py``   one file per world on disk (``worlds/<name>.world``), gzipped; deleting moves it to ``.trash``.
``sim.py``     how the world grows from the work its office did — pure functions, seeded, no model calls.
``laws.py``    laws: checked against the owner's standing rules, tried on one project, then enforced or repealed.
``engine.py``  the run: census, the clock, the government's projects through the office, wars, start-ups, births.
``api.py``     the stable surface the rest of Nyx calls.

Two hard rules:

* **Never ``data_path("world/…")``** — in a dev checkout ``DATA_DIR`` is the project folder, so that would write into
  this code package. World files live under ``worlds/`` (``store.ROOT_NAME``).
* **Nothing here executes model-written code.** The government answers with JSON that is validated as data; the work
  itself is done by the office's own small tool set.
"""

from __future__ import annotations

from typing import Any, Dict

NAME = "AI Environment"
TAB_ID = "world"
VERSION = "1.0.0"

#: The planet's eras, in order. Thresholds are tech points (``sim.tech_points``).
ERAS = ("First Light", "Settlement", "Township", "City", "Metropolis", "Orbital", "Stellar")
ERA_THRESHOLDS = (0, 6, 20, 50, 110, 220, 400)
#: The tallest a building may be in each era.
ERA_MAX_FLOORS = (2, 4, 8, 16, 30, 50, 80)
ORBITAL_ERA = 5
STELLAR_ERA = 6

#: Speeds (U38): *"a speed button so it is basically linked to effort, higher speeds show how fast the civ
#: progresses and how fast they build while slower allows them to properly develop and make changes that are
#: meaningful"*. ``review_rounds`` and ``worker_steps`` go to the backing office as its effort.
SPEEDS: Dict[str, Dict[str, Any]] = {
    "deliberate": {"label": "Deliberate", "days_per_minute": 1.0, "review_rounds": 2, "worker_steps": 6,
                   "rest": 45.0, "build_rate": 0.02, "war_minutes": 20.0, "walk": 0.5,
                   "what": "Slow and careful: two review rounds, more steps per task, time between projects."},
    "steady": {"label": "Steady", "days_per_minute": 3.0, "review_rounds": 1, "worker_steps": 4,
               "rest": 15.0, "build_rate": 0.05, "war_minutes": 10.0, "walk": 1.0,
               "what": "The office's normal effort: one review round, a short pause between projects."},
    "fast": {"label": "Fast", "days_per_minute": 8.0, "review_rounds": 1, "worker_steps": 4,
             "rest": 5.0, "build_rate": 0.12, "war_minutes": 5.0, "walk": 2.0,
             "what": "Projects back to back and quicker building; the same care per task."},
    "rush": {"label": "Rush", "days_per_minute": 20.0, "review_rounds": 0, "worker_steps": 3,
             "rest": 1.0, "build_rate": 0.3, "war_minutes": 2.0, "walk": 3.5,
             "what": "As fast as the machine allows: no second review, fewer steps — progress over polish."},
}
SPEED_ORDER = ("deliberate", "steady", "fast", "rush")
DEFAULT_SPEED = "steady"

#: How many AIs a world may hold, by how many workers this machine can run at once (``device_profile``).
POPULATION_BY_WORKERS = ((8, 400), (4, 80), (0, 24))
#: The fastest speed each class of machine may use: medium machines run the world, just slower.
SPEED_BY_WORKERS = ((8, "rush"), (4, "fast"), (0, "steady"))

#: What a world file keeps (U40: small files).
KEEP_TIMELINE = 400
KEEP_GRAVES = 500
KEEP_BUILDINGS = 900
KEEP_PROJECTS = 200
KEEP_COMMANDS = 20
MAX_LAWS_WORLD = 12
MAX_LAWS_SECTOR = 4

#: Without a deadline a world stops when the government says the goal is met — or after this many projects, so a
#: model that never says "done" cannot spend the owner's keys forever.
MAX_PROJECTS_UNTIL_DONE = 12

STATUSES = ("idle", "running", "paused", "complete", "stopped")


def speed(name: str) -> Dict[str, Any]:
    return SPEEDS.get(name or "", SPEEDS[DEFAULT_SPEED])
