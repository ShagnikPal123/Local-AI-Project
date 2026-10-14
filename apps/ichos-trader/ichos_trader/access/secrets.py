"""Saved keys: environment variables first, then ``data/secrets.json``. Never sent back whole.

The data folder is gitignored, so a key typed into the Connectors page can never end up in a
commit. A cloud host should use environment variables instead, which win over the file. Anything
shown in the browser goes through ``masked`` (the last 4 characters at most), so a viewer, or a
screenshot, never carries a usable key.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

from .. import store

FILE = "secrets"


def env_name(name: str) -> str:
    return "ICHOS_" + name.upper().replace(".", "_").replace("-", "_")


def get(name: str) -> Optional[str]:
    return os.environ.get(env_name(name)) or store.read(FILE).get(name) or None


def put(name: str, value: str) -> None:
    value = (value or "").strip()
    if not value:
        return
    store.update(FILE, dict, lambda data: data.__setitem__(name, value))
    try:
        os.chmod(store.path_for(FILE), 0o600)  # only the owner's account can read it
    except OSError:
        pass


def forget(name: str) -> None:
    store.update(FILE, dict, lambda data: data.pop(name, None))


def masked(name: str) -> Dict[str, str]:
    """``{"from": "env"|"file", "last4": "…abcd"}``, or ``{}`` when the key is not set."""
    value = get(name)
    if not value:
        return {}
    return {"from": "env" if os.environ.get(env_name(name)) else "file",
            "last4": "…" + value[-4:] if len(value) >= 12 else "…"}
