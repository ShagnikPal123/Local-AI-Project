"""The workspace's look, as data the assistant can change.

"Allow the AI much more control on the user for designing the AI landscape."
The theme lives here as validated tokens — colours, radius, font, density,
motion, wallpaper — and every change is broadcast on the UI event bus so open
windows restyle immediately. Like tabs and skills, it is a declarative spec: a
token can be a colour or a number from a fixed menu, never CSS or code, so an
assistant that gets creative can make things ugly but never break or inject
anything.
"""

from __future__ import annotations

import json
import re
import threading
from typing import Any, Dict, Optional

from paths import data_path

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

COLOR_TOKENS = ("accent", "accent2", "background", "surface", "nav", "text")
FONTS = ("Inter", "System", "Segoe UI", "Roboto", "Georgia", "JetBrains Mono", "Comic Neue")
DENSITIES = ("comfortable", "compact")
MOTION = ("full", "reduced", "off")
WALLPAPERS = ("none", "gradient", "orb", "aurora", "grid")

DEFAULT_THEME: Dict[str, Any] = {
    "accent": "#9184d9",
    "accent2": "#a7a1db",
    "background": "#161826",
    "surface": "#232532",
    "nav": "#12141f",
    "text": "#e9e9ed",
    "radius": 8,
    "font": "Inter",
    "density": "comfortable",
    "glass": False,
    "motion": "full",
    "wallpaper": {"type": "none", "value": ""},
}

#: Names people (and models) use for colours, mapped to palette-friendly values.
NAMED_COLORS = {
    "violet": "#9184d9", "purple": "#9b6ef3", "blue": "#5a9ce0", "sky": "#5ab8e0", "cyan": "#5ad6e0",
    "teal": "#3fbfb0", "green": "#5ac08a", "lime": "#9bd35a", "yellow": "#e0c65a", "amber": "#e0b45a",
    "orange": "#e0954a", "red": "#e07a7a", "pink": "#e07ac0", "rose": "#e0708f", "white": "#e9e9ed",
    "black": "#0b0c12", "grey": "#75798c", "gray": "#75798c", "gold": "#d4af37", "navy": "#1b2a4a",
}


class ThemeError(ValueError):
    """A theme value that is not allowed, with a message the model can relay."""


def _color(name: str, value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in NAMED_COLORS:
        return NAMED_COLORS[text]
    if _HEX_RE.match(text):
        return text
    if re.match(r"^#[0-9a-f]{3}$", text):
        return "#" + "".join(ch * 2 for ch in text[1:])
    raise ThemeError(f"{name} must be a #rrggbb colour or a colour name like {', '.join(list(NAMED_COLORS)[:6])}.")


def validate(changes: Dict[str, Any]) -> Dict[str, Any]:
    """Clean a partial theme, or raise ThemeError naming the bad field."""
    clean: Dict[str, Any] = {}
    for key, value in (changes or {}).items():
        if value is None or value == "":
            continue
        if key in COLOR_TOKENS:
            clean[key] = _color(key, value)
        elif key == "radius":
            try:
                clean[key] = max(0, min(24, int(float(value))))
            except (TypeError, ValueError) as error:
                raise ThemeError("radius must be a number from 0 to 24.") from error
        elif key == "font":
            match = next((f for f in FONTS if f.lower() == str(value).strip().lower()), None)
            if match is None:
                raise ThemeError(f"font must be one of: {', '.join(FONTS)}.")
            clean[key] = match
        elif key == "density":
            if str(value).lower() not in DENSITIES:
                raise ThemeError("density must be comfortable or compact.")
            clean[key] = str(value).lower()
        elif key == "motion":
            if str(value).lower() not in MOTION:
                raise ThemeError("motion must be full, reduced or off.")
            clean[key] = str(value).lower()
        elif key == "glass":
            clean[key] = bool(value) if not isinstance(value, str) else value.lower() in ("1", "true", "yes", "on")
        elif key == "wallpaper":
            if isinstance(value, str):
                value = {"type": value}
            kind = str((value or {}).get("type", "none")).lower()
            if kind not in WALLPAPERS:
                raise ThemeError(f"wallpaper must be one of: {', '.join(WALLPAPERS)}.")
            extra = str((value or {}).get("value", ""))[:40]
            if extra and not _HEX_RE.match(extra) and extra.lower() not in NAMED_COLORS:
                extra = ""
            clean[key] = {"type": kind, "value": NAMED_COLORS.get(extra.lower(), extra)}
        else:
            raise ThemeError(f"Unknown theme setting {key!r}.")
    return clean


class UiState:
    def __init__(self, path=None) -> None:
        self.path = path or data_path("ui_state.json")
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = {"theme": dict(DEFAULT_THEME), "history": []}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        try:
            self._state["theme"] = {**DEFAULT_THEME, **validate(raw.get("theme", {}))}
        except ThemeError:
            self._state["theme"] = dict(DEFAULT_THEME)
        self._state["history"] = [h for h in raw.get("history", []) if isinstance(h, dict)][-10:]

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        except OSError:
            pass

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {"theme": dict(self._state["theme"]), "defaults": dict(DEFAULT_THEME),
                    "fonts": list(FONTS), "wallpapers": list(WALLPAPERS), "can_undo": bool(self._state["history"])}

    def update_theme(self, changes: Dict[str, Any], broadcast: bool = True) -> Dict[str, Any]:
        clean = validate(changes)
        with self._lock:
            self._state["history"].append(dict(self._state["theme"]))
            self._state["history"] = self._state["history"][-10:]
            self._state["theme"] = {**self._state["theme"], **clean}
            theme = dict(self._state["theme"])
            self._save()
        if broadcast:
            _broadcast(theme)
        return theme

    def reset_theme(self) -> Dict[str, Any]:
        with self._lock:
            self._state["history"].append(dict(self._state["theme"]))
            self._state["theme"] = dict(DEFAULT_THEME)
            theme = dict(self._state["theme"])
            self._save()
        _broadcast(theme)
        return theme

    def undo_theme(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not self._state["history"]:
                return None
            self._state["theme"] = self._state["history"].pop()
            theme = dict(self._state["theme"])
            self._save()
        _broadcast(theme)
        return theme


def _broadcast(theme: Dict[str, Any]) -> None:
    try:
        from agent_events import publish_ui

        publish_ui("ui.theme", theme=theme)
    except Exception:
        pass


UI_STATE = UiState()
