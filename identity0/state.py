"""Identity 0's settings and the small JSON stores the rest of the package shares.

Everything lives under ``kahuna/`` (``paths.data_path``), never under ``identity0/``: in a dev
checkout DATA_DIR *is* the project folder, so ``data_path("identity0/...")`` would write into this
code package. Writes are atomic (tmp + replace) because the engine can be killed at any moment and a
half-written settings file must not switch the main brain off.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from paths import data_path

DATA_DIR_NAME = "kahuna"
_LOCK = threading.RLock()
_OVERRIDE: Optional[Path] = None  # tests point this at tmp_path

DEFAULTS: Dict[str, Any] = {
    "enabled": True,            # Big Kahuna leads every turn (head of the router chain)
    "shadow_rate": 0.25,        # share of turns that also run a second member for comparison
    "shadow_local_only": False, # True keeps shadows and judges on local models only (no API calls at all)
    "api_shadow_per_hour": 6,   # hard cap on API calls spent on shadows + judging per hour
    "judge_per_hour": 20,
    "panel_on_hard": True,      # hard requests in weak domains get helpers' notes before the lead answers
    "auto_promote": False,      # a new own-model version needs the owner's click
    "layered_mode": "off",      # "off" | "auto": AirLLM-style layer-by-layer only at MAX power (Request P)
    "train_on_chats": True,     # Safe mix (owner, 2026-09-18)
    "corpus_cap_mb": 2048,
    "dataset_cap_mb": 256,
    "experience_cap_mb": 50,
    "auto_tabs": False,         # the tab planner proposes; creating needs a click unless this is on
    "ollama_autostart": True,   # start the installed Ollama service when it is not running
    "auto_resume_training": True,  # pick an interrupted training run back up when the engine starts
    "id0_all": False,           # "ID0 + All": companion chat, background thoughts, early voice actions (S21)
}

_RANGES = {
    "shadow_rate": (0.0, 1.0), "api_shadow_per_hour": (0, 120), "judge_per_hour": (0, 240),
    "corpus_cap_mb": (16, 65536), "dataset_cap_mb": (8, 8192), "experience_cap_mb": (1, 1024),
}
_CHOICES = {"layered_mode": ("off", "auto")}


class SettingsError(ValueError):
    """A settings change that would leave Identity 0 in a state it cannot run in."""


def data_dir() -> Path:
    if _OVERRIDE is not None:
        _OVERRIDE.mkdir(parents=True, exist_ok=True)
        return _OVERRIDE
    return data_path(f"{DATA_DIR_NAME}/.keep").parent


def use_directory(path: Optional[Path]) -> None:
    """Redirect every Identity 0 store (tests, or a portable install)."""
    global _OVERRIDE
    _OVERRIDE = Path(path) if path else None


def path(name: str) -> Path:
    target = data_dir() / name
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def read_json(name: str, default: Any) -> Any:
    try:
        return json.loads(path(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(name: str, data: Any) -> None:
    target = path(name)
    tmp = target.with_name(target.name + ".tmp")
    with _LOCK:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, target)


def get_settings() -> Dict[str, Any]:
    stored = read_json("settings.json", {})
    merged = dict(DEFAULTS)
    if isinstance(stored, dict):
        merged.update({k: v for k, v in stored.items() if k in DEFAULTS})
    return merged


def _clean(key: str, value: Any) -> Any:
    default = DEFAULTS[key]
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise SettingsError(f"{key} must be true or false")
        return value
    if key in _CHOICES:
        if value not in _CHOICES[key]:
            raise SettingsError(f"{key} must be one of {', '.join(_CHOICES[key])}")
        return value
    try:
        number = float(value) if isinstance(default, float) else int(value)
    except (TypeError, ValueError) as error:
        raise SettingsError(f"{key} must be a number") from error
    low, high = _RANGES.get(key, (float("-inf"), float("inf")))
    if not low <= number <= high:
        raise SettingsError(f"{key} must be between {low} and {high}")
    return number


def update_settings(**changes: Any) -> Dict[str, Any]:
    unknown = sorted(set(changes) - set(DEFAULTS))
    if unknown:
        raise SettingsError(f"unknown setting: {', '.join(unknown)}")
    with _LOCK:
        current = get_settings()
        current.update({key: _clean(key, value) for key, value in changes.items()})
        write_json("settings.json", current)
    return current
