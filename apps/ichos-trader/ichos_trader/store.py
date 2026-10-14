"""Small JSON files under the data folder, written so a crash can never leave half a file.

Copied in spirit from the main app's ``trading/store.py``. The difference is ``os.replace``: the
new file is written next to the old one and swapped in one step, so the practice account is always
either the old version or the new one, never a torn mix. That matters for "anti crash and stay on".
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from . import config

_LOCK = threading.RLock()

Default = Callable[[], Dict[str, Any]]


def path_for(name: str) -> Path:
    if not name or any(ch in name for ch in "/\\:") or name.startswith("."):
        raise ValueError(f"Bad store name: {name!r}")
    return config.data_dir() / f"{name}.json"


def read(name: str, default: Optional[Default] = None) -> Dict[str, Any]:
    """The saved dict, or ``default()`` when there is none yet or the file is unreadable."""
    with _LOCK:
        try:
            data = json.loads(path_for(name).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
        return default() if default else {}


def write(name: str, data: Dict[str, Any]) -> None:
    with _LOCK:
        target = path_for(name)
        temp = target.with_suffix(".json.tmp")
        temp.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(temp, target)


def update(name: str, default: Default, change: Callable[[Dict[str, Any]], Any]) -> Any:
    """Read, change and write one store under the lock; returns what ``change`` returns."""
    with _LOCK:
        data = read(name, default)
        result = change(data)
        write(name, data)
        return result
