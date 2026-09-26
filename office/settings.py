"""The handful of choices the owner makes once, kept beside the office library.

Stored at ``offices/.settings.json`` — inside the library root (so a portable copy of the offices folder carries
its own settings) and hidden from the lobby, which skips dot-files.
"""

from __future__ import annotations

import threading
from typing import Any, Dict

from office import library

FILE = ".settings.json"

DEFAULTS: Dict[str, Any] = {
    # "ask" = the consent sheet every time an office starts work; "always" = pause without asking;
    # "never" = never pause Nyx's background work.
    "focus_mode": "ask",
    "allow_web": True,
    # 0 = let the machine decide (casting.capacity).
    "max_agents": 0,
    # The staffing animation: desks appearing one after another as the office is built in front of the owner.
    "animate": True,
    "keep_open_offices": 3,
}

_CHOICES = {"focus_mode": ("ask", "always", "never")}
_lock = threading.RLock()


def load() -> Dict[str, Any]:
    raw = library._read_json(library.root() / FILE)
    settings = dict(DEFAULTS)
    for key, value in (raw or {}).items():
        if key in settings:
            settings[key] = value
    return settings


def save(changes: Dict[str, Any]) -> Dict[str, Any]:
    """Apply what is valid and return the whole settings dict. Unknown keys are ignored, never an error."""
    with _lock:
        settings = load()
        for key, value in (changes or {}).items():
            if key not in DEFAULTS:
                continue
            default = DEFAULTS[key]
            try:
                if key in _CHOICES:
                    text = str(value).strip().lower()
                    settings[key] = text if text in _CHOICES[key] else settings[key]
                elif isinstance(default, bool):
                    settings[key] = bool(value)
                elif isinstance(default, int):
                    settings[key] = max(0, min(400, int(value)))
                else:
                    settings[key] = value
            except (TypeError, ValueError):
                continue
        library.write_json(library.root() / FILE, settings)
        return settings
