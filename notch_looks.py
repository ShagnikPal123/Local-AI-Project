"""Notch looks: how the notch looks and when it opens, as a small file the owner can import, share and export.

The owner (Fixer Upper S30): "The user can import how different notches look and when it activates so the ai and the
user have a better coordination." And (Drive document 1, 1.11): "make it unique".

A look is data, never code (AGENTS.md invariant 2): a name, a handful of colours, two corner radii, the open width,
a font from a fixed list, and the activation settings the notch already has (open on hover, how long it waits, when
it folds away). Anything else in an imported file is dropped, and every value is checked before it is kept, so a
look found online cannot inject styles or scripts into the notch.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from typing import Any, Dict, List

from paths import atomic_replace, data_path

STORE = data_path("notch_looks.json")

FONTS = {"system": 'system-ui, "Segoe UI Variable Text", "Segoe UI", sans-serif',
         "rounded": '"SF Pro Rounded", "Nunito", "Segoe UI", system-ui, sans-serif',
         "mono": '"Cascadia Mono", Consolas, ui-monospace, monospace',
         "serif": '"Iowan Old Style", Georgia, "Times New Roman", serif'}
COLOR_KEYS = ("island", "card", "ink", "dim", "accent")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

#: Shipped looks. "Coucou" is the notch as built; the others take the reference images in new directions.
BUILT_IN: List[Dict[str, Any]] = [
    {"id": "coucou", "name": "Coucou", "colors": {"island": "#000000", "card": "#141518", "ink": "#F5F6F8",
     "dim": "#9398A1", "accent": "#A594FF"}, "radius": {"closed": 14, "open": 30}, "width": 640, "font": "system",
     "glow": False},
    {"id": "midnight", "name": "Midnight", "colors": {"island": "#14141F", "card": "#22222F", "ink": "#ECEBF5",
     "dim": "#8E8CA8", "accent": "#7C9CFF"}, "radius": {"closed": 16, "open": 28}, "width": 680, "font": "system",
     "glow": True},
    {"id": "ember", "name": "Ember", "colors": {"island": "#120B08", "card": "#21140F", "ink": "#FFF1E6",
     "dim": "#B39280", "accent": "#FF7A45"}, "radius": {"closed": 14, "open": 26}, "width": 640, "font": "rounded",
     "glow": True},
    {"id": "terminal", "name": "Terminal", "colors": {"island": "#050806", "card": "#0C130E", "ink": "#C8F7D2",
     "dim": "#6E9A78", "accent": "#34D399"}, "radius": {"closed": 8, "open": 14}, "width": 660, "font": "mono",
     "glow": False},
]

ACTIVATION_KEYS = {"open_on_hover": bool, "hover_delay_ms": int, "autoclose_s": int, "trio": bool}

_lock = threading.RLock()


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def clean(raw: Any) -> Dict[str, Any]:
    """A look from anywhere (an imported file, the setup page) made safe, or ValueError when nothing usable is in it."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as error:
            raise ValueError("That isn't a notch look file (not JSON).") from error
    if not isinstance(raw, dict):
        raise ValueError("That isn't a notch look file.")
    base = BUILT_IN[0]
    name = re.sub(r"[\x00-\x1f<>]", "", str(raw.get("name") or "").strip())[:40]
    if not name:
        raise ValueError("A look needs a name.")
    colors_in = raw.get("colors") if isinstance(raw.get("colors"), dict) else {}
    colors = {key: (str(colors_in.get(key)) if _HEX.match(str(colors_in.get(key) or "")) else base["colors"][key]).upper()
              for key in COLOR_KEYS}
    if not any(_HEX.match(str(colors_in.get(key) or "")) for key in COLOR_KEYS):
        raise ValueError("A look needs at least one colour like #1A1B1F.")
    radius_in = raw.get("radius") if isinstance(raw.get("radius"), dict) else {}
    look = {
        "id": re.sub(r"[^a-z0-9-]", "", str(raw.get("id") or "").lower())[:24] or f"look-{uuid.uuid4().hex[:6]}",
        "name": name,
        "colors": colors,
        "radius": {"closed": _clamp(radius_in.get("closed"), 0, 24, 14), "open": _clamp(radius_in.get("open"), 0, 40, 30)},
        "width": _clamp(raw.get("width"), 560, 760, 640),
        "font": raw.get("font") if raw.get("font") in FONTS else "system",
        "glow": bool(raw.get("glow")),
    }
    activation_in = raw.get("activation") if isinstance(raw.get("activation"), dict) else {}
    activation = {}
    for key, kind in ACTIVATION_KEYS.items():
        if key in activation_in:
            activation[key] = bool(activation_in[key]) if kind is bool else int(activation_in[key] or 0)
    if "hover_delay_ms" in activation:
        activation["hover_delay_ms"] = _clamp(activation["hover_delay_ms"], 0, 3000, 650)
    if "autoclose_s" in activation:
        activation["autoclose_s"] = _clamp(activation["autoclose_s"], 5, 600, 60)
    if activation:
        look["activation"] = activation
    return look


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    custom = []
    for raw in data.get("custom") or []:
        try:
            custom.append(clean(raw))
        except ValueError:
            continue
    return {"active": str(data.get("active") or "coucou"), "custom": custom[:20]}


def _save(state: Dict[str, Any]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    atomic_replace(tmp, STORE)


def looks() -> Dict[str, Any]:
    """Every look (built-in first) and the one in use."""
    with _lock:
        state = _load()
    every = [dict(look, built_in=True) for look in BUILT_IN] + [dict(look, built_in=False) for look in state["custom"]]
    active = next((look for look in every if look["id"] == state["active"]), every[0])
    return {"active": active, "looks": every, "fonts": FONTS}


def import_look(raw: Any) -> Dict[str, Any]:
    """Keep an imported look (a name already taken by a built-in gets its own id) and switch to it."""
    look = clean(raw)
    with _lock:
        state = _load()
        if look["id"] in {b["id"] for b in BUILT_IN} | {c["id"] for c in state["custom"]}:
            look["id"] = f"{look['id'][:17]}-{uuid.uuid4().hex[:6]}"
        if len(state["custom"]) >= 20:
            raise ValueError("Twenty imported looks is the limit; delete one first.")
        state["custom"].append(look)
        state["active"] = look["id"]
        _save(state)
    _apply_activation(look)
    return looks()


def use(look_id: str) -> Dict[str, Any]:
    """Switch looks; a look that carries activation settings brings them to the notch too."""
    every = looks()["looks"]
    look = next((l for l in every if l["id"] == look_id), None)
    if look is None:
        raise ValueError("No look with that id.")
    with _lock:
        state = _load()
        state["active"] = look_id
        _save(state)
    _apply_activation(look)
    return looks()


def remove(look_id: str) -> Dict[str, Any]:
    with _lock:
        state = _load()
        state["custom"] = [c for c in state["custom"] if c["id"] != look_id]
        if state["active"] == look_id:
            state["active"] = "coucou"
        _save(state)
    return looks()


def export(look_id: str) -> Dict[str, Any]:
    """The look as a file someone else can import (the same shape ``clean`` accepts)."""
    look = next((l for l in looks()["looks"] if l["id"] == look_id), None)
    if look is None:
        raise ValueError("No look with that id.")
    out = {k: v for k, v in look.items() if k != "built_in"}
    out["format"] = "ichos-notch-look/1"
    return out


def _apply_activation(look: Dict[str, Any]) -> None:
    """"When it activates": the notch's own open-on-hover and fold-away settings (equalize_assistant, notch part)."""
    activation = look.get("activation") or {}
    changes = {k: activation[k] for k in ("open_on_hover", "autoclose_s", "trio") if k in activation}
    if not changes:
        return
    import equalize_assistant

    notch = equalize_assistant.settings()["notch"]
    equalize_assistant.update({"notch": {**notch, **changes}})
