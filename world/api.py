"""The small, stable surface the rest of Nyx calls (voice, chat, the processes view).

Nothing here raises: a caller that is only *trying* to reach a world gets an answer it can read out.
"""

from __future__ import annotations

from typing import Any, Dict, List

from world import store
from world.engine import ENGINE


def running() -> str:
    """The world running right now, or ""."""
    try:
        return ENGINE.running_world()
    except Exception:  # noqa: BLE001
        return ""


def worlds() -> List[Dict[str, Any]]:
    try:
        return store.worlds()
    except Exception:  # noqa: BLE001
        return []


def say(text: str, *, world_id: str = "") -> Dict[str, Any]:
    """Tell a world something: the running one by default, else the newest."""
    target = world_id or running() or (worlds()[0]["id"] if worlds() else "")
    if not target:
        return {"ok": False, "note": "There is no world yet — make one in the World tab."}
    try:
        return {"ok": True, "world_id": target, **ENGINE.say(target, text)}
    except Exception as error:  # noqa: BLE001 - callers read this out loud; never throw at them
        return {"ok": False, "world_id": target, "note": str(error)[:300]}


def summary() -> Dict[str, Any]:
    world_id = running()
    if not world_id:
        rows = worlds()
        return {"running": False, "worlds": len(rows),
                "note": f"{len(rows)} world(s); none running right now." if rows else "No worlds yet."}
    try:
        data = ENGINE.snapshot(world_id)["world"]
        return {"running": True, "world_id": world_id, "name": data["name"], "era": data["era_name"],
                "population": data["population"],
                "note": (f"{data['name']}: {data['era_name']} era, {data['game_date']}, "
                         f"{data['population']['ais']} AIs ({data['population']['awake']} awake), "
                         f"{data['projects_done']} projects delivered.")}
    except Exception as error:  # noqa: BLE001
        return {"running": True, "world_id": world_id, "note": str(error)[:200]}


__all__ = ["running", "worlds", "say", "summary"]
