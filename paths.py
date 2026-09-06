"""Project-anchored filesystem paths for every persistent file.

Every store in this project used to default to a bare relative filename
(``Path("chats.json")``), which resolves against the *current working
directory*. That made the whole application silently depend on where it was
launched from: started from the parent folder, the app created a second, empty
world of ``.env.local`` / ``chats.json`` / ``memory.json`` and then reported
"no API key configured" while a perfectly good key sat one directory down. The
user-visible symptom was the assistant answering every question with the same
canned sentence, which took a long time to trace back here.

Anchoring on ``__file__`` instead of the CWD makes launch location irrelevant.

Two directories, deliberately distinct:

``PROJECT_DIR``
    Where the code lives. Read-only in a packaged install.
``DATA_DIR``
    Where mutable state lives. Same as ``PROJECT_DIR`` when running from a
    checkout, but ``%LOCALAPPDATA%/NyxIchos`` in a frozen build, because
    an installed application cannot write next to its own executable.

``NYX_DATA_DIR`` overrides the data directory, which is what lets tests and
multiple side-by-side profiles keep their state apart.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

#: Directory containing the source tree. Never used for writes in a frozen build.
PROJECT_DIR: Path = Path(__file__).resolve().parent

_APP_DIR_NAME = "NyxIchos"


def is_frozen() -> bool:
    """Return whether we are running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def _resolve_data_dir() -> Path:
    """Pick the directory for mutable state, honouring an explicit override."""
    override = os.getenv("NYX_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    if is_frozen():
        base = os.getenv("LOCALAPPDATA") or os.getenv("XDG_DATA_HOME")
        root = Path(base) if base else Path.home() / ".local" / "share"
        return (root / _APP_DIR_NAME).resolve()

    return PROJECT_DIR


#: Directory for mutable state (chats, memory, credentials, layout).
DATA_DIR: Path = _resolve_data_dir()


def data_path(name: str) -> Path:
    """Return the absolute path for a mutable state file.

    The parent directory is created on demand so a first run on a clean machine
    does not have to special-case a missing data directory.
    """
    target = DATA_DIR / name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        # A read-only or missing data directory must not stop import; the store
        # that owns this file reports the failure with its own context.
        pass
    return target


def project_path(name: str) -> Path:
    """Return the absolute path for a file shipped alongside the code."""
    return PROJECT_DIR / name


def atomic_replace(tmp: Path, target: Path, attempts: int = 5) -> None:
    """Rename ``tmp`` over ``target``, retrying briefly on Windows.

    ``os.replace`` is atomic on both platforms, but on Windows it fails with
    ``PermissionError`` (WinError 5/32) whenever anything else holds a handle to
    the target for even a moment - most often a virus scanner or the search
    indexer reacting to the file we just wrote. That surfaced as a rare, moving
    test failure: a different store would fail to save on each run.

    A failed save is not cosmetic. For ``auth.json`` it means a password change
    or a new account is silently lost, so a few short retries are worth it.
    The final attempt is allowed to raise, because a save that truly cannot
    happen must not be swallowed.
    """
    delay = 0.05
    for remaining in range(attempts - 1, -1, -1):
        try:
            tmp.replace(target)
            return
        except PermissionError:
            if remaining == 0:
                raise
            time.sleep(delay)
            delay *= 2


def env_files() -> list[Path]:
    """Return the dotenv files to load, most specific first.

    ``.env.local`` in the data directory wins so an installed build can hold
    per-machine credentials that the shipped tree knows nothing about.
    """
    candidates = [DATA_DIR / ".env.local", PROJECT_DIR / ".env.local", PROJECT_DIR / ".env"]
    seen: set[Path] = set()
    ordered: list[Path] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            ordered.append(candidate)
    return ordered
