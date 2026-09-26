"""Versions of Identity 0's own model and which one serves (no torch — the app reads this).

A version is a folder under ``kahuna/models/<version>/`` (config, tokenizer, weights, metrics). Training
registers it; serving it is a separate step (``promote``) so a worse model never replaces a better one
by accident. When ``auto_promote`` is off (the default) the owner clicks; the first version ever trained
may be promoted by the job that made it, since there is nothing to replace.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from identity0 import state

FILE = "models/registry.json"


class RegistryError(ValueError):
    pass


def models_dir() -> Path:
    path = state.path("models/.keep").parent
    return path


def _load() -> Dict[str, Any]:
    data = state.read_json(FILE, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("versions", [])
    data.setdefault("current", None)
    return data


def _save(data: Dict[str, Any]) -> None:
    state.write_json(FILE, data)


def next_version(kind: str = "nano") -> str:
    taken = {v["version"] for v in _load()["versions"]}
    n = 1
    while f"{kind}-v{n}" in taken:
        n += 1
    return f"{kind}-v{n}"


def register(version: str, path: Path, *, kind: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
    data = _load()
    data["versions"] = [v for v in data["versions"] if v["version"] != version]
    entry = {"version": version, "kind": kind, "path": str(path), "created": time.time(), "promoted": False,
             "params": metrics.get("params"),
             "metrics": {k: metrics[k] for k in ("held_out_perplexity", "tokens_seen", "minutes", "steps", "sft_examples")
                         if k in metrics}}
    data["versions"].append(entry)
    _save(data)
    return entry


def list_versions() -> List[Dict[str, Any]]:
    data = _load()
    return [{**v, "promoted": v["version"] == data["current"]} for v in data["versions"]]


def current() -> Optional[Dict[str, Any]]:
    data = _load()
    return next((v for v in data["versions"] if v["version"] == data["current"]), None)


def promote(version: str) -> List[Dict[str, Any]]:
    data = _load()
    if not any(v["version"] == version for v in data["versions"]):
        raise RegistryError(f"No trained version called {version}.")
    data["previous"] = data.get("current")
    data["current"] = version
    _save(data)
    return list_versions()


def rollback() -> List[Dict[str, Any]]:
    data = _load()
    if not data.get("previous"):
        raise RegistryError("There is no earlier version to go back to.")
    data["current"], data["previous"] = data["previous"], data["current"]
    _save(data)
    return list_versions()


def remove(version: str) -> List[Dict[str, Any]]:
    data = _load()
    if data.get("current") == version:
        raise RegistryError("That version is serving; promote another one first.")
    entry = next((v for v in data["versions"] if v["version"] == version), None)
    if entry is None:
        raise RegistryError(f"No trained version called {version}.")
    target = Path(entry["path"])
    if target.is_dir() and models_dir() in target.parents:
        shutil.rmtree(target, ignore_errors=True)
    data["versions"] = [v for v in data["versions"] if v["version"] != version]
    _save(data)
    return list_versions()
