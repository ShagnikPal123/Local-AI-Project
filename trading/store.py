"""Small JSON stores for trading state under data/trading/, written atomically."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable, Dict

from paths import atomic_replace, data_path

_LOCK = threading.RLock()


def folder() -> Path:
    path = data_path("trading")
    path.mkdir(parents=True, exist_ok=True)
    return path


def read(name: str, default: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    with _LOCK:
        try:
            data = json.loads((folder() / f"{name}.json").read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
        return default()


def write(name: str, data: Dict[str, Any]) -> None:
    with _LOCK:
        target = folder() / f"{name}.json"
        temp = target.with_suffix(".json.tmp")
        temp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        atomic_replace(temp, target)


def update(name: str, default: Callable[[], Dict[str, Any]], change: Callable[[Dict[str, Any]], Any]) -> Any:
    """Read, change and write one store under the lock; returns what ``change`` returns."""
    with _LOCK:
        data = read(name, default)
        result = change(data)
        write(name, data)
        return result
