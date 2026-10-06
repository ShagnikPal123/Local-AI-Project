"""Swarm: many agents on one job at once, as many as this PC can carry (Update 1, U5).

The owner (2026-09-26): "swarm idea. In this it can make lots of agents, with a slider if the user has a
limit ... An example use for swarm is to upload things to projects, fix small code errors, and more."

The chat's Swarm mode (``chat_modes``) hands a message to a swarm: Nyx splits the job into independent parts,
runs them side by side through ``agent_dispatch`` — the same boxes the owner already knows from ``/coder [3]`` —
and merges the reports. This module only answers *how many*:

* **size** — the owner's slider, remembered between sessions.
* **ceiling** — what the hardware allows, so the slider never promises more than the PC can carry. An agent
  spends most of its time waiting on a model, so the ceiling is a few agents per safe worker, not one per core.
* **parallel** — how many work at the same moment: the Power setting's agent budget (``resource_governor``),
  never more than the size. The rest wait in their boxes and start as others finish, so a big swarm on a small
  machine is slower, not dangerous.

Every agent in a swarm is an ordinary specialist with the same tools, permission checks and approvals — a bigger
swarm is more hands, not more authority.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, Tuple

from paths import atomic_replace, data_path

#: However big the machine, one chat message never fans out wider than this.
HARD_MAX = 48
#: The smallest swarm worth the name; below it Co-work does the same job.
MIN_SIZE = 2
#: Agents per safe worker. Agents mostly wait on a model, so several share one worker's headroom.
AGENTS_PER_WORKER = 4

_LOCK = threading.Lock()


def _path():
    return data_path("swarm.json")


def _read() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def ceiling() -> Tuple[int, str]:
    """The most agents one swarm may hold on this machine, and the plain reason why."""
    try:
        from device_profile import get_device_profile

        profile = get_device_profile()
        workers = max(1, int(profile.max_workers))
        machine = f"{profile.ram_gb:.0f} GB RAM" + (f", {profile.vram_gb:.0f} GB graphics memory" if profile.vram_gb else "")
    except Exception:  # noqa: BLE001 - an unreadable machine is treated as a small one
        workers, machine = 1, "an unrecognised machine"
    size = max(MIN_SIZE * 2, min(HARD_MAX, workers * AGENTS_PER_WORKER))
    return size, f"Up to {size} agents on this PC ({machine})."


def settings() -> Dict[str, Any]:
    top, _ = ceiling()
    saved = _read().get("size")
    try:
        size = int(saved)
    except (TypeError, ValueError):
        size = min(8, top)
    return {"size": max(MIN_SIZE, min(size, top))}


def save(size: Any) -> Dict[str, Any]:
    """Remember the slider. Clamped to the machine's ceiling, so a saved 40 on a laptop reads back as its maximum."""
    try:
        wanted = int(size)
    except (TypeError, ValueError):
        raise ValueError("The swarm size is a whole number of agents.") from None
    top, _ = ceiling()
    with _LOCK:
        data = _read()
        data["size"] = max(MIN_SIZE, min(wanted, top))
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        atomic_replace(tmp, path)
    return describe()


def limit() -> int:
    """How many agents a Swarm turn may dispatch."""
    return settings()["size"]


def parallel(size: int = 0) -> int:
    """How many of them work at the same moment — the Power setting's budget, never more than the swarm."""
    size = int(size or limit())
    try:
        from resource_governor import GOVERNOR

        budget = int(GOVERNOR.ceiling(task_complexity="parallel").max_agents)
    except Exception:  # noqa: BLE001
        budget = 2
    return max(1, min(size, max(2, budget)))


def describe() -> Dict[str, Any]:
    """What the slider shows: the owner's choice, the machine's limit, and how many run at once."""
    top, reason = ceiling()
    size = settings()["size"]
    together = parallel(size)
    return {
        "size": size,
        "min": MIN_SIZE,
        "ceiling": top,
        "parallel": together,
        "reason": reason,
        "summary": (f"{size} agents, {together} at a time" if together < size else f"{size} agents, all at once"),
    }
