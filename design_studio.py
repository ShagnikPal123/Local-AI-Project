"""The 3D Build studio: parts, assemblies and circuits as validated data.

Request H4 and the 2026-09-15 follow-up ("make sure each part is highlighted,
similar to a tutorial... complex kinds of tools... combine parts, save parts,
and combine to a single space and connect. circuits can connect and the AI
helps heavily").

Nothing here is executable geometry. A part is a *feature tree* - a list of
solid primitives with an operation (add / cut / intersect), a blend radius and
modifiers (array, mirror, shell). The browser turns that tree into a mesh by
sampling a signed distance field, so the same spec can come from the owner
clicking buttons or from a model emitting JSON, and both are validated by the
identical code path (invariant 2: specs are data, never code).

Three levels, because the owner asked for all three:

``part``
    One thing you could print or buy. Features + pins.
``placement``
    That part positioned in the project's single shared space, so many parts
    combine into one machine.
``net``
    A wire between two pins of two placements. Nets are what make circuits
    "connect", and what the rule checks reason about.

The library (``data/build/library.json``) is where a part is *saved* so it can
be dropped into any other project, alongside a built-in catalog of real boards
and components with real millimetre sizes and real pinouts.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from paths import atomic_replace, data_path

_LOCK = threading.RLock()

#: Guard rails. A spec that would take minutes to mesh is a bug, not a design.
MAX_PARTS = 240
MAX_FEATURES = 200
MAX_PROFILE_POINTS = 96
MAX_PINS = 128
MAX_PLACEMENTS = 400
MAX_NETS = 300
MAX_STEPS = 60

PART_KINDS = ("mechanical", "electronic", "enclosure", "fastener", "material")
FEATURE_TYPES = ("box", "cylinder", "sphere", "cone", "torus", "wedge", "pipe", "extrude", "revolve")
FEATURE_OPS = ("add", "cut", "intersect")
PIN_KINDS = ("power", "gnd", "digital", "analog", "pwm", "i2c", "spi", "uart", "usb", "net", "mech")
PIN_DIRECTIONS = ("in", "out", "bidir", "power", "gnd", "passive")
NET_KINDS = ("power", "gnd", "signal", "bus", "mechanical")
JOINT_KINDS = ("fixed", "stack", "slide", "hinge", "screw", "clip")

DEFAULT_SPACE = {"width": 300.0, "depth": 300.0, "height": 300.0}


class BuildError(ValueError):
    """A spec the studio refuses, carrying a sentence the UI can show as-is."""


# --- small validators ---------------------------------------------------------
#
# Every one of these is total: it takes anything (a model's JSON, a form post)
# and returns a value inside the allowed range. Nothing below raises on a bad
# type, only on "this design cannot exist at all".


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def _num(value: Any, default: float = 0.0, lo: float = -100000.0, hi: float = 100000.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out or out in (float("inf"), float("-inf")):  # NaN / inf from a model
        return default
    return max(lo, min(hi, out))


def _pos(value: Any, default: float, hi: float = 100000.0) -> float:
    """A dimension that has to be above zero - a 0 mm wall is not a wall."""
    out = _num(value, default, 0.0, hi)
    return out if out > 0.0001 else default


def _int(value: Any, default: int = 0, lo: int = 0, hi: int = 1000) -> int:
    try:
        out = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, out))


def _text(value: Any, limit: int = 200, default: str = "") -> str:
    out = str(value if value is not None else "").strip()
    return out[:limit] if out else default


def _one_of(value: Any, allowed: Sequence[str], default: str) -> str:
    out = str(value or "").strip().lower().replace(" ", "_")
    return out if out in allowed else default


def _vec3(value: Any, default: Tuple[float, float, float] = (0.0, 0.0, 0.0)) -> List[float]:
    if isinstance(value, dict):
        value = [value.get("x"), value.get("y"), value.get("z")]
    if not isinstance(value, (list, tuple)):
        return list(default)
    out = list(default)
    for index in range(3):
        if index < len(value):
            out[index] = _num(value[index], default[index], -100000.0, 100000.0)
    return out


def _color(value: Any, default: str = "#9aa4b2") -> str:
    out = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", out):
        return out.lower()
    if re.fullmatch(r"#[0-9a-fA-F]{3}", out):
        return "#" + "".join(c * 2 for c in out[1:]).lower()
    return default


def _profile(value: Any) -> List[List[float]]:
    """A closed 2D outline in mm, [[x, y], ...] - the input to extrude/revolve."""
    points: List[List[float]] = []
    for raw in value if isinstance(value, (list, tuple)) else []:
        if isinstance(raw, dict):
            raw = [raw.get("x"), raw.get("y")]
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            continue
        points.append([_num(raw[0], 0.0, -10000, 10000), _num(raw[1], 0.0, -10000, 10000)])
        if len(points) >= MAX_PROFILE_POINTS:
            break
    return points


def _scalars(value: Any, limit: int = 24) -> Dict[str, Any]:
    """Free-form part specs (voltage, current, price) kept to flat scalars."""
    out: Dict[str, Any] = {}
    if not isinstance(value, dict):
        return out
    for key, raw in list(value.items())[:limit]:
        name = _text(key, 40)
        if not name:
            continue
        if isinstance(raw, bool):
            out[name] = raw
        elif isinstance(raw, (int, float)):
            out[name] = _num(raw)
        else:
            out[name] = _text(raw, 200)
    return out


# --- features -----------------------------------------------------------------

#: Per primitive: the size fields it understands, with default and ceiling.
_SIZE_FIELDS: Dict[str, Dict[str, Tuple[float, float]]] = {
    "box": {"w": (20.0, 5000.0), "d": (20.0, 5000.0), "h": (20.0, 5000.0)},
    "cylinder": {"r": (10.0, 2500.0), "h": (20.0, 5000.0)},
    "sphere": {"r": (10.0, 2500.0)},
    "cone": {"r": (10.0, 2500.0), "r2": (0.0, 2500.0), "h": (20.0, 5000.0)},
    "torus": {"r": (15.0, 2500.0), "t": (4.0, 1000.0)},
    "wedge": {"w": (20.0, 5000.0), "d": (20.0, 5000.0), "h": (20.0, 5000.0)},
    "pipe": {"r": (10.0, 2500.0), "t": (2.0, 1000.0), "h": (20.0, 5000.0)},
    "extrude": {"h": (5.0, 5000.0)},
    "revolve": {"angle": (360.0, 360.0)},
}


def clean_feature(raw: Any) -> Optional[Dict[str, Any]]:
    """Validate one solid in a part's feature tree. None means unusable."""
    if not isinstance(raw, dict):
        return None
    kind = _one_of(raw.get("type") or raw.get("kind"), FEATURE_TYPES, "")
    if not kind:
        return None

    size_in = raw.get("size") if isinstance(raw.get("size"), dict) else raw
    size: Dict[str, float] = {}
    for field, (default, ceiling) in _SIZE_FIELDS[kind].items():
        given = size_in.get(field, raw.get(field))
        # r2 is the only size allowed to be zero: a cone that comes to a point.
        size[field] = _num(given, default, 0.0, ceiling) if field == "r2" else _pos(given, default, ceiling)

    feature: Dict[str, Any] = {
        "id": _text(raw.get("id"), 32) or _new_id("f"),
        "type": kind,
        "name": _text(raw.get("name"), 60) or kind.title(),
        "op": _one_of(raw.get("op"), FEATURE_OPS, "add"),
        "at": _vec3(raw.get("at") or raw.get("position")),
        "rot": _vec3(raw.get("rot") or raw.get("rotation")),
        "size": size,
        # Rounding and blending are what make this feel like CAD rather than
        # stacked boxes: `round` is an edge radius, `blend` is a fillet where
        # this solid meets everything before it.
        "round": _num(raw.get("round"), 0.0, 0.0, 200.0),
        "blend": _num(raw.get("blend"), 0.0, 0.0, 200.0),
        "note": _text(raw.get("note"), 400),
    }

    if kind in ("extrude", "revolve"):
        profile = _profile(raw.get("profile"))
        if len(profile) < 3:
            return None
        feature["profile"] = profile

    # A cylinder with a side count is a prism: that is how a hex standoff, a
    # nut or a triangular brace gets made without a hand-drawn outline.
    if kind in ("cylinder", "cone", "pipe"):
        sides = _int(raw.get("sides"), 0, 0, 64)
        if sides >= 3:
            feature["sides"] = sides

    repeat = raw.get("repeat") if isinstance(raw.get("repeat"), dict) else None
    if repeat:
        count = _int(repeat.get("count"), 1, 1, 64)
        if count > 1:
            feature["repeat"] = {"count": count, "step": _vec3(repeat.get("step"), (10.0, 0.0, 0.0))}

    radial = raw.get("radial") if isinstance(raw.get("radial"), dict) else None
    if radial:
        count = _int(radial.get("count"), 1, 1, 64)
        if count > 1:
            feature["radial"] = {
                "count": count,
                "axis": _one_of(radial.get("axis"), ("x", "y", "z"), "y"),
                "radius": _num(radial.get("radius"), 20.0, 0.0, 5000.0),
            }

    # Optional per-shape colour: a green board with silver connectors reads as
    # a Raspberry Pi at a glance; one flat colour reads as a green brick.
    colour = _color(raw.get("color"), "")
    if colour:
        feature["color"] = colour

    given_mirror = [str(m).lower() for m in (raw.get("mirror") or []) if isinstance(m, str)]
    mirror = [axis for axis in ("x", "y", "z") if axis in given_mirror]
    if mirror:
        feature["mirror"] = mirror
    return feature


def clean_pin(raw: Any) -> Optional[Dict[str, Any]]:
    """A connectable point on a part: where a wire, screw or bolt lands."""
    if not isinstance(raw, dict):
        return None
    name = _text(raw.get("name") or raw.get("label"), 40)
    if not name:
        return None
    return {
        "id": _text(raw.get("id"), 32) or _new_id("p"),
        "name": name,
        "kind": _one_of(raw.get("kind"), PIN_KINDS, "digital"),
        "direction": _one_of(raw.get("direction"), PIN_DIRECTIONS, "passive"),
        "at": _vec3(raw.get("at") or raw.get("position")),
        "voltage": _num(raw.get("voltage"), 0.0, -60.0, 600.0),
        # Marked pins are the ones the checks complain about when left floating.
        "required": bool(raw.get("required")),
        "note": _text(raw.get("note"), 300),
    }


def clean_part(raw: Any, *, keep_id: str = "") -> Dict[str, Any]:
    """Validate a whole part. Raises BuildError only when nothing is left."""
    if not isinstance(raw, dict):
        raise BuildError("That part was not in a shape the studio understands.")

    features: List[Dict[str, Any]] = []
    for item in (raw.get("features") or [])[: MAX_FEATURES * 2]:
        cleaned = clean_feature(item)
        if cleaned:
            features.append(cleaned)
        if len(features) >= MAX_FEATURES:
            break
    if not features:
        raise BuildError("A part needs at least one shape - add a box, cylinder or outline first.")
    # A tree that opens with a cut has nothing to cut from, which renders as an
    # invisible part: the single most confusing thing a model can emit here.
    if features[0]["op"] != "add":
        features[0] = {**features[0], "op": "add"}

    pins: List[Dict[str, Any]] = []
    seen_pins: set[str] = set()
    for item in (raw.get("pins") or [])[: MAX_PINS * 2]:
        cleaned = clean_pin(item)
        if not cleaned:
            continue
        # A repeated id is a numbering slip, not a duplicate pin. Dropping it
        # made a buck converter lose its outputs, so it gets a fresh id instead.
        if cleaned["id"] in seen_pins:
            cleaned["id"] = _new_id("p")
        seen_pins.add(cleaned["id"])
        pins.append(cleaned)
        if len(pins) >= MAX_PINS:
            break

    now = time.time()
    shell = raw.get("shell") if isinstance(raw.get("shell"), dict) else None
    part: Dict[str, Any] = {
        "id": keep_id or _text(raw.get("id"), 32) or _new_id(),
        "name": _text(raw.get("name"), 80) or "New part",
        "kind": _one_of(raw.get("kind"), PART_KINDS, "mechanical"),
        "color": _color(raw.get("color")),
        "material": _text(raw.get("material"), 60),
        "summary": _text(raw.get("summary") or raw.get("description"), 600),
        "features": features,
        "pins": pins,
        "specs": _scalars(raw.get("specs")),
        "tags": [_text(t, 30) for t in (raw.get("tags") or [])[:12] if _text(t, 30)],
        "source": _one_of(raw.get("source"), ("owner", "ai", "catalog"), "owner"),
        "catalog_id": _text(raw.get("catalog_id"), 60),
        "created_at": _num(raw.get("created_at"), now, 0, 4e9) or now,
        "updated_at": now,
    }
    if shell and _num(shell.get("thickness"), 0.0) > 0:
        part["shell"] = {"thickness": _num(shell.get("thickness"), 2.0, 0.1, 200.0)}
    return part


# --- bounds -------------------------------------------------------------------
#
# The same arithmetic runs in the browser to size the sampling grid. It lives
# here too because the checks (does it fit the printer? do two parts overlap?)
# must not depend on anything having been rendered first.


def _feature_extent(feature: Dict[str, Any]) -> List[float]:
    """Half-sizes on each local axis, before the feature's own rotation.

    Per-axis, not a bounding sphere: a 85 x 56 x 1.6 mm board has a 51 mm
    sphere around it, and treating that as its height turns every overlap and
    printer-fit check into noise.

    Axis conventions, shared with the browser mesher: a cylinder, cone, pipe
    and revolve stand along Y; a torus lies in the XZ plane; an extruded
    profile is drawn in XZ and pushed along Y.
    """
    size = feature["size"]
    kind = feature["type"]
    if kind in ("box", "wedge"):
        return [size["w"] / 2, size["h"] / 2, size["d"] / 2]
    if kind in ("cylinder", "pipe"):
        return [size["r"], size["h"] / 2, size["r"]]
    if kind == "sphere":
        return [size["r"]] * 3
    if kind == "cone":
        widest = max(size["r"], size["r2"])
        return [widest, size["h"] / 2, widest]
    if kind == "torus":
        return [size["r"] + size["t"], size["t"], size["r"] + size["t"]]
    profile = feature.get("profile") or [[0.0, 0.0]]
    if kind == "extrude":
        return [max(abs(x) for x, _ in profile) or 10.0,
                size["h"] / 2,
                max(abs(z) for _, z in profile) or 10.0]
    # revolve: the profile is (radius, height) swept around Y.
    reach = max(abs(r) for r, _ in profile) or 10.0
    return [reach, max(abs(y) for _, y in profile) or 10.0, reach]


def _rotated_extent(extent: Sequence[float], rot_degrees: Sequence[float]) -> List[float]:
    """Half-sizes of the axis-aligned box around a rotated box."""
    if not any(rot_degrees):
        return list(extent)
    rx, ry, rz = (math.radians(r) for r in rot_degrees)
    a, b = math.cos(rx), math.sin(rx)
    c, d = math.cos(ry), math.sin(ry)
    e, f = math.cos(rz), math.sin(rz)
    # Euler XYZ, the three.js default order (R = Rx.Ry.Rz).
    rows = (
        (c * e, -c * f, d),
        (a * f + b * d * e, a * e - b * d * f, -b * c),
        (b * f - a * d * e, b * e + a * d * f, a * c),
    )
    return [sum(abs(rows[axis][i]) * extent[i] for i in range(3)) for axis in range(3)]


def part_bounds(part: Dict[str, Any]) -> Dict[str, List[float]]:
    """An axis-aligned box around everything a part adds.

    Cuts are ignored on purpose: a hole never makes a part bigger, and counting
    one would turn the printer-fit check into a lie.
    """
    lo = [1e9, 1e9, 1e9]
    hi = [-1e9, -1e9, -1e9]
    axes = {"x": 0, "y": 1, "z": 2}
    for feature in part.get("features", []):
        if feature.get("op") != "add":
            continue
        # Rounding an edge never makes a shape bigger, and a smooth blend adds at
        # most a quarter of its radius at the seam - so only that counts here.
        grow = feature.get("blend", 0.0) * 0.25
        extent = [half + grow for half in _rotated_extent(_feature_extent(feature), feature.get("rot", [0, 0, 0]))]
        centres = [list(feature["at"])]
        repeat = feature.get("repeat")
        if repeat:
            step = repeat["step"]
            centres = [[feature["at"][i] + step[i] * n for i in range(3)] for n in range(repeat["count"])]
        radial = feature.get("radial")
        if radial:
            # A ring of copies reaches the orbit radius on both axes it turns in.
            spread = radial["radius"]
            turning = {"x": (1, 2), "y": (0, 2), "z": (0, 1)}[radial["axis"]]
            for index in turning:
                extent[index] += spread
        # Each mirror axis doubles the set, so ["x", "z"] fills all four
        # quadrants - the same rule the browser mesher follows.
        for axis in feature.get("mirror") or []:
            flipped_set = []
            for centre in centres:
                flipped = list(centre)
                flipped[axes[axis]] = -flipped[axes[axis]]
                flipped_set.append(flipped)
            centres = centres + flipped_set
        for centre in centres:
            for i in range(3):
                lo[i] = min(lo[i], centre[i] - extent[i])
                hi[i] = max(hi[i], centre[i] + extent[i])
    if lo[0] > hi[0]:
        return {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0], "size": [0.0, 0.0, 0.0]}
    return {"min": lo, "max": hi, "size": [hi[i] - lo[i] for i in range(3)]}


def _feature_volume(feature: Dict[str, Any]) -> float:
    """Rough mm3 for one solid, used only for the material estimate."""
    size = feature["size"]
    kind = feature["type"]
    if kind == "box":
        volume = size["w"] * size["d"] * size["h"]
    elif kind == "wedge":
        volume = size["w"] * size["d"] * size["h"] / 2
    elif kind == "cylinder":
        volume = math.pi * size["r"] ** 2 * size["h"]
    elif kind == "pipe":
        inner = max(0.0, size["r"] - size["t"])
        volume = math.pi * (size["r"] ** 2 - inner ** 2) * size["h"]
    elif kind == "sphere":
        volume = 4 / 3 * math.pi * size["r"] ** 3
    elif kind == "cone":
        r1, r2 = size["r"], size["r2"]
        volume = math.pi * size["h"] / 3 * (r1 * r1 + r1 * r2 + r2 * r2)
    elif kind == "torus":
        volume = 2 * math.pi ** 2 * size["r"] * size["t"] ** 2
    elif kind == "extrude":
        area = 0.0
        points = feature.get("profile") or []
        for index in range(len(points)):
            x1, y1 = points[index]
            x2, y2 = points[(index + 1) % len(points)]
            area += x1 * y2 - x2 * y1
        volume = abs(area) / 2 * size["h"]
    else:  # revolve: Pappus, using the profile centroid
        points = feature.get("profile") or []
        if len(points) < 3:
            return 0.0
        area = 0.0
        cx = 0.0
        for index in range(len(points)):
            x1, y1 = points[index]
            x2, y2 = points[(index + 1) % len(points)]
            cross = x1 * y2 - x2 * y1
            area += cross
            cx += (x1 + x2) * cross
        area /= 2
        cx = cx / (6 * area) if abs(area) > 1e-9 else 0.0
        volume = abs(2 * math.pi * cx * area)

    copies = 1
    if feature.get("repeat"):
        copies *= feature["repeat"]["count"]
    if feature.get("radial"):
        copies *= feature["radial"]["count"]
    if feature.get("mirror"):
        copies *= 2 ** len(feature["mirror"])
    return volume * copies


def part_volume(part: Dict[str, Any]) -> float:
    """Added volume minus cut volume, in mm3.

    Overlaps are not subtracted, so this is an estimate and is always labelled
    as one where it reaches the screen. It is still the right order of
    magnitude for "how much filament will this take".
    """
    total = 0.0
    for feature in part.get("features", []):
        volume = _feature_volume(feature)
        if feature.get("op") == "cut":
            total -= volume
        elif feature.get("op") == "add":
            total += volume
    return max(0.0, total)


# --- the store ----------------------------------------------------------------
#
# Projects and the saved-parts library are two files. They are separate because
# a library part outlives the project it was drawn in - that is the whole point
# of saving one.


def _projects_path():
    return data_path("build/projects.json")


def _library_path():
    return data_path("build/library.json")


def _read(path, empty: Dict[str, Any]) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key, value in empty.items():
                data.setdefault(key, value)
            return data
    except (OSError, ValueError):
        pass
    return dict(empty)


def _write(path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    atomic_replace(temp, path)


def _blank_project(name: str, goal: str = "") -> Dict[str, Any]:
    now = time.time()
    return {
        "id": _new_id(),
        "name": _text(name, 80) or "New build",
        "goal": _text(goal, 1200),
        "space": dict(DEFAULT_SPACE),
        "parts": [],
        "placements": [],
        "joints": [],
        "nets": [],
        "tutorial": None,
        "comparison": None,
        "notes": "",
        "created_at": now,
        "updated_at": now,
    }


def _clean_space(raw: Any) -> Dict[str, float]:
    given = raw if isinstance(raw, dict) else {}
    return {
        "width": _pos(given.get("width"), DEFAULT_SPACE["width"], 5000.0),
        "depth": _pos(given.get("depth"), DEFAULT_SPACE["depth"], 5000.0),
        "height": _pos(given.get("height"), DEFAULT_SPACE["height"], 5000.0),
    }


def _load_projects() -> Dict[str, Any]:
    return _read(_projects_path(), {"projects": [], "active": ""})


def list_projects() -> Dict[str, Any]:
    with _LOCK:
        data = _load_projects()
    summaries = []
    for project in data["projects"]:
        summaries.append({
            "id": project["id"],
            "name": project["name"],
            "goal": project.get("goal", ""),
            "parts": len(project.get("parts", [])),
            "placements": len(project.get("placements", [])),
            "nets": len(project.get("nets", [])),
            "updated_at": project.get("updated_at", 0),
            "has_tutorial": bool((project.get("tutorial") or {}).get("steps")),
        })
    summaries.sort(key=lambda p: -p["updated_at"])
    return {"projects": summaries, "active": data.get("active", "")}


def get_project(project_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        for project in _load_projects()["projects"]:
            if project["id"] == project_id:
                return project
    return None


def project_or_error(project_id: str) -> Dict[str, Any]:
    project = get_project(project_id)
    if project is None:
        raise BuildError("That build no longer exists. Pick another one from the list.")
    return project


def _save_project(project: Dict[str, Any]) -> Dict[str, Any]:
    project["updated_at"] = time.time()
    with _LOCK:
        data = _load_projects()
        for index, existing in enumerate(data["projects"]):
            if existing["id"] == project["id"]:
                data["projects"][index] = project
                break
        else:
            data["projects"].append(project)
        data["active"] = project["id"]
        _write(_projects_path(), data)
    return project


def create_project(name: str, goal: str = "") -> Dict[str, Any]:
    return _save_project(_blank_project(name, goal))


def update_project(project_id: str, **fields: Any) -> Dict[str, Any]:
    project = project_or_error(project_id)
    if "name" in fields:
        project["name"] = _text(fields["name"], 80) or project["name"]
    if "goal" in fields:
        project["goal"] = _text(fields["goal"], 1200)
    if "notes" in fields:
        project["notes"] = _text(fields["notes"], 8000)
    if "space" in fields:
        project["space"] = _clean_space(fields["space"])
    return _save_project(project)


def set_active(project_id: str) -> None:
    with _LOCK:
        data = _load_projects()
        if any(p["id"] == project_id for p in data["projects"]):
            data["active"] = project_id
            _write(_projects_path(), data)


def delete_project(project_id: str) -> bool:
    with _LOCK:
        data = _load_projects()
        before = len(data["projects"])
        data["projects"] = [p for p in data["projects"] if p["id"] != project_id]
        if data.get("active") == project_id:
            data["active"] = data["projects"][0]["id"] if data["projects"] else ""
        _write(_projects_path(), data)
        return len(data["projects"]) < before


# --- parts inside a project ---------------------------------------------------


def find_part(project: Dict[str, Any], part_id: str) -> Optional[Dict[str, Any]]:
    return next((p for p in project.get("parts", []) if p["id"] == part_id), None)


def save_part(project_id: str, spec: Any, part_id: str = "") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Add or replace one part. Returns (project, part)."""
    project = project_or_error(project_id)
    existing = find_part(project, part_id) if part_id else None
    part = clean_part(spec, keep_id=part_id or "")
    if existing:
        part["created_at"] = existing.get("created_at", part["created_at"])
        project["parts"] = [part if p["id"] == part["id"] else p for p in project["parts"]]
    else:
        if len(project["parts"]) >= MAX_PARTS:
            raise BuildError(f"This build already has {MAX_PARTS} parts. Delete one before adding another.")
        project["parts"].append(part)
    return _save_project(project), part


def delete_part(project_id: str, part_id: str) -> Dict[str, Any]:
    """Remove a part, and everything in the space that pointed at it.

    Leaving orphan placements behind is how a studio ends up rendering ghosts,
    so the cascade is deliberate and total.
    """
    project = project_or_error(project_id)
    project["parts"] = [p for p in project["parts"] if p["id"] != part_id]
    dropped = {p["id"] for p in project["placements"] if p["part_id"] == part_id}
    project["placements"] = [p for p in project["placements"] if p["part_id"] != part_id]
    project["joints"] = [j for j in project["joints"] if j["a"] not in dropped and j["b"] not in dropped]
    for net in project["nets"]:
        net["points"] = [pt for pt in net["points"] if pt["placement"] not in dropped]
    project["nets"] = [n for n in project["nets"] if n["points"]]
    return _save_project(project)


def duplicate_part(project_id: str, part_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    project = project_or_error(project_id)
    source = find_part(project, part_id)
    if source is None:
        raise BuildError("That part is not in this build.")
    copy = json.loads(json.dumps(source))
    copy["id"] = _new_id()
    copy["name"] = f"{source['name']} copy"
    for feature in copy["features"]:
        feature["id"] = _new_id("f")
    return save_part(project_id, copy)


# --- the shared space: placements and joints ----------------------------------


def clean_placement(raw: Any, *, part_id: str = "", keep_id: str = "") -> Dict[str, Any]:
    given = raw if isinstance(raw, dict) else {}
    return {
        "id": keep_id or _text(given.get("id"), 32) or _new_id("pl"),
        "part_id": part_id or _text(given.get("part_id"), 32),
        "name": _text(given.get("name"), 80),
        "at": _vec3(given.get("at")),
        "rot": _vec3(given.get("rot")),
        "scale": _num(given.get("scale"), 1.0, 0.05, 20.0),
        "color": _color(given.get("color"), "") if given.get("color") else "",
        "locked": bool(given.get("locked")),
        "group": _text(given.get("group"), 40),
        "note": _text(given.get("note"), 400),
    }


def _free_spot(project: Dict[str, Any], part: Dict[str, Any]) -> List[float]:
    """Where to drop a part nobody positioned: on the plate, beside the rest.

    Dropping everything at the origin buries each new part inside the last one,
    and the checks then open with a page of overlap warnings the owner did not
    cause. Seating it on the plate and walking outwards costs nothing and means
    a fresh part is visible and legal the moment it appears.
    """
    bounds = part_bounds(part)
    seated = -bounds["min"][1]
    space = _clean_space(project.get("space"))
    taken = [box for box in (placement_box(project, p) for p in project.get("placements", [])) if box]
    gap = 6.0
    limit_x, limit_z = space["width"] / 2, space["depth"] / 2

    def clear(x: float, z: float) -> bool:
        box = {
            "min": [x + bounds["min"][0] - gap, seated + bounds["min"][1], z + bounds["min"][2] - gap],
            "max": [x + bounds["max"][0] + gap, seated + bounds["max"][1], z + bounds["max"][2] + gap],
        }
        return not any(_overlap(box, other, slack=0.0) for other in taken)

    # Every legal spot on a 5 mm grid, nearest the centre first. The grid is
    # fine-grained because stepping by the new part's width skips every gap
    # narrower than it - which is how a Pi and a supply once ended up merged.
    candidates = []
    for ix in range(-int(limit_x // 5), int(limit_x // 5) + 1):
        x = ix * 5.0
        if x + bounds["min"][0] < -limit_x or x + bounds["max"][0] > limit_x:
            continue
        for iz in range(-int(limit_z // 5), int(limit_z // 5) + 1):
            z = iz * 5.0
            if z + bounds["min"][2] < -limit_z or z + bounds["max"][2] > limit_z:
                continue
            candidates.append((x * x + z * z, x, z))
    for _distance, x, z in sorted(candidates):
        if clear(x, z):
            return [x, seated, z]

    # The space is full. Park it just past the right-hand edge rather than
    # inside something else: "sticks out of the build space" is a true
    # message, a silent overlap is not.
    right = max([limit_x] + [box["max"][0] for box in taken])
    return [right + gap - bounds["min"][0], seated, 0.0]


def place_part(project_id: str, part_id: str, at: Any = None, name: str = "") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drop a part into the single shared space."""
    project = project_or_error(project_id)
    part = find_part(project, part_id)
    if part is None:
        raise BuildError("That part is not in this build yet - save it first.")
    if len(project["placements"]) >= MAX_PLACEMENTS:
        raise BuildError(f"The space already holds {MAX_PLACEMENTS} pieces.")
    spot = _vec3(at) if at is not None else _free_spot(project, part)
    placement = clean_placement({"at": spot, "name": name or part["name"]}, part_id=part_id)
    project["placements"].append(placement)
    return _save_project(project), placement


def update_placement(project_id: str, placement_id: str, **fields: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    project = project_or_error(project_id)
    current = next((p for p in project["placements"] if p["id"] == placement_id), None)
    if current is None:
        raise BuildError("That piece is no longer in the space.")
    merged = {**current, **{k: v for k, v in fields.items() if v is not None}}
    placement = clean_placement(merged, part_id=current["part_id"], keep_id=placement_id)
    project["placements"] = [placement if p["id"] == placement_id else p for p in project["placements"]]
    return _save_project(project), placement


def delete_placement(project_id: str, placement_id: str) -> Dict[str, Any]:
    project = project_or_error(project_id)
    project["placements"] = [p for p in project["placements"] if p["id"] != placement_id]
    project["joints"] = [j for j in project["joints"] if placement_id not in (j["a"], j["b"])]
    for net in project["nets"]:
        net["points"] = [pt for pt in net["points"] if pt["placement"] != placement_id]
    project["nets"] = [n for n in project["nets"] if n["points"]]
    return _save_project(project)


def add_joint(project_id: str, a: str, b: str, kind: str = "fixed", note: str = "") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Fix two pieces together mechanically - bolted, stacked, hinged."""
    project = project_or_error(project_id)
    ids = {p["id"] for p in project["placements"]}
    if a not in ids or b not in ids or a == b:
        raise BuildError("Pick two different pieces that are both in the space.")
    joint = {"id": _new_id("j"), "a": a, "b": b, "kind": _one_of(kind, JOINT_KINDS, "fixed"), "note": _text(note, 300)}
    project["joints"] = [j for j in project["joints"] if {j["a"], j["b"]} != {a, b}] + [joint]
    return _save_project(project), joint


def delete_joint(project_id: str, joint_id: str) -> Dict[str, Any]:
    project = project_or_error(project_id)
    project["joints"] = [j for j in project["joints"] if j["id"] != joint_id]
    return _save_project(project)


# --- circuits: nets -----------------------------------------------------------


_NET_COLORS = {"power": "#ff453a", "gnd": "#8e8e96", "signal": "#64d2ff", "bus": "#bf5af2", "mechanical": "#ffd60a"}


def _pin_of(project: Dict[str, Any], placement_id: str, pin_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    placement = next((p for p in project["placements"] if p["id"] == placement_id), None)
    if placement is None:
        raise BuildError("One of those pieces is not in the space any more.")
    part = find_part(project, placement["part_id"])
    if part is None:
        raise BuildError("One of those pieces has lost its part.")
    pin = next((p for p in part.get("pins", []) if p["id"] == pin_id), None)
    if pin is None:
        raise BuildError(f"{part['name']} has no pin called that.")
    return placement, pin


def _net_kind_for(pins: List[Dict[str, Any]]) -> str:
    kinds = {p["kind"] for p in pins}
    if "gnd" in kinds:
        return "gnd"
    if "power" in kinds:
        return "power"
    if "mech" in kinds:
        return "mechanical"
    if kinds & {"i2c", "spi", "uart", "usb"}:
        return "bus"
    return "signal"


def connect(project_id: str, a_placement: str, a_pin: str, b_placement: str, b_pin: str,
            name: str = "", kind: str = "") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Wire two pins together.

    A real netlist has no notion of "wire 3"; it has nets, and touching a third
    pin to an existing wire joins that net rather than making a second one. So
    connecting into either endpoint merges, and connecting two existing nets
    merges them - which is exactly the mistake (two supplies bridged by one
    jumper) the checks then need to be able to see.
    """
    project = project_or_error(project_id)
    placement_a, pin_a = _pin_of(project, a_placement, a_pin)
    placement_b, pin_b = _pin_of(project, b_placement, b_pin)
    if a_placement == b_placement and a_pin == b_pin:
        raise BuildError("That is the same pin twice.")

    point_a = {"placement": a_placement, "pin": a_pin}
    point_b = {"placement": b_placement, "pin": b_pin}

    def holds(net: Dict[str, Any], point: Dict[str, Any]) -> bool:
        return any(pt["placement"] == point["placement"] and pt["pin"] == point["pin"] for pt in net["points"])

    net_a = next((n for n in project["nets"] if holds(n, point_a)), None)
    net_b = next((n for n in project["nets"] if holds(n, point_b)), None)

    if net_a and net_b and net_a["id"] != net_b["id"]:
        net_a["points"] += [pt for pt in net_b["points"] if not holds(net_a, pt)]
        project["nets"] = [n for n in project["nets"] if n["id"] != net_b["id"]]
        net = net_a
    elif net_a or net_b:
        net = net_a or net_b
        for point in (point_a, point_b):
            if not holds(net, point):
                net["points"].append(point)
    else:
        if len(project["nets"]) >= MAX_NETS:
            raise BuildError(f"This build already has {MAX_NETS} nets.")
        net_kind = _one_of(kind, NET_KINDS, "") or _net_kind_for([pin_a, pin_b])
        net = {
            "id": _new_id("n"),
            "name": _text(name, 60) or f"{pin_a['name']} to {pin_b['name']}",
            "kind": net_kind,
            "color": _NET_COLORS.get(net_kind, "#64d2ff"),
            "voltage": max(pin_a["voltage"], pin_b["voltage"]),
            "points": [point_a, point_b],
            "note": "",
        }
        project["nets"].append(net)

    pins = [_pin_of(project, pt["placement"], pt["pin"])[1] for pt in net["points"]]
    net["kind"] = _one_of(kind, NET_KINDS, "") or _net_kind_for(pins)
    net["color"] = _NET_COLORS.get(net["kind"], net.get("color", "#64d2ff"))
    net["voltage"] = max((p["voltage"] for p in pins), default=0.0)
    return _save_project(project), net


def disconnect(project_id: str, net_id: str, placement_id: str = "", pin_id: str = "") -> Dict[str, Any]:
    """Drop one pin from a net, or the whole net when no pin is named."""
    project = project_or_error(project_id)
    if not placement_id:
        project["nets"] = [n for n in project["nets"] if n["id"] != net_id]
    else:
        for net in project["nets"]:
            if net["id"] == net_id:
                net["points"] = [pt for pt in net["points"]
                                 if not (pt["placement"] == placement_id and (not pin_id or pt["pin"] == pin_id))]
        project["nets"] = [n for n in project["nets"] if len(n["points"]) > 0]
    return _save_project(project)


def update_net(project_id: str, net_id: str, **fields: Any) -> Dict[str, Any]:
    project = project_or_error(project_id)
    for net in project["nets"]:
        if net["id"] == net_id:
            if fields.get("name") is not None:
                net["name"] = _text(fields["name"], 60) or net["name"]
            if fields.get("kind") is not None:
                net["kind"] = _one_of(fields["kind"], NET_KINDS, net["kind"])
                net["color"] = _NET_COLORS.get(net["kind"], net["color"])
            if fields.get("color") is not None:
                net["color"] = _color(fields["color"], net["color"])
            if fields.get("note") is not None:
                net["note"] = _text(fields["note"], 400)
            if fields.get("voltage") is not None:
                net["voltage"] = _num(fields["voltage"], net["voltage"], -60.0, 600.0)
    return _save_project(project)


# --- the saved-parts library --------------------------------------------------


def library() -> List[Dict[str, Any]]:
    with _LOCK:
        data = _read(_library_path(), {"parts": []})
    parts = []
    for part in data["parts"]:
        bounds = part_bounds(part)
        parts.append({
            "id": part["id"],
            "name": part["name"],
            "kind": part["kind"],
            "color": part["color"],
            "summary": part.get("summary", ""),
            "tags": part.get("tags", []),
            "source": part.get("source", "owner"),
            "features": len(part.get("features", [])),
            "pins": len(part.get("pins", [])),
            "size": [round(v, 1) for v in bounds["size"]],
            "updated_at": part.get("updated_at", 0),
        })
    parts.sort(key=lambda p: -p["updated_at"])
    return parts


def library_get(part_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        data = _read(_library_path(), {"parts": []})
    return next((p for p in data["parts"] if p["id"] == part_id), None)


def library_save(spec: Any) -> Dict[str, Any]:
    """Save a part so it can be dropped into any other build."""
    part = clean_part(spec)
    with _LOCK:
        data = _read(_library_path(), {"parts": []})
        # Same name, same source: this is a re-save, not a second copy - and it
        # keeps its library id, so anything that points at the saved part
        # still finds it after the owner saves an improved version.
        same = next((p for p in data["parts"]
                     if p["name"] == part["name"] and p.get("catalog_id", "") == part.get("catalog_id", "")), None)
        part["id"] = same["id"] if same else _new_id("lib")
        if same:
            part["created_at"] = same.get("created_at", part["created_at"])
        data["parts"] = [p for p in data["parts"] if p["id"] != part["id"]] + [part]
        _write(_library_path(), data)
    return part


def library_delete(part_id: str) -> bool:
    with _LOCK:
        data = _read(_library_path(), {"parts": []})
        before = len(data["parts"])
        data["parts"] = [p for p in data["parts"] if p["id"] != part_id]
        _write(_library_path(), data)
        return len(data["parts"]) < before


def use_library_part(project_id: str, library_id: str, at: Any = None) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Copy a saved part into a build and place it. Returns (project, part, placement)."""
    saved = library_get(library_id)
    if saved is None:
        raise BuildError("That saved part is gone from the library.")
    spec = json.loads(json.dumps(saved))
    spec["id"] = ""
    project, part = save_part(project_id, spec)
    project, placement = place_part(project["id"], part["id"], at=at)
    return project, part, placement


def use_catalog_part(project_id: str, catalog_id: str, at: Any = None) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Put a real component from the catalog into a build, already placed."""
    import build_catalog

    spec = build_catalog.expand(catalog_id)
    if spec is None:
        raise BuildError("There is no component with that id in the catalog.")
    project = project_or_error(project_id)
    # One catalog part, many placements: reuse the definition when it is
    # already here so four fans do not become four identical part entries.
    existing = next((p for p in project["parts"] if p.get("catalog_id") == catalog_id), None)
    if existing is None:
        project, part = save_part(project_id, spec)
    else:
        part = existing
    project, placement = place_part(project["id"], part["id"], at=at)
    return project, part, placement


# --- where things really are --------------------------------------------------
#
# The space is a printer bed: X across, Z deep, Y up from the plate at y = 0,
# centred on the origin in X and Z. Every check below speaks in those terms so
# "it does not fit" means the same thing here and on the screen.


def _rotate(vector: Sequence[float], rot_degrees: Sequence[float]) -> List[float]:
    """Euler XYZ in degrees, matching three.js default order (R = Rx.Ry.Rz)."""
    rx, ry, rz = (math.radians(r) for r in rot_degrees)
    a, b = math.cos(rx), math.sin(rx)
    c, d = math.cos(ry), math.sin(ry)
    e, f = math.cos(rz), math.sin(rz)
    x, y, z = vector
    m = (
        (c * e, -c * f, d),
        (a * f + b * d * e, a * e - b * d * f, -b * c),
        (b * f - a * d * e, b * e + a * d * f, a * c),
    )
    return [m[0][0] * x + m[0][1] * y + m[0][2] * z,
            m[1][0] * x + m[1][1] * y + m[1][2] * z,
            m[2][0] * x + m[2][1] * y + m[2][2] * z]


def placement_box(project: Dict[str, Any], placement: Dict[str, Any]) -> Optional[Dict[str, List[float]]]:
    """World-space box for one placed piece, with rotation and scale applied."""
    part = find_part(project, placement["part_id"])
    if part is None:
        return None
    bounds = part_bounds(part)
    scale = placement.get("scale", 1.0)
    lo = [1e9, 1e9, 1e9]
    hi = [-1e9, -1e9, -1e9]
    for sx in (bounds["min"][0], bounds["max"][0]):
        for sy in (bounds["min"][1], bounds["max"][1]):
            for sz in (bounds["min"][2], bounds["max"][2]):
                corner = _rotate([sx * scale, sy * scale, sz * scale], placement.get("rot", [0, 0, 0]))
                for i in range(3):
                    value = corner[i] + placement["at"][i]
                    lo[i] = min(lo[i], value)
                    hi[i] = max(hi[i], value)
    if lo[0] > hi[0]:
        return None
    return {"min": lo, "max": hi, "size": [hi[i] - lo[i] for i in range(3)]}


def world_pin(project: Dict[str, Any], placement: Dict[str, Any], pin: Dict[str, Any]) -> List[float]:
    scale = placement.get("scale", 1.0)
    local = [pin["at"][i] * scale for i in range(3)]
    turned = _rotate(local, placement.get("rot", [0, 0, 0]))
    return [turned[i] + placement["at"][i] for i in range(3)]


def _overlap(a: Dict[str, List[float]], b: Dict[str, List[float]], slack: float = 0.4) -> float:
    """Depth of the smallest overlapping axis, or 0.0 when they are clear."""
    depths = []
    for i in range(3):
        depth = min(a["max"][i], b["max"][i]) - max(a["min"][i], b["min"][i])
        if depth <= slack:
            return 0.0
        depths.append(depth)
    return min(depths)


# --- rule checks --------------------------------------------------------------


def _finding(level: str, message: str, where: Optional[Dict[str, str]] = None, fix: str = "") -> Dict[str, Any]:
    return {"level": level, "message": message, "where": where or {}, "fix": fix}


def check_project(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Everything the studio can tell is wrong without asking a model.

    These run on every save, which is what makes the AI advice worth reading:
    the model is never asked to spot a short circuit that arithmetic already
    found, so its attention goes to the parts arithmetic cannot judge.
    """
    findings: List[Dict[str, Any]] = []
    parts = {p["id"]: p for p in project.get("parts", [])}
    placements = {p["id"]: p for p in project.get("placements", [])}
    space = _clean_space(project.get("space"))

    # 1. Does every piece fit inside the space, and is any of it under the plate?
    boxes: Dict[str, Dict[str, List[float]]] = {}
    for placement in project.get("placements", []):
        box = placement_box(project, placement)
        if box is None:
            continue
        boxes[placement["id"]] = box
        name = placement.get("name") or parts.get(placement["part_id"], {}).get("name", "A piece")
        limits = (space["width"] / 2, None, space["depth"] / 2)
        if box["min"][0] < -limits[0] - 0.01 or box["max"][0] > limits[0] + 0.01 \
                or box["min"][2] < -limits[2] - 0.01 or box["max"][2] > limits[2] + 0.01 \
                or box["max"][1] > space["height"] + 0.01:
            findings.append(_finding(
                "error", f"{name} sticks out of the build space.",
                {"kind": "placement", "id": placement["id"]},
                f"Move it back inside {space['width']:.0f} x {space['depth']:.0f} x {space['height']:.0f} mm, or make the space bigger.",
            ))
        elif box["min"][1] < -0.5:
            findings.append(_finding(
                "warn", f"{name} hangs below the base plate.",
                {"kind": "placement", "id": placement["id"]},
                "Raise it so its lowest point is at y = 0.",
            ))

    # 2. Pieces occupying the same space. Bolted stacks are supposed to touch,
    #    so a joint between the two turns this into a note instead of a warning.
    joined = {frozenset((j["a"], j["b"])) for j in project.get("joints", [])}
    ids = list(boxes)
    for index, first in enumerate(ids):
        for second in ids[index + 1:]:
            depth = _overlap(boxes[first], boxes[second])
            if depth <= 0:
                continue
            level = "info" if frozenset((first, second)) in joined else "warn"
            name_a = placements[first].get("name") or "A piece"
            name_b = placements[second].get("name") or "another piece"
            findings.append(_finding(
                level,
                f"{name_a} and {name_b} overlap by {depth:.1f} mm."
                + (" They are joined, so this may be intentional." if level == "info" else ""),
                {"kind": "placement", "id": first},
                "Move one of them, or add a joint if they really do bolt together.",
            ))

    # 3. Circuit rules, per net.
    supplies: List[Tuple[str, float]] = []
    for net in project.get("nets", []):
        pins: List[Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]] = []
        for point in net["points"]:
            placement = placements.get(point["placement"])
            part = parts.get(placement["part_id"]) if placement else None
            pin = next((p for p in (part or {}).get("pins", []) if p["id"] == point["pin"]), None)
            if placement and part and pin:
                pins.append((placement, part, pin))
        if len(pins) < 2:
            findings.append(_finding(
                "warn", f"Net {net['name']} only reaches one pin, so nothing is connected yet.",
                {"kind": "net", "id": net["id"]}, "Connect a second pin, or delete the net."))
            continue

        drivers = [(pl, pin) for pl, _part, pin in pins if pin["direction"] == "out"]
        if len(drivers) > 1:
            names = ", ".join(f"{pl.get('name', 'piece')} {pin['name']}" for pl, pin in drivers[:4])
            findings.append(_finding(
                "error", f"Net {net['name']} has {len(drivers)} outputs driving it ({names}).",
                {"kind": "net", "id": net["id"]},
                "Only one thing may drive a wire. Make the others inputs, or split the net."))

        kinds = {pin["kind"] for _pl, _part, pin in pins}
        if "gnd" in kinds and "power" in kinds:
            findings.append(_finding(
                "error", f"Net {net['name']} joins a power pin to a ground pin - that is a short.",
                {"kind": "net", "id": net["id"]}, "Disconnect one of them."))

        voltages = {round(pin["voltage"], 2) for _pl, _part, pin in pins if pin["voltage"] > 0}
        if len(voltages) > 1:
            listed = ", ".join(f"{v:g} V" for v in sorted(voltages))
            findings.append(_finding(
                "error" if max(voltages) - min(voltages) > 1.5 else "warn",
                f"Net {net['name']} mixes {listed}.",
                {"kind": "net", "id": net["id"]},
                "Put a level shifter or a regulator between them."))

        if net["kind"] in ("power", "gnd"):
            supply = sum(float(part.get("specs", {}).get("supply_ma", 0) or 0)
                         for _pl, part, pin in pins if pin["direction"] in ("out", "power"))
            draw = sum(float(part.get("specs", {}).get("draw_ma", 0) or 0)
                       for _pl, part, pin in pins if pin["direction"] in ("in", "power", "bidir"))
            if supply > 0:
                supplies.append((net["id"], supply))
                if draw > supply:
                    findings.append(_finding(
                        "error", f"Net {net['name']} carries {draw:.0f} mA of load on a {supply:.0f} mA supply.",
                        {"kind": "net", "id": net["id"]},
                        "Use a bigger supply, or move something onto its own rail."))
                elif draw > supply * 0.8:
                    findings.append(_finding(
                        "warn", f"Net {net['name']} is at {draw / supply * 100:.0f}% of its supply ({draw:.0f} of {supply:.0f} mA).",
                        {"kind": "net", "id": net["id"]},
                        "Leave headroom for start-up surges - motors and drives pull several times their running current."))

    # 4. Pins that a part cannot work without, left floating.
    wired = {(pt["placement"], pt["pin"]) for net in project.get("nets", []) for pt in net["points"]}
    for placement in project.get("placements", []):
        part = parts.get(placement["part_id"])
        if not part:
            continue
        missing = [pin["name"] for pin in part.get("pins", [])
                   if pin.get("required") and (placement["id"], pin["id"]) not in wired]
        if missing:
            listed = ", ".join(missing[:4]) + (f" and {len(missing) - 4} more" if len(missing) > 4 else "")
            findings.append(_finding(
                "warn", f"{placement.get('name') or part['name']} still needs {listed} connected.",
                {"kind": "placement", "id": placement["id"]},
                "Wire it in the Circuit panel, or clear the required flag on that pin."))

    # 5. Whole-build sanity.
    electronic = [p for p in project.get("placements", [])
                  if parts.get(p["part_id"], {}).get("kind") == "electronic"]
    if electronic and not supplies:
        findings.append(_finding(
            "info", "Nothing in this build supplies power yet.", {},
            "Add a supply or a battery from the catalog and wire it to a power pin."))
    for part in project.get("parts", []):
        size = part_bounds(part)["size"]
        if size[0] > space["width"] or size[1] > space["height"] or size[2] > space["depth"]:
            findings.append(_finding(
                "warn", f"{part['name']} is {size[0]:.0f} x {size[2]:.0f} x {size[1]:.0f} mm and will not fit the space as one piece.",
                {"kind": "part", "id": part["id"]},
                "Split it, or raise the build space in the project settings."))

    order = {"error": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda f: order.get(f["level"], 3))
    return findings[:80]


# --- what it costs and what it prints -----------------------------------------

#: Grams per cm3, for the filament estimate. Nominal densities.
_DENSITY = {"pla": 1.24, "petg": 1.27, "abs": 1.04, "asa": 1.07, "tpu": 1.21, "nylon": 1.14,
            "resin": 1.10, "aluminium": 2.70, "brass": 8.50, "steel": 7.85}


def _density_for(material: str) -> Tuple[float, str]:
    text = (material or "").lower()
    for key, value in _DENSITY.items():
        if key in text:
            return value, key
    return _DENSITY["pla"], "pla"


def bom(project: Dict[str, Any]) -> Dict[str, Any]:
    """What to buy and what to print, with a total where prices are known."""
    counts: Dict[str, int] = {}
    for placement in project.get("placements", []):
        counts[placement["part_id"]] = counts.get(placement["part_id"], 0) + 1

    lines: List[Dict[str, Any]] = []
    total = 0.0
    unpriced = 0
    for part in project.get("parts", []):
        quantity = counts.get(part["id"], 0)
        price = float(part.get("specs", {}).get("price_usd", 0) or 0)
        printable = part.get("source") != "catalog" and part["kind"] in ("mechanical", "enclosure", "fastener")
        volume_cm3 = part_volume(part) / 1000.0
        density, material_key = _density_for(part.get("material", ""))
        line = {
            "part_id": part["id"],
            "name": part["name"],
            "kind": part["kind"],
            "quantity": quantity,
            "unit_price": price,
            "line_price": round(price * quantity, 2) if price else 0.0,
            "buy_or_print": "print" if printable else "buy",
            "material": part.get("material", "") or (material_key.upper() if printable else ""),
            "volume_cm3": round(volume_cm3, 2),
            "grams": round(volume_cm3 * density, 1) if printable else 0.0,
            "catalog_id": part.get("catalog_id", ""),
        }
        if quantity and price:
            total += price * quantity
        elif quantity and not printable:
            unpriced += 1
        lines.append(line)

    lines.sort(key=lambda line: (line["buy_or_print"], -line["quantity"], line["name"]))
    grams = sum(line["grams"] * max(line["quantity"], 1) for line in lines if line["buy_or_print"] == "print")
    return {
        "lines": lines,
        "total_usd": round(total, 2),
        "unpriced": unpriced,
        "print_grams": round(grams, 1),
        "note": "Prices are the catalog figures entered with each part, not a live quote.",
    }


def print_report(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Per printable part: does it fit the plate, how much material, what to watch.

    Deliberately short on advice the geometry cannot support. It does not claim
    to know where supports go - it says where the part is tall and thin, which
    is the thing a bounding box can honestly tell you.
    """
    space = _clean_space(project.get("space"))
    rows = []
    for part in project.get("parts", []):
        if part.get("source") == "catalog" or part["kind"] not in ("mechanical", "enclosure", "fastener"):
            continue
        bounds = part_bounds(part)
        size = bounds["size"]
        volume_cm3 = part_volume(part) / 1000.0
        density, material_key = _density_for(part.get("material", ""))
        notes: List[str] = []
        if size[0] > space["width"] or size[2] > space["depth"] or size[1] > space["height"]:
            notes.append("Too big for the build space as one piece - split it or print it at an angle.")
        footprint = max(size[0], size[2])
        if footprint > 0 and size[1] > footprint * 3:
            notes.append("Tall and narrow: print it lying down or add a brim, or it will be knocked over.")
        thin = [f for f in part.get("features", [])
                if f["op"] == "add" and min(f["size"].get("h", 99), f["size"].get("w", 99), f["size"].get("d", 99)) < 0.8]
        if thin:
            notes.append(f"{len(thin)} feature(s) are under 0.8 mm thick - thinner than two perimeters at 0.4 mm.")
        if part.get("shell"):
            notes.append(f"Hollowed to a {part['shell']['thickness']:.1f} mm wall.")
        rows.append({
            "part_id": part["id"],
            "name": part["name"],
            "size_mm": [round(v, 1) for v in size],
            "fits": size[0] <= space["width"] and size[2] <= space["depth"] and size[1] <= space["height"],
            "volume_cm3": round(volume_cm3, 2),
            "grams": round(volume_cm3 * density, 1),
            "material": part.get("material", "") or material_key.upper(),
            "notes": notes,
            "estimate": "Volume is a rough estimate: overlapping shapes are counted once each.",
        })
    return rows


# --- the tutorial -------------------------------------------------------------
#
# "make sure each part is highlighted, similar to a tutorial": a tutorial is a
# list of steps, each pointing at one thing in the scene. The viewport lights
# that thing and dims the rest, so reading the step and seeing the part are the
# same action.


def clean_tutorial(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    steps: List[Dict[str, Any]] = []
    for item in (raw.get("steps") or [])[: MAX_STEPS * 2]:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title"), 120)
        body = _text(item.get("body") or item.get("text"), 1500)
        if not title and not body:
            continue
        focus = item.get("focus") if isinstance(item.get("focus"), dict) else {}
        step: Dict[str, Any] = {
            "id": _text(item.get("id"), 32) or _new_id("s"),
            "title": title or "Step",
            "body": body,
            "focus": {
                "kind": _one_of(focus.get("kind"), ("part", "placement", "net", "pin", "feature", "none"), "none"),
                "id": _text(focus.get("id"), 32),
                "part_id": _text(focus.get("part_id"), 32),
            },
            "tips": [_text(t, 300) for t in (item.get("tips") or [])[:5] if _text(t, 300)],
            "warning": _text(item.get("warning"), 400),
        }
        steps.append(step)
        if len(steps) >= MAX_STEPS:
            break
    if not steps:
        return None
    return {
        "title": _text(raw.get("title"), 120) or "How this goes together",
        "intro": _text(raw.get("intro"), 1200),
        "steps": steps,
        "source": _one_of(raw.get("source"), ("ai", "owner"), "ai"),
        "model": _text(raw.get("model"), 80),
        "made_at": time.time(),
    }


def set_tutorial(project_id: str, raw: Any) -> Dict[str, Any]:
    project = project_or_error(project_id)
    project["tutorial"] = clean_tutorial(raw)
    return _save_project(project)


def clean_comparison(raw: Any) -> Optional[Dict[str, Any]]:
    """Pi vs Arduino vs Jetson, as data the UI renders rather than prose."""
    if not isinstance(raw, dict):
        return None
    options: List[Dict[str, Any]] = []
    for item in (raw.get("options") or [])[:6]:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"), 80)
        if not name:
            continue
        options.append({
            "id": _text(item.get("id"), 40) or _new_id("o"),
            "name": name,
            "catalog_id": _text(item.get("catalog_id"), 60),
            "summary": _text(item.get("summary"), 800),
            "price_usd": _num(item.get("price_usd"), 0.0, 0.0, 100000.0),
            "pros": [_text(p, 200) for p in (item.get("pros") or [])[:6] if _text(p, 200)],
            "cons": [_text(c, 200) for c in (item.get("cons") or [])[:6] if _text(c, 200)],
            "specs": _scalars(item.get("specs")),
            "score": _num(item.get("score"), 0.0, 0.0, 10.0),
        })
    if len(options) < 2:
        return None
    return {
        "question": _text(raw.get("question"), 400),
        "options": options,
        "recommendation": _text(raw.get("recommendation"), 60),
        "because": _text(raw.get("because"), 1200),
        "model": _text(raw.get("model"), 80),
        "made_at": time.time(),
    }


def set_comparison(project_id: str, raw: Any) -> Dict[str, Any]:
    project = project_or_error(project_id)
    project["comparison"] = clean_comparison(raw)
    return _save_project(project)


# --- what the model is shown --------------------------------------------------


def describe(project: Dict[str, Any], *, limit: int = 6000) -> str:
    """A compact, honest picture of the build for a model prompt.

    Feature trees are summarised rather than dumped: a model asked to comment
    on a design does not need every fillet radius, and the token budget is
    better spent on the pins and the wiring, which is where the mistakes are.
    """
    parts = {p["id"]: p for p in project.get("parts", [])}
    lines = [f"Build: {project.get('name', 'Untitled')}"]
    if project.get("goal"):
        lines.append(f"Goal: {project['goal']}")
    space = _clean_space(project.get("space"))
    lines.append(f"Build space: {space['width']:.0f} x {space['depth']:.0f} x {space['height']:.0f} mm (X, Z, Y up).")

    lines.append(f"\nParts ({len(project.get('parts', []))}):")
    for part in project.get("parts", []):
        size = part_bounds(part)["size"]
        pins = ", ".join(f"{p['name']} [{p['kind']}{'' if not p['voltage'] else f' {p['voltage']:g}V'}]"
                         for p in part.get("pins", [])[:14])
        lines.append(
            f"- {part['name']} (id {part['id']}, {part['kind']}, {size[0]:.0f} x {size[2]:.0f} x {size[1]:.0f} mm, "
            f"{len(part.get('features', []))} features){': ' + part['summary'] if part.get('summary') else ''}"
        )
        if pins:
            lines.append(f"    pins: {pins}{' ...' if len(part.get('pins', [])) > 14 else ''}")
        if part.get("specs"):
            lines.append("    specs: " + ", ".join(f"{k}={v}" for k, v in list(part["specs"].items())[:8]))

    lines.append(f"\nIn the space ({len(project.get('placements', []))} pieces):")
    for placement in project.get("placements", [])[:60]:
        part = parts.get(placement["part_id"], {})
        at = placement["at"]
        lines.append(f"- {placement.get('name') or part.get('name', 'piece')} (id {placement['id']}, part {placement['part_id']}) "
                     f"at ({at[0]:.0f}, {at[1]:.0f}, {at[2]:.0f})")

    lines.append(f"\nWiring ({len(project.get('nets', []))} nets):")
    for net in project.get("nets", [])[:80]:
        ends = []
        for point in net["points"]:
            placement = next((p for p in project["placements"] if p["id"] == point["placement"]), None)
            part = parts.get(placement["part_id"]) if placement else None
            pin = next((p for p in (part or {}).get("pins", []) if p["id"] == point["pin"]), None)
            if placement and pin:
                ends.append(f"{placement.get('name') or part['name']}.{pin['name']}")
        lines.append(f"- {net['name']} [{net['kind']}]: " + " = ".join(ends))

    findings = check_project(project)
    if findings:
        lines.append("\nChecks already found (do not repeat these, build on them):")
        for finding in findings[:12]:
            lines.append(f"- {finding['level']}: {finding['message']}")

    text = "\n".join(lines)
    return text[:limit]


def snapshot(project: Dict[str, Any]) -> Dict[str, Any]:
    """The whole project plus everything derived from it, in one response.

    One round trip: the studio opens with its checks, bill of materials and
    print report already in hand, instead of three more requests after paint.
    """
    return {
        "project": project,
        "checks": check_project(project),
        "bom": bom(project),
        "printing": print_report(project),
        "bounds": {p["id"]: placement_box(project, p) for p in project.get("placements", [])},
    }
