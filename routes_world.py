"""HTTP routes for the World tab — the AI Environment planet (UPDATE_IDEAS U34–U40).

Owner-only, every one of them: a world runs models on the owner's keys for hours or days, writes into their folders
and pauses the rest of Nyx, so an invited tester has no business here. Hosted builds do not have these routes at all
(``deploy_mode.HOSTED_BLOCKED_PREFIXES``).

The work lives in ``world/``; this file only validates what came in and calls one engine method.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


def _owner_dep():
    def dependency(http_request: Request, authorization: Optional[str] = Header(default=None)) -> Any:
        from server import require_local_owner

        return require_local_owner(http_request, authorization)
    return Depends(dependency)


Owner = _owner_dep()


def _engine() -> Any:
    from world.engine import ENGINE

    return ENGINE


def _fail(error: Exception) -> HTTPException:
    from office.engine import OfficeError
    from office.library import LibraryError
    from world.engine import WorldError
    from world.store import StoreError

    if isinstance(error, (WorldError, StoreError, OfficeError, LibraryError, ValueError)):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=500, detail=f"{type(error).__name__}: {error}")


def _call(fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except HTTPException:
        raise
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error


class NewWorld(BaseModel):
    name: str = ""
    goal: str = ""
    duration: str = ""
    speed: str = ""


class Upscale(NewWorld):
    office_id: str


class WorldChanges(BaseModel):
    name: Optional[str] = None
    goal: Optional[str] = None
    duration: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None


class ControlBody(BaseModel):
    action: str
    halt_office: bool = False


class TextBody(BaseModel):
    text: str = ""


class SpeedBody(BaseModel):
    speed: str


class LawBody(BaseModel):
    text: str
    scope: str = "world"
    sector: str = ""


class ActionBody(BaseModel):
    action: str


class DecideBody(BaseModel):
    choice: str
    text: str = ""


class MoodBody(BaseModel):
    agent_id: str


@router.get("/api/world")
def world_overview(_owner=Owner) -> Dict[str, Any]:
    return _call(_engine().overview)


@router.post("/api/world/worlds")
def world_create(body: NewWorld, _owner=Owner) -> Dict[str, Any]:
    return _call(_engine().create, name=body.name, goal=body.goal, duration=body.duration, speed=body.speed)


@router.post("/api/world/upscale")
def world_upscale(body: Upscale, _owner=Owner) -> Dict[str, Any]:
    """Office Space → Upscale: the office's team become the first citizens of a planet."""
    return _call(_engine().upscale, body.office_id, name=body.name, goal=body.goal, duration=body.duration,
                 speed=body.speed)


@router.get("/api/world/worlds/{world_id}")
def world_snapshot(world_id: str, _owner=Owner) -> Dict[str, Any]:
    return _call(_engine().snapshot, world_id)


@router.patch("/api/world/worlds/{world_id}")
def world_patch(world_id: str, body: WorldChanges, _owner=Owner) -> Dict[str, Any]:
    return _call(_engine().patch, world_id, name=body.name, goal=body.goal, duration=body.duration,
                 settings=body.settings)


@router.delete("/api/world/worlds/{world_id}")
def world_trash(world_id: str, _owner=Owner) -> Dict[str, Any]:
    """Moves the world file to ``worlds/.trash`` — never destroyed; its office stays in Office Space."""
    return _call(_engine().trash, world_id)


@router.post("/api/world/worlds/{world_id}/control")
def world_control(world_id: str, body: ControlBody, _owner=Owner) -> Dict[str, Any]:
    return _call(_engine().control, world_id, body.action, halt_office=body.halt_office)


@router.post("/api/world/worlds/{world_id}/say")
def world_say(world_id: str, body: TextBody, _owner=Owner) -> Dict[str, Any]:
    engine = _engine()
    result = _call(engine.say, world_id, body.text)
    return {**result, "snapshot": _call(engine.snapshot, world_id)}


@router.post("/api/world/worlds/{world_id}/speed")
def world_speed(world_id: str, body: SpeedBody, _owner=Owner) -> Dict[str, Any]:
    return _call(_engine().set_speed, world_id, body.speed)


@router.post("/api/world/worlds/{world_id}/laws")
def world_new_law(world_id: str, body: LawBody, _owner=Owner) -> Dict[str, Any]:
    return _call(_engine().propose_law, world_id, body.text, scope=body.scope, sector=body.sector)


@router.post("/api/world/worlds/{world_id}/laws/{law_id}")
def world_law(world_id: str, law_id: int, body: ActionBody, _owner=Owner) -> Dict[str, Any]:
    return _call(_engine().law_action, world_id, law_id, body.action)


@router.post("/api/world/worlds/{world_id}/wars/{war_id}/hearing")
def world_war_hearing(world_id: str, war_id: str, _owner=Owner) -> Dict[str, Any]:
    return _call(_engine().war_hearing, world_id, war_id)


@router.post("/api/world/worlds/{world_id}/wars/{war_id}/decide")
def world_war_decide(world_id: str, war_id: str, body: DecideBody, _owner=Owner) -> Dict[str, Any]:
    return _call(_engine().war_decide, world_id, war_id, choice=body.choice, text=body.text)


@router.post("/api/world/worlds/{world_id}/startups/{startup_id}")
def world_startup(world_id: str, startup_id: str, body: ActionBody, _owner=Owner) -> Dict[str, Any]:
    return _call(_engine().startup_action, world_id, startup_id, body.action)


@router.post("/api/world/worlds/{world_id}/mood")
def world_mood(world_id: str, body: MoodBody, _owner=Owner) -> Dict[str, Any]:
    """Asked live from the AI's own model and returned — never stored (U39)."""
    return _call(_engine().mood, world_id, body.agent_id)


@router.post("/api/world/worlds/{world_id}/graves/{grave_id}/rejoin")
def world_rejoin(world_id: str, grave_id: int, _owner=Owner) -> Dict[str, Any]:
    return _call(_engine().rejoin, world_id, grave_id)
