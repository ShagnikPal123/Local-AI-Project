"""Game studio — the Game Studio tab (Request H5).

The owner's words: "Also to build off this make a game studio tab to make games
in 3d and 2d. Similar to making hollow knight and more it can import to unity."

**A game is a validated data spec, never code** (AGENTS.md invariant 2). The
model designs rooms, enemies, abilities and numbers; this module refuses
anything outside the grammar below; the tab's engine *interprets* the spec to
play it. The Unity export is fixed C# written here — the model's output only
ever becomes the JSON level file those scripts read. Nothing is compiled, and
Nyx never runs a game engine.

The grammar:

    {id, title, kind: "2d"|"3d", template, story: {opening, goal},
     world:   {gravity, tile, air_control, terminal_velocity},
     player:  {name, speed, jump, max_jumps, dash, wall_jump, health, attack, colour},
     palette: {bg, ground, platform, hazard, accent, player, enemy},
     abilities: [{id, name, gives, note}],
     enemies:   [{id, name, behaviour, speed, health, damage, colour, size}],
     rooms:     [{id, name, tiles: ["#....#", ...], spawns: [{enemy, x, y}],
                  items: [{kind, ability, x, y}], doors: [{to, x, y, spawn_x, spawn_y}]}]}

Tile characters (anything else becomes empty space):

    "."  air          "#"  solid ground      "="  one-way platform
    "^"  hazard       "P"  player start      "D"  door (paired with rooms[].doors)
    "S"  save point   "A"  ability pickup    "E"  enemy spawn marker
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from paths import atomic_replace, data_path

_LOCK = threading.Lock()

MAX_GAMES = 30
MAX_ROOMS = 24
MAX_ROOM_W = 80
MAX_ROOM_H = 48
MAX_ENEMIES = 12
MAX_ABILITIES = 10
MAX_SPAWNS = 40

KINDS = ("2d", "3d")
TEMPLATES = ("metroidvania", "platformer", "topdown", "runner", "puzzle", "arena")
BEHAVIOURS = ("patrol", "chaser", "flyer", "turret", "jumper")
ITEM_KINDS = ("ability", "health", "coin", "key")
TILES = set(".#=^PDSAE")

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")


class GameError(ValueError):
    """A request the studio refuses, with a sentence the UI can show."""


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def _text(value: Any, limit: int = 400) -> str:
    if value is None:
        return ""
    return _CONTROL_RE.sub("", str(value)).strip()[:limit]


def _num(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return round(min(high, max(low, number)), 3)


def _int(value: Any, low: int, high: int, default: int) -> int:
    return int(_num(value, low, high, default))


def _pick(value: Any, allowed: Sequence[str], default: str) -> str:
    candidate = _text(value, 40).lower()
    for option in allowed:
        if candidate == option.lower():
            return option
    return default


def _colour(value: Any, default: str) -> str:
    candidate = _text(value, 7)
    return candidate if _HEX_RE.match(candidate) else default


def _slug(value: Any, fallback: str) -> str:
    candidate = re.sub(r"[^a-z0-9_-]+", "-", _text(value, 40).lower()).strip("-")
    return candidate if _ID_RE.match(candidate or "") else fallback


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


def _clean_tiles(value: Any) -> List[str]:
    """Rows of known characters, rectangular, bounded. Unknown characters become air."""
    rows = value if isinstance(value, (list, tuple)) else str(value or "").splitlines()
    cleaned: List[str] = []
    for row in list(rows)[:MAX_ROOM_H]:
        # Models sometimes write a row as a list of characters: ["#", ".", "#"].
        line = "".join(str(cell)[:1] for cell in row) if isinstance(row, (list, tuple)) else str(row)
        text = "".join(character if character in TILES else "." for character in line)[:MAX_ROOM_W]
        cleaned.append(text)
    if not cleaned:
        return []
    width = max(len(row) for row in cleaned)
    return [row.ljust(width, ".") for row in cleaned]


def _clean_ability(raw: Any, index: int) -> Optional[Dict[str, Any]]:
    if isinstance(raw, str):
        raw = {"name": raw}
    if not isinstance(raw, dict):
        return None
    name = _text(raw.get("name"), 40)
    if not name:
        return None
    return {
        "id": _slug(raw.get("id") or name, f"ability{index + 1}"),
        "name": name,
        #: What the ability actually changes in the engine. Anything else is flavour only.
        "gives": _pick(raw.get("gives"), ("double_jump", "dash", "wall_jump", "attack", "speed", "none"), "none"),
        "note": _text(raw.get("note") or raw.get("description"), 200),
    }


def _clean_enemy(raw: Any, index: int) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    name = _text(raw.get("name"), 40)
    if not name:
        return None
    return {
        "id": _slug(raw.get("id") or name, f"enemy{index + 1}"),
        "name": name,
        "behaviour": _pick(raw.get("behaviour") or raw.get("kind"), BEHAVIOURS, "patrol"),
        "speed": _num(raw.get("speed"), 0, 20, 3),
        "health": _int(raw.get("health"), 1, 200, 3),
        "damage": _int(raw.get("damage"), 0, 50, 1),
        "colour": _colour(raw.get("colour") or raw.get("color"), "#ff6b6b"),
        "size": _num(raw.get("size"), 0.4, 4, 1),
        "note": _text(raw.get("note"), 200),
    }


def _clean_room(raw: Any, index: int, enemy_ids: Sequence[str], ability_ids: Sequence[str]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    tiles = _clean_tiles(raw.get("tiles") or raw.get("map") or raw.get("layout") or raw.get("grid"))
    if not tiles or not any(set(row) - {"."} for row in tiles):
        return None
    height = len(tiles)
    width = len(tiles[0])
    spawns = []
    for item in (raw.get("spawns") or [])[:MAX_SPAWNS]:
        if not isinstance(item, dict):
            continue
        enemy = _slug(item.get("enemy") or item.get("id"), "")
        if enemy not in enemy_ids:
            continue
        spawns.append({"enemy": enemy, "x": _int(item.get("x"), 0, width - 1, 1),
                       "y": _int(item.get("y"), 0, height - 1, 1)})
    items = []
    for item in (raw.get("items") or [])[:MAX_SPAWNS]:
        if not isinstance(item, dict):
            continue
        kind = _pick(item.get("kind"), ITEM_KINDS, "coin")
        ability = _slug(item.get("ability"), "")
        if kind == "ability" and ability not in ability_ids:
            continue
        items.append({"kind": kind, "ability": ability, "x": _int(item.get("x"), 0, width - 1, 1),
                      "y": _int(item.get("y"), 0, height - 1, 1),
                      "needs": _slug(item.get("needs"), "") if _slug(item.get("needs"), "") in ability_ids else ""})
    doors = []
    for item in (raw.get("doors") or [])[:12]:
        if not isinstance(item, dict):
            continue
        doors.append({"to": _slug(item.get("to"), ""), "x": _int(item.get("x"), 0, width - 1, 0),
                      "y": _int(item.get("y"), 0, height - 1, 0),
                      "spawn_x": _int(item.get("spawn_x"), 0, MAX_ROOM_W, 1),
                      "spawn_y": _int(item.get("spawn_y"), 0, MAX_ROOM_H, 1),
                      "needs": _slug(item.get("needs"), "")})
    return {
        "id": _slug(raw.get("id") or raw.get("name"), f"room{index + 1}"),
        "name": _text(raw.get("name"), 60) or f"Room {index + 1}",
        "tiles": tiles, "width": width, "height": height,
        "spawns": spawns, "items": items, "doors": doors,
        "note": _text(raw.get("note"), 300),
    }


def _ensure_start(room: Dict[str, Any]) -> None:
    """The first room needs somewhere to stand: an open tile with ground under it."""
    if any("P" in row for row in room["tiles"]):
        return
    tiles = room["tiles"]
    for need_headroom in (True, False):  # somewhere you can jump from, else anywhere you can stand
        for y in range(len(tiles) - 2, -1, -1):
            for x in range(1, len(tiles[y]) - 1):
                headroom = y == 0 or tiles[y - 1][x] == "."
                if tiles[y][x] == "." and tiles[y + 1][x] in "#=" and (headroom or not need_headroom):
                    tiles[y] = tiles[y][:x] + "P" + tiles[y][x + 1:]
                    return


def validate_game(raw: Any, *, base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Turn anything into a game we are willing to run in the tab."""
    if not isinstance(raw, dict):
        raise GameError("A game has to be an object.")
    base = base or {}
    title = _text(raw.get("title") or base.get("title"), 80)
    if not title:
        raise GameError("Give the game a name first.")

    abilities: List[Dict[str, Any]] = []
    for index, item in enumerate((raw.get("abilities") or [])[:MAX_ABILITIES]):
        cleaned = _clean_ability(item, index)
        if cleaned and all(cleaned["id"] != existing["id"] for existing in abilities):
            abilities.append(cleaned)
    enemies: List[Dict[str, Any]] = []
    for index, item in enumerate((raw.get("enemies") or [])[:MAX_ENEMIES]):
        cleaned = _clean_enemy(item, index)
        if cleaned and all(cleaned["id"] != existing["id"] for existing in enemies):
            enemies.append(cleaned)
    enemy_ids = [enemy["id"] for enemy in enemies]
    ability_ids = [ability["id"] for ability in abilities]
    rooms: List[Dict[str, Any]] = []
    for index, item in enumerate((raw.get("rooms") or raw.get("levels") or raw.get("areas") or [])[:MAX_ROOMS]):
        cleaned = _clean_room(item, index, enemy_ids, ability_ids)
        if cleaned and all(cleaned["id"] != existing["id"] for existing in rooms):
            rooms.append(cleaned)
    if rooms:
        _ensure_start(rooms[0])
    room_ids = {room["id"] for room in rooms}
    for room in rooms:
        room["doors"] = [door for door in room["doors"] if door["to"] in room_ids and door["to"] != room["id"]]

    player = raw.get("player") if isinstance(raw.get("player"), dict) else {}
    world = raw.get("world") if isinstance(raw.get("world"), dict) else {}
    palette = raw.get("palette") if isinstance(raw.get("palette"), dict) else {}
    story = raw.get("story") if isinstance(raw.get("story"), dict) else {}

    game = {
        "id": _slug(raw.get("id") or base.get("id") or "", "") or _new_id(),
        "title": title,
        "kind": _pick(raw.get("kind"), KINDS, base.get("kind") or "2d"),
        "template": _pick(raw.get("template"), TEMPLATES, base.get("template") or "metroidvania"),
        "created_at": float(base.get("created_at") or raw.get("created_at") or time.time()),
        "updated_at": time.time(),
        "story": {"opening": _text(story.get("opening"), 800), "goal": _text(story.get("goal"), 400)},
        "world": {
            "gravity": _num(world.get("gravity"), 0, 200, 46),
            "tile": _int(world.get("tile"), 8, 64, 24),
            "air_control": _num(world.get("air_control"), 0, 1, 0.75),
            "terminal_velocity": _num(world.get("terminal_velocity"), 5, 120, 34),
        },
        "player": {
            "name": _text(player.get("name"), 40) or "You",
            "speed": _num(player.get("speed"), 1, 30, 9),
            "jump": _num(player.get("jump"), 4, 40, 17),
            "max_jumps": _int(player.get("max_jumps"), 1, 3, 1),
            "dash": bool(player.get("dash")),
            "wall_jump": bool(player.get("wall_jump")),
            "attack": bool(player.get("attack", True)),
            "health": _int(player.get("health"), 1, 20, 5),
            "colour": _colour(player.get("colour") or player.get("color"), "#a594ff"),
        },
        "palette": {
            "bg": _colour(palette.get("bg"), "#0b0b14"),
            "ground": _colour(palette.get("ground"), "#2b2b3a"),
            "platform": _colour(palette.get("platform"), "#41415a"),
            "hazard": _colour(palette.get("hazard"), "#ff453a"),
            "accent": _colour(palette.get("accent"), "#64d2ff"),
        },
        "abilities": abilities,
        "enemies": enemies,
        "rooms": rooms,
        "notes": _text(raw.get("notes"), 4000),
    }
    return game


def starter(title: str, kind: str = "2d", template: str = "metroidvania") -> Dict[str, Any]:
    """A small playable game, so a new project is never an empty screen."""
    floor = "#" * 40
    room_a = [
        "#" + "." * 38 + "#",
        "#" + "." * 38 + "#",
        "#" + "." * 38 + "#",
        "#....P..........................D......#",
        "#" + "." * 10 + "==========" + "." * 18 + "#",
        "#" + "." * 38 + "#",
        "#" + "." * 16 + "A" + "." * 21 + "#",
        "#" + "." * 12 + "======" + "." * 20 + "#",
        "#" + "." * 38 + "#",
        "#...........^^^........................#",
        floor,
    ]
    room_b = [
        "#" + "." * 38 + "#",
        "#" + "." * 38 + "#",
        "#D............................." + "." * 8 + "#",
        "#" + "." * 6 + "=====" + "." * 27 + "#",
        "#" + "." * 38 + "#",
        "#" + "." * 20 + "=====" + "." * 13 + "#",
        "#" + "." * 38 + "#",
        "#...........^^^^^......................#",
        floor,
    ]
    return validate_game({
        "title": title, "kind": kind, "template": template,
        "story": {"opening": "You wake up somewhere below the surface, with no idea how far down it goes.",
                  "goal": "Find a way back up."},
        "player": {"name": "Wanderer", "dash": True, "wall_jump": True, "health": 5},
        "abilities": [{"id": "dash", "name": "Dash", "gives": "dash", "note": "A short burst forward."},
                      {"id": "wings", "name": "Second wind", "gives": "double_jump", "note": "One more jump in the air."}],
        "enemies": [{"id": "crawler", "name": "Crawler", "behaviour": "patrol", "speed": 2.5, "health": 2, "damage": 1},
                    {"id": "flit", "name": "Flit", "behaviour": "flyer", "speed": 3.5, "health": 1, "damage": 1,
                     "colour": "#ffd60a"}],
        "rooms": [
            {"id": "start", "name": "The landing", "tiles": room_a,
             "spawns": [{"enemy": "crawler", "x": 24, "y": 9}],
             "items": [{"kind": "ability", "ability": "dash", "x": 17, "y": 6}],
             "doors": [{"to": "deep", "x": 32, "y": 3, "spawn_x": 3, "spawn_y": 2}]},
            {"id": "deep", "name": "Deeper still", "tiles": room_b,
             "spawns": [{"enemy": "flit", "x": 20, "y": 4}, {"enemy": "crawler", "x": 30, "y": 7}],
             "items": [{"kind": "ability", "ability": "wings", "x": 22, "y": 4}],
             "doors": [{"to": "start", "x": 1, "y": 2, "spawn_x": 31, "spawn_y": 3}]},
        ],
    })


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def _path() -> Path:
    return data_path("games/games.json")


def _read() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("games"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"games": []}


def _write(data: Dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    atomic_replace(temp, path)


def _summary(game: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": game["id"], "title": game["title"], "kind": game["kind"], "template": game["template"],
            "updated_at": game["updated_at"],
            "counts": {"rooms": len(game.get("rooms", [])), "enemies": len(game.get("enemies", [])),
                       "abilities": len(game.get("abilities", []))}}


def games() -> List[Dict[str, Any]]:
    with _LOCK:
        data = _read()
    return [_summary(game) for game in sorted(data["games"], key=lambda g: -float(g.get("updated_at", 0)))]


def get(game_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        data = _read()
    return next((game for game in data["games"] if game.get("id") == game_id), None)


def _require(game_id: str) -> Dict[str, Any]:
    game = get(game_id)
    if game is None:
        raise GameError("That game is not here any more.")
    return game


def _store(game: Dict[str, Any]) -> Dict[str, Any]:
    with _LOCK:
        data = _read()
        rest = [item for item in data["games"] if item.get("id") != game["id"]]
        rest.append(game)
        rest.sort(key=lambda g: -float(g.get("updated_at", 0)))
        data["games"] = rest[:MAX_GAMES]
        _write(data)
    return game


def create(title: str, kind: str = "2d", template: str = "metroidvania", *, blank: bool = False) -> Dict[str, Any]:
    game = validate_game({"title": title, "kind": kind, "template": template}) if blank \
        else starter(title, kind, template)
    return _store(game)


def create_designed(title: str, brief: str, kind: str = "2d", template: str = "metroidvania") -> Dict[str, Any]:
    """Create a game and have a model design it; if the design fails, nothing is left behind."""
    game = create(title, kind, template)
    try:
        return design(game["id"], brief)
    except Exception:
        remove(game["id"])
        raise


def update(game_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    game = _require(game_id)
    merged = {**game, **(changes if isinstance(changes, dict) else {})}
    merged["id"] = game["id"]
    return _store(validate_game(merged, base=game))


def remove(game_id: str) -> None:
    with _LOCK:
        data = _read()
        kept = [game for game in data["games"] if game.get("id") != game_id]
        if len(kept) == len(data["games"]):
            raise GameError("That game is not here any more.")
        data["games"] = kept
        _write(data)


# ---------------------------------------------------------------------------
# Designing with a model
# ---------------------------------------------------------------------------

_DESIGN_SYSTEM = (
    "You design small games as pure data. Answer with JSON only — no prose, no code fences, no code of any kind. "
    'Shape: {"title":"...","kind":"2d","template":"metroidvania",'
    '"story":{"opening":"...","goal":"..."},'
    '"player":{"name":"...","speed":9,"jump":17,"max_jumps":1,"dash":true,"wall_jump":true,"health":5,"colour":"#a594ff"},'
    '"palette":{"bg":"#0b0b14","ground":"#2b2b3a","platform":"#41415a","hazard":"#ff453a","accent":"#64d2ff"},'
    '"abilities":[{"id":"dash","name":"Dash","gives":"dash","note":"..."}],'
    '"enemies":[{"id":"crawler","name":"Crawler","behaviour":"patrol","speed":2.5,"health":2,"damage":1,"colour":"#ff6b6b"}],'
    '"rooms":[{"id":"start","name":"...","tiles":["#....#","#.P..#","######"],'
    '"spawns":[{"enemy":"crawler","x":4,"y":2}],"items":[{"kind":"ability","ability":"dash","x":6,"y":3}],'
    '"doors":[{"to":"deep","x":9,"y":2,"spawn_x":2,"spawn_y":2}]}]}. '
    "Tiles: '.' air, '#' solid, '=' one-way platform, '^' hazard, 'P' the player start, 'D' a door, 'A' a pickup. "
    "Every row of a room is the same length. Rooms are at most 60 wide and 34 tall, and every room must be "
    "playable: reachable platforms, a floor, and a way back to the door you came in by. "
    "gives must be one of double_jump, dash, wall_jump, attack, speed, none. "
    "behaviour must be one of patrol, chaser, flyer, turret, jumper. "
    "Make 2 to 4 rooms that connect both ways, and make the level readable — open space to move, not a maze of noise."
)


def _ask(prompt: str, *, max_tokens: int, timeout: float) -> Dict[str, Any]:
    """A model's JSON for the design grammar; a model failure becomes a GameError sentence."""
    import spec_ai

    try:
        return spec_ai.ask_json(_DESIGN_SYSTEM, prompt, max_tokens=max_tokens, timeout=timeout)
    except spec_ai.SpecAIError as error:
        raise GameError(str(error)) from error


def _unwrap(raw: Dict[str, Any]) -> Dict[str, Any]:
    """{"game": {...}} and {"spec": {...}} are the same game one level down."""
    for key in ("game", "spec", "design"):
        inner = raw.get(key)
        if isinstance(inner, dict) and not raw.get("rooms"):
            return inner
    return raw


def design(game_id: str, brief: str) -> Dict[str, Any]:
    """Ask a model to design the game from a sentence, then validate it hard."""
    game = _require(game_id)
    prompt = "\n".join([
        f"The game: {game['title']}",
        f"Kind: {game['kind']} ({game['template']})",
        f"What the owner wants: {brief.strip()[:1500] or game['title']}",
        "Keep the numbers in the ranges the system message shows. Return the whole game, not a patch.",
    ])
    started = time.monotonic()
    designed = None
    for attempt in range(2):
        raw = _unwrap(_ask(prompt, max_tokens=4000, timeout=max(30.0, 150 - (time.monotonic() - started))))
        merged = {**raw, "id": game["id"], "title": _text(raw.get("title"), 80) or game["title"],
                  "kind": game["kind"], "template": _pick(raw.get("template"), TEMPLATES, game["template"])}
        designed = validate_game(merged, base=game)
        if designed["rooms"] or attempt == 1 or time.monotonic() - started > 110:
            break
        # Say exactly what was wrong; the second answer is usually right.
        prompt += ("\n\nYour last answer had no usable room. Every room needs \"tiles\": a JSON list of strings, "
                   "each string one row of the same length, using only . # = ^ P D A — for example "
                   '["##########", "#P.......#", "#...==...#", "##########"]. Send the whole game again.')
    if not designed or not designed["rooms"]:
        raise GameError("The model did not come back with a playable room. Try again.")
    return _store(designed)


def add_room(game_id: str, brief: str = "") -> Dict[str, Any]:
    """One more room, connected to the last one."""
    game = _require(game_id)
    if len(game["rooms"]) >= MAX_ROOMS:
        raise GameError("This game already has as many rooms as the studio holds.")
    last = game["rooms"][-1] if game["rooms"] else None
    prompt = "\n".join([
        f"The game: {game['title']} ({game['template']})",
        f"Rooms so far: {', '.join(room['name'] for room in game['rooms']) or 'none'}",
        f"The room it connects back to: {last['id'] if last else 'none'}",
        f"Abilities the player can have: {', '.join(a['id'] for a in game['abilities']) or 'none'}",
        f"Enemies available: {', '.join(e['id'] for e in game['enemies']) or 'none'}",
        f"What this new room should be: {brief.strip()[:600] or 'the next room, a little harder'}",
        'Answer with JSON only: {"rooms":[{...one room...}]} using the same grammar. '
        f'Give it a door back to "{last["id"] if last else ""}".',
    ])
    raw = _unwrap(_ask(prompt, max_tokens=2200, timeout=120))
    fresh = (raw.get("rooms") or raw.get("levels") or ([raw["room"]] if isinstance(raw.get("room"), dict) else []))[:1]
    if not fresh:
        raise GameError("The model did not send a room back. Try again.")
    merged = {**game, "rooms": game["rooms"] + fresh}
    grown = validate_game(merged, base=game)
    if len(grown["rooms"]) <= len(game["rooms"]):
        raise GameError("The room that came back was not playable, so it was dropped.")
    # Let the player get back: give the previous room a door into the new one.
    if last is not None:
        new_room = grown["rooms"][-1]
        previous = next(room for room in grown["rooms"] if room["id"] == last["id"])
        if all(door["to"] != new_room["id"] for door in previous["doors"]):
            previous["doors"].append({"to": new_room["id"], "x": max(1, previous["width"] - 2),
                                      "y": max(1, previous["height"] - 3), "spawn_x": 2, "spawn_y": 2, "needs": ""})
    return _store(validate_game(grown, base=game))


# ---------------------------------------------------------------------------
# Unity export — fixed C# written here, spec data written as JSON beside it
# ---------------------------------------------------------------------------

_SPEC_CS = '''// Data classes for a Nyx game spec. Generated by Nyx; the level itself is
// NyxLevel.json next to this file. Unity's JsonUtility fills these in.
using System;
using System.Collections.Generic;
using UnityEngine;

namespace NyxGame {
  [Serializable] public class World { public float gravity; public int tile; public float air_control; public float terminal_velocity; }
  [Serializable] public class Player { public string name; public float speed; public float jump; public int max_jumps; public bool dash; public bool wall_jump; public bool attack; public int health; public string colour; }
  [Serializable] public class Palette { public string bg; public string ground; public string platform; public string hazard; public string accent; }
  [Serializable] public class Ability { public string id; public string name; public string gives; public string note; }
  [Serializable] public class Enemy { public string id; public string name; public string behaviour; public float speed; public int health; public int damage; public string colour; public float size; }
  [Serializable] public class Spawn { public string enemy; public int x; public int y; }
  [Serializable] public class Item { public string kind; public string ability; public int x; public int y; public string needs; }
  [Serializable] public class Door { public string to; public int x; public int y; public int spawn_x; public int spawn_y; public string needs; }
  [Serializable] public class Room {
    public string id; public string name; public string[] tiles; public int width; public int height;
    public List<Spawn> spawns; public List<Item> items; public List<Door> doors;
  }
  [Serializable] public class GameSpec {
    public string id; public string title; public string kind; public string template;
    public World world; public Player player; public Palette palette;
    public List<Ability> abilities; public List<Enemy> enemies; public List<Room> rooms;

    public static GameSpec Load(TextAsset json) { return JsonUtility.FromJson<GameSpec>(json.text); }
    public Room RoomById(string id) { return rooms.Find(r => r.id == id); }
    public static Color Ink(string hex, Color fallback) {
      Color parsed; return ColorUtility.TryParseHtmlString(hex, out parsed) ? parsed : fallback;
    }
  }
}
'''

_BUILDER_CS = '''// Builds a room from the spec's tile rows: one collider per solid tile, a
// trigger per hazard, door and pickup. Nothing here is generated per game —
// the game is the JSON this reads.
using UnityEngine;

namespace NyxGame {
  public class LevelBuilder : MonoBehaviour {
    public TextAsset levelJson;
    public GameObject playerPrefab;
    public GameObject enemyPrefab;
    [HideInInspector] public GameSpec spec;
    Transform built;

    void Awake() {
      spec = GameSpec.Load(levelJson);
      Camera.main.backgroundColor = GameSpec.Ink(spec.palette.bg, Color.black);
      Build(spec.rooms[0].id, -1, -1);
    }

    public void Build(string roomId, int spawnX, int spawnY) {
      if (built != null) Destroy(built.gameObject);
      built = new GameObject("Room " + roomId).transform;
      built.SetParent(transform, false);
      Room room = spec.RoomById(roomId);
      if (room == null) return;

      for (int y = 0; y < room.tiles.Length; y++) {
        string line = room.tiles[y];
        for (int x = 0; x < line.Length; x++) {
          char tile = line[x];
          Vector2 at = new Vector2(x, room.tiles.Length - y);
          if (tile == '#') Block(at, spec.palette.ground, false);
          else if (tile == '=') Block(at, spec.palette.platform, true);
          else if (tile == '^') Hazard(at);
          else if (tile == 'P' && spawnX < 0) SpawnPlayer(at);
        }
      }
      if (spawnX >= 0) SpawnPlayer(new Vector2(spawnX, room.tiles.Length - spawnY));
      foreach (Spawn spawn in room.spawns) {
        Enemy kind = spec.enemies.Find(e => e.id == spawn.enemy);
        if (kind == null) continue;
        GameObject made = Instantiate(enemyPrefab, new Vector2(spawn.x, room.tiles.Length - spawn.y), Quaternion.identity, built);
        made.GetComponent<EnemyController>().Setup(kind);
      }
    }

    void Block(Vector2 at, string colour, bool oneWay) {
      GameObject cube = GameObject.CreatePrimitive(PrimitiveType.Quad);
      cube.transform.SetParent(built, false);
      cube.transform.position = at;
      cube.GetComponent<Renderer>().material.color = GameSpec.Ink(colour, Color.grey);
      BoxCollider2D box = cube.AddComponent<BoxCollider2D>();
      if (oneWay) {
        PlatformEffector2D effector = cube.AddComponent<PlatformEffector2D>();
        box.usedByEffector = true;
        effector.useOneWay = true;
      }
    }

    void Hazard(Vector2 at) {
      GameObject spike = GameObject.CreatePrimitive(PrimitiveType.Quad);
      spike.transform.SetParent(built, false);
      spike.transform.position = at;
      spike.transform.localScale = new Vector3(1f, 0.5f, 1f);
      spike.GetComponent<Renderer>().material.color = GameSpec.Ink(spec.palette.hazard, Color.red);
      BoxCollider2D box = spike.AddComponent<BoxCollider2D>();
      box.isTrigger = true;
      spike.tag = "Hazard";
    }

    void SpawnPlayer(Vector2 at) {
      GameObject player = GameObject.FindWithTag("Player");
      if (player == null) player = Instantiate(playerPrefab, at, Quaternion.identity);
      else player.transform.position = at;
      player.GetComponent<PlayerController2D>().Setup(spec.player, spec.world, this);
    }
  }
}
'''

_PLAYER_CS = '''// Movement read from the spec: speed, jump height, extra jumps, dash, wall jump.
// Change the numbers in NyxLevel.json, not here.
using UnityEngine;

namespace NyxGame {
  [RequireComponent(typeof(Rigidbody2D))]
  public class PlayerController2D : MonoBehaviour {
    Player stats; World world; LevelBuilder level;
    Rigidbody2D body; int jumpsLeft; float dashLeft; int health; bool facingRight = true;

    public void Setup(Player player, World w, LevelBuilder builder) {
      stats = player; world = w; level = builder; health = player.health;
      body = GetComponent<Rigidbody2D>();
      body.gravityScale = world.gravity / 9.81f;
      GetComponent<Renderer>().material.color = GameSpec.Ink(player.colour, Color.white);
    }

    void Update() {
      if (stats == null) return;
      float move = Input.GetAxisRaw("Horizontal");
      if (move != 0) facingRight = move > 0;
      float control = Grounded() ? 1f : world.air_control;
      body.velocity = new Vector2(move * stats.speed * control, Mathf.Max(body.velocity.y, -world.terminal_velocity));

      if (Grounded()) jumpsLeft = stats.max_jumps;
      if (Input.GetButtonDown("Jump") && jumpsLeft > 0) {
        jumpsLeft--;
        body.velocity = new Vector2(body.velocity.x, stats.jump);
      }
      if (stats.dash && Input.GetKeyDown(KeyCode.LeftShift) && dashLeft <= 0f) {
        dashLeft = 0.18f;
        body.velocity = new Vector2((facingRight ? 1 : -1) * stats.speed * 2.6f, 0f);
      }
      if (dashLeft > 0f) { dashLeft -= Time.deltaTime; body.gravityScale = 0f; }
      else body.gravityScale = world.gravity / 9.81f;
    }

    bool Grounded() {
      return Physics2D.Raycast(transform.position, Vector2.down, 0.55f, ~(1 << gameObject.layer));
    }

    void OnTriggerEnter2D(Collider2D other) {
      if (other.CompareTag("Hazard")) Hurt(1);
    }

    public void Hurt(int amount) {
      health -= amount;
      if (health <= 0 && level != null) level.Build(level.spec.rooms[0].id, -1, -1);
    }
  }
}
'''

_ENEMY_CS = '''// One component, four behaviours, all read from the spec.
using UnityEngine;

namespace NyxGame {
  public class EnemyController : MonoBehaviour {
    Enemy stats; int direction = 1; Transform player;

    public void Setup(Enemy enemy) {
      stats = enemy;
      transform.localScale = Vector3.one * enemy.size;
      GetComponent<Renderer>().material.color = GameSpec.Ink(enemy.colour, Color.red);
      GameObject found = GameObject.FindWithTag("Player");
      if (found != null) player = found.transform;
    }

    void Update() {
      if (stats == null) return;
      if (stats.behaviour == "patrol") {
        transform.position += Vector3.right * direction * stats.speed * Time.deltaTime;
        if (!Physics2D.Raycast(transform.position + Vector3.right * direction * 0.6f, Vector2.down, 1.2f)) direction = -direction;
      } else if (stats.behaviour == "chaser" && player != null) {
        transform.position = Vector3.MoveTowards(transform.position,
          new Vector3(player.position.x, transform.position.y, 0), stats.speed * Time.deltaTime);
      } else if (stats.behaviour == "flyer" && player != null) {
        transform.position = Vector3.MoveTowards(transform.position, player.position, stats.speed * Time.deltaTime);
      } else if (stats.behaviour == "jumper") {
        Rigidbody2D body = GetComponent<Rigidbody2D>();
        if (body != null && Mathf.Abs(body.velocity.y) < 0.01f) body.velocity = new Vector2(0, stats.speed * 2f);
      }
    }

    void OnCollisionEnter2D(Collision2D other) {
      PlayerController2D hit = other.gameObject.GetComponent<PlayerController2D>();
      if (hit != null) hit.Hurt(stats.damage);
    }
  }
}
'''


def unity_files(game_id: str) -> List[Dict[str, str]]:
    """The Unity project files for this game. Fixed C#, plus the spec as JSON."""
    game = _require(game_id)
    folder = re.sub(r"[^A-Za-z0-9]+", "", game["title"].title()) or "NyxGame"
    root = f"Assets/{folder}"
    readme = [
        f"# {game['title']} — Unity import",
        "",
        "Nyx wrote this folder from the game you designed in the Game Studio tab. Nyx did not compile or run",
        "anything; these are plain files you open yourself.",
        "",
        "## Steps",
        "",
        "1. Unity Hub → New project → **2D (Built-In Render Pipeline)**" if game["kind"] == "2d"
        else "1. Unity Hub → New project → **3D (Built-In Render Pipeline)**",
        f"2. Close Unity, copy this whole `{folder}` folder into the project's `Assets/` folder, reopen Unity.",
        "3. Open a new scene. Create an empty GameObject called `Level` and add the `LevelBuilder` component.",
        f"4. Drag `{root}/NyxLevel.json` onto the component's **Level Json** slot.",
        "5. Make a Player prefab: a Sprite (Square), tag it `Player`, add `Rigidbody2D` (freeze Z rotation),",
        "   a `BoxCollider2D`, and the `PlayerController2D` script. Drag it to the **Player Prefab** slot.",
        "6. Make an Enemy prefab the same way with `EnemyController`, and drag it to **Enemy Prefab**.",
        "7. Press Play. Arrows/WASD move, Space jumps" + (", Left Shift dashes" if game["player"]["dash"] else "") + ".",
        "",
        "## Changing the game",
        "",
        "Everything about the level lives in `NyxLevel.json` — tiles, enemies, abilities, colours, the player's",
        "speed and jump. Edit it there (or back in the Game Studio tab) and press Play again; the C# does not",
        "need to change.",
        "",
        "## What is in here",
        "",
        "| File | What it does |",
        "| --- | --- |",
        "| `NyxLevel.json` | The whole game as data |",
        "| `Scripts/GameSpec.cs` | Classes Unity reads the JSON into |",
        "| `Scripts/LevelBuilder.cs` | Turns tile rows into colliders, hazards and spawns |",
        "| `Scripts/PlayerController2D.cs` | Movement, jumps, dash — numbers come from the JSON |",
        "| `Scripts/EnemyController.cs` | patrol / chaser / flyer / jumper |",
        "",
        f"Rooms: {', '.join(room['name'] for room in game['rooms']) or 'none yet'}.",
    ]
    if game["kind"] == "3d":
        readme += [
            "",
            "## This one is a 3D game",
            "",
            "The tile grid is the floor plan: `#` is a wall block, `=` a low platform, `^` a hazard pad. In a 3D",
            "project, swap `Quad` for `Cube` in `LevelBuilder` and use a 3D character controller — the spec and the",
            "room data do not change.",
        ]
    return [
        {"path": f"{root}/NyxLevel.json", "text": json.dumps(game, ensure_ascii=False, indent=2)},
        {"path": f"{root}/README.md", "text": "\n".join(readme) + "\n"},
        {"path": f"{root}/Scripts/GameSpec.cs", "text": _SPEC_CS},
        {"path": f"{root}/Scripts/LevelBuilder.cs", "text": _BUILDER_CS},
        {"path": f"{root}/Scripts/PlayerController2D.cs", "text": _PLAYER_CS},
        {"path": f"{root}/Scripts/EnemyController.cs", "text": _ENEMY_CS},
    ]


def export_to_folder(game_id: str, folder: str) -> Dict[str, Any]:
    """Write the Unity files into a folder the owner opened in the Code tab."""
    import code_workspace

    base = folder.rstrip("/\\")
    written: List[str] = []
    for item in unity_files(game_id):
        try:
            code_workspace.create_file(base + "/" + item["path"], item["text"])
        except Exception as error:  # noqa: BLE001 - say which file, do not half-hide it
            raise GameError(f"Could not write {item['path']}: {error}") from error
        written.append(item["path"])
    return {"folder": folder, "files": written}
