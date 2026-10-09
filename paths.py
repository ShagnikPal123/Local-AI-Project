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

import json
import os
import re
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

# --- Accounts (local_accounts.py) --------------------------------------------------
# The owner can keep separate accounts on one PC ("user1", "NIS", …) for different things.
# An account is a folder: the stores below belong to one account, everything else (keys,
# sign-in, settings, models, tabs, skills, trading, Nyx's own training) is shared. "main"
# is the data that was here before accounts existed, so it lives where it always has.

MAIN_ACCOUNT = "main"

#: First path segment of every store that belongs to one account.
ACCOUNT_SCOPED = frozenset({
    "chats.json", "internal_chats.json", "memory.json", "custom_personality.json", "speech_patterns.json",
    "predictions.json", "notes", "slides", "brain", "learning", "uploads", "attachments", "research",
    "absorb", "data_process", "diagrams", "offices", "worlds", "sketches",
})

_ACCOUNT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


def accounts_index_path() -> Path:
    """The list of accounts and which one opens. Shared, so it is never inside an account."""
    return DATA_DIR / "accounts" / "index.json"


def _resolve_active_account() -> str:
    """The account this process works in, fixed at start: switching restarts the engine,
    because nearly every store opens its file once. NYX_ACCOUNT overrides it (tests)."""
    wanted = os.getenv("NYX_ACCOUNT", "").strip().lower()
    known: set = set()
    try:
        index = json.loads(accounts_index_path().read_text(encoding="utf-8"))
        known = {str(a.get("id")) for a in index.get("accounts", []) if isinstance(a, dict)}
        wanted = wanted or str(index.get("active") or "").strip().lower()
    except (OSError, ValueError, AttributeError):
        pass
    if wanted and wanted != MAIN_ACCOUNT and _ACCOUNT_ID.fullmatch(wanted) and (wanted in known or os.getenv("NYX_ACCOUNT")):
        return wanted
    return MAIN_ACCOUNT


#: The account whose chats, memory and files this engine reads and writes.
ACTIVE_ACCOUNT: str = _resolve_active_account()


def valid_account_id(account_id: str) -> bool:
    return account_id == MAIN_ACCOUNT or bool(_ACCOUNT_ID.fullmatch(account_id or ""))


def account_dir(account_id: str) -> Path:
    """Where one account's own stores live ("main" is the data directory itself)."""
    if account_id == MAIN_ACCOUNT:
        return DATA_DIR
    if not _ACCOUNT_ID.fullmatch(account_id or ""):
        raise ValueError(f"Not an account id: {account_id!r}")
    return DATA_DIR / "accounts" / account_id


def is_account_scoped(name: str) -> bool:
    first = name.replace("\\", "/").lstrip("/").split("/", 1)[0]
    return first in ACCOUNT_SCOPED or first.startswith("chats.backup-")


def data_path(name: str) -> Path:
    """Return the absolute path for a mutable state file.

    The parent directory is created on demand so a first run on a clean machine
    does not have to special-case a missing data directory. A store that belongs
    to one account resolves inside the running account's folder.
    """
    base = DATA_DIR
    if ACTIVE_ACCOUNT != MAIN_ACCOUNT and is_account_scoped(name):
        base = account_dir(ACTIVE_ACCOUNT)
    target = base / name
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
