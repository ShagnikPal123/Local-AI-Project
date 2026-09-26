"""HTTP routes for the Game Studio tab (Request H5).

Designing and playing a game is an ordinary signed-in action. Writing a Unity
project onto this PC is not: that needs the owner, on this machine, like the
Code tab.
"""

from __future__ import annotations

import functools
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from server_auth import RequireChat

router = APIRouter()


class NewGameRequest(BaseModel):
    title: str
    kind: str = "2d"
    template: str = "metroidvania"
    blank: bool = False
    brief: str = ""


class PatchRequest(BaseModel):
    changes: Dict[str, Any] = {}


class BriefRequest(BaseModel):
    brief: str = ""


class ExportRequest(BaseModel):
    folder: str


def _errors(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        import game_studio
        from model_hub import ModelCallError

        try:
            return fn(*args, **kwargs)
        except game_studio.GameError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except ModelCallError as error:
            raise HTTPException(status_code=502, detail=f"No model could answer: {error}") from error
    return wrapper


def _owner_dep():
    def dependency(http_request: Request, authorization: Optional[str] = Header(default=None)) -> Any:
        from server import require_local_owner

        return require_local_owner(http_request, authorization)
    return Depends(dependency)


Owner = _owner_dep()


@router.get("/api/games")
def list_games(_user=RequireChat) -> Dict[str, Any]:
    import game_studio

    return {"games": game_studio.games(), "templates": list(game_studio.TEMPLATES)}


@router.post("/api/games")
@_errors
def create_game(body: NewGameRequest, _user=RequireChat) -> Dict[str, Any]:
    import game_studio

    if body.brief.strip():
        return {"game": game_studio.create_designed(body.title, body.brief, body.kind, body.template)}
    return {"game": game_studio.create(body.title, body.kind, body.template, blank=body.blank)}


@router.get("/api/games/{game_id}")
def read_game(game_id: str, _user=RequireChat) -> Dict[str, Any]:
    import game_studio

    game = game_studio.get(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="That game is not here any more.")
    return {"game": game}


@router.patch("/api/games/{game_id}")
@_errors
def patch_game(game_id: str, body: PatchRequest, _user=RequireChat) -> Dict[str, Any]:
    import game_studio

    return {"game": game_studio.update(game_id, body.changes)}


@router.delete("/api/games/{game_id}")
@_errors
def delete_game(game_id: str, _user=RequireChat) -> Dict[str, Any]:
    import game_studio

    game_studio.remove(game_id)
    return {"removed": game_id}


@router.post("/api/games/{game_id}/design")
@_errors
def design_game(game_id: str, body: BriefRequest, _user=RequireChat) -> Dict[str, Any]:
    import game_studio

    return {"game": game_studio.design(game_id, body.brief)}


@router.post("/api/games/{game_id}/rooms")
@_errors
def add_room(game_id: str, body: BriefRequest, _user=RequireChat) -> Dict[str, Any]:
    import game_studio

    return {"game": game_studio.add_room(game_id, body.brief)}


@router.get("/api/games/{game_id}/unity")
@_errors
def unity_preview(game_id: str, _user=RequireChat) -> Dict[str, Any]:
    import game_studio

    files = game_studio.unity_files(game_id)
    return {"files": [{"path": item["path"], "bytes": len(item["text"])} for item in files]}


@router.post("/api/games/{game_id}/unity")
@_errors
def export_unity(game_id: str, body: ExportRequest, _owner=Owner) -> Dict[str, Any]:
    import game_studio

    return game_studio.export_to_folder(game_id, body.folder)


# --- chat tools: "make me a game like Hollow Knight" works from the chat too ----


def tool_game_create(title: str, kind: str = "2d", brief: str = "") -> str:
    import game_studio

    try:
        if brief.strip():
            game = game_studio.create_designed(title, brief, kind or "2d")
        else:
            game = game_studio.create(title, kind or "2d", "metroidvania")
    except game_studio.GameError as error:
        return f"Error: {error}"
    rooms = ", ".join(room["name"] for room in game["rooms"]) or "no rooms"
    return (f"Made the {game['kind'].upper()} game “{game['title']}” (id {game['id']}): {len(game['rooms'])} rooms "
            f"({rooms}), {len(game['enemies'])} enemy types, abilities: "
            f"{', '.join(a['name'] for a in game['abilities']) or 'none'}. "
            "It is playable now in the Game Studio tab, and exports to Unity from there.")


def tool_game_list() -> str:
    import game_studio

    found = game_studio.games()
    if not found:
        return "No games in the Game Studio yet."
    return "\n".join(f"- {g['title']} (id {g['id']}, {g['kind']}, {g['counts']['rooms']} rooms)" for g in found)


def tool_game_add_room(game_id: str, brief: str = "") -> str:
    import game_studio

    try:
        game = game_studio.add_room(game_id, brief)
    except game_studio.GameError as error:
        return f"Error: {error}"
    return f"Added “{game['rooms'][-1]['name']}” to {game['title']} — {len(game['rooms'])} rooms now."


def register_game_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        "game_create",
        "Make a playable game in the Game Studio tab (2D or 3D, metroidvania-style rooms, enemies, abilities). "
        "Give a brief to have it designed from the owner's description; it exports to Unity from the tab.",
        [ToolParam("title", "string", "The game's name"),
         ToolParam("kind", "string", "2d or 3d", required=False, enum_values=["2d", "3d"]),
         ToolParam("brief", "string", "What the game should be like", required=False)],
        tool_game_create, category="general", label=lambda a: f"Making the game {str(a.get('title', ''))[:40]}")
    registry.register("game_list", "List the games in the Game Studio tab.", [], tool_game_list,
                      category="general", label=lambda a: "Listing games")
    registry.register(
        "game_add_room", "Add one designed room to a Game Studio game, connected to its last room.",
        [ToolParam("game_id", "string", "Game id from game_list"),
         ToolParam("brief", "string", "What the room should be like", required=False)],
        tool_game_add_room, category="general", label=lambda a: "Adding a room")
