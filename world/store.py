"""One file per world, on the owner's disk (U40).

The owner: *"This world is basically an entity and has a way to save in a persons computer similar to office (but in
this case it's just one file since it's already so large scale and can't link to multiple)."* So::

    worlds/                       ← the root (never "world/": that is the code package)
      Moon base.world             ← the whole world: gzipped compact JSON (``World.to_compact``)
      .trash/                     ← deleted worlds, kept: this app never destroys the owner's work

The agents' own files are the work the world delivered; they live in its backing office's ``work/`` folder and come
back through the Output box. Writing is atomic (write a temp file, then replace), so a crash mid-save leaves the
previous world intact.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from paths import data_path
from world.state import World

ROOT_NAME = "worlds"
SUFFIX = ".world"
TRASH = ".trash"

_lock = threading.RLock()
_root_override: Optional[Path] = None
_index: Dict[str, Any] = {"at": 0.0, "rows": {}}
_INDEX_SECONDS = 1.0

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class StoreError(ValueError):
    """Something the owner can act on: a world that is gone, a name that cannot be used."""


def use_root(path: Optional[Path]) -> None:
    """Point the store somewhere else (tests, or a portable install)."""
    global _root_override
    with _lock:
        _root_override = Path(path) if path is not None else None
        _index.update(at=0.0, rows={})


def root() -> Path:
    with _lock:
        if _root_override is not None:
            _root_override.mkdir(parents=True, exist_ok=True)
            return _root_override
    path = data_path(f"{ROOT_NAME}/.keep").parent
    path.mkdir(parents=True, exist_ok=True)
    return path


def clean_name(name: str) -> str:
    text = _BAD_CHARS.sub(" ", str(name or "")).strip().strip(".")
    text = re.sub(r"\s+", " ", text)[:60].strip() or "New world"
    if text.lower() in _RESERVED:
        text = f"{text} (world)"
    return text


def _unique_path(name: str, *, keep: Optional[Path] = None) -> Path:
    base = root()
    candidate = base / f"{name}{SUFFIX}"
    if not candidate.exists() or candidate == keep:
        return candidate
    for index in range(2, 500):
        candidate = base / f"{name} ({index}){SUFFIX}"
        if not candidate.exists() or candidate == keep:
            return candidate
    return base / f"{name} ({int(time.time())}){SUFFIX}"


def read_file(path: Path) -> Dict[str, Any]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            raw = json.load(handle)
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001 - an unreadable file is an empty one to the lobby
        return {}


def _write_file(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    with open(temp, "wb") as raw_handle:
        # mtime=0 keeps the bytes identical for identical worlds; compresslevel 6 is the sweet spot for small JSON.
        with gzip.GzipFile(fileobj=raw_handle, mode="wb", compresslevel=6, mtime=0) as handle:
            handle.write(payload)
    os.replace(temp, path)


def _card(path: Path, raw: Dict[str, Any]) -> Dict[str, Any]:
    from world import ERAS

    era = int(raw.get("era") or 0)
    run = list(raw.get("run") or []) + [0, 0, 0, 0]
    times = list(raw.get("t") or []) + [0, 0, 0]
    return {
        "id": str(raw.get("id") or ""), "name": path.stem, "path": str(path), "office_id": str(raw.get("o") or ""),
        "goal": str(raw.get("g") or "")[:300], "status": str(raw.get("st") or "idle"),
        "speed": str(raw.get("sp") or "steady"), "era": era, "era_name": ERAS[max(0, min(len(ERAS) - 1, era))],
        "population": len(raw.get("B") or []), "sectors": len(raw.get("S") or []),
        "buildings": sum(1 for b in (raw.get("U") or []) if isinstance(b, list) and len(b) > 7 and b[7] != 2),
        "projects": len(raw.get("P") or []), "game_days": float(run[3] or 0), "real_seconds": float(run[2] or 0),
        "run_until": float(run[0] or 0), "created_at": float(times[0] or 0), "updated_at": float(times[1] or 0),
        "size": path.stat().st_size if path.exists() else 0,
    }


def _scan(force: bool = False) -> Dict[str, Dict[str, Any]]:
    with _lock:
        if not force and time.time() - float(_index["at"]) < _INDEX_SECONDS:
            return dict(_index["rows"])
    rows: Dict[str, Dict[str, Any]] = {}
    for path in sorted(root().glob(f"*{SUFFIX}")):
        raw = read_file(path)
        if not raw.get("id"):
            continue
        rows[str(raw["id"])] = _card(path, raw)
    with _lock:
        _index.update(at=time.time(), rows=rows)
    return dict(rows)


def invalidate() -> None:
    with _lock:
        _index.update(at=0.0, rows={})


def worlds() -> List[Dict[str, Any]]:
    """Every world file, newest first — what the lobby shows."""
    return sorted(_scan().values(), key=lambda r: -float(r.get("updated_at") or 0))


def path_of(world_id: str) -> Path:
    rows = _scan()
    row = rows.get(world_id) or _scan(force=True).get(world_id)
    if row is None:
        raise StoreError("That world is gone. It may have been moved or deleted outside Nyx.")
    return Path(row["path"])


def load(world_id: str) -> World:
    raw = read_file(path_of(world_id))
    if not raw:
        raise StoreError("That world file could not be read.")
    world = World.from_compact(raw)
    world.name = path_of(world_id).stem
    return world


def save(world: World) -> Path:
    """Write the world to its one file (creating it on the first save)."""
    with _lock:
        try:
            path = path_of(world.id)
        except StoreError:
            path = _unique_path(clean_name(world.name))
        world.updated_at = time.time()
        _write_file(path, world.to_compact())
        world.name = path.stem
        invalidate()
        return path


def rename(world: World, new_name: str) -> Path:
    with _lock:
        old = path_of(world.id)
        target = _unique_path(clean_name(new_name), keep=old)
        if target != old:
            os.replace(old, target)
        world.name = target.stem
        invalidate()
        return target


def trash(world_id: str) -> str:
    """Move a world to ``.trash`` — never destroyed. Returns where it went."""
    with _lock:
        source = path_of(world_id)
        bin_dir = root() / TRASH
        bin_dir.mkdir(parents=True, exist_ok=True)
        target = bin_dir / f"{source.stem} {time.strftime('%Y-%m-%d %H%M%S')}{SUFFIX}"
        os.replace(source, target)
        invalidate()
        return str(target)
