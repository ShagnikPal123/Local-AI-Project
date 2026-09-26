"""What the assistant may do on this machine — decided by the owner, not by us.

The owner's instruction was explicit: "Nothing should be restricted unless User
asks for it." So every category starts at **allow**, and restriction is a choice
the owner makes per category:

``allow``  the tool runs.
``ask``    the tool pauses and an approval card appears in the chat; it runs only
           if the owner approves within the time limit.
``block``  the tool refuses and tells the model why, so it can say so plainly
           instead of pretending it tried.

Two defaults are *not* restrictions on the owner, and both are visible and
editable in the Permissions panel:

* **Protected paths.** Credential files (.env.local, .secrets.json, SSH keys,
  browser password stores) are not read into model context by default. Reading
  them would paste API keys into a third-party model provider's logs. The owner
  can clear the list.
* **Other people's accounts.** On a claimed install with invited testers, an
  invitee does not inherit the owner's machine — shell, code, computer control
  and sending email stay blocked for non-admin accounts until the owner sets
  ``accounts_inherit``. The owner's own permissions are unaffected.

This module replaces nothing in ``machine_control.py`` (the grant/audit engine for
the HTTP API); it is the policy the *assistant's tools* are held to.
"""

from __future__ import annotations

import fnmatch
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from paths import data_path

MODES = ("allow", "ask", "block")

#: Category id -> what it lets the assistant do, in the owner's terms.
CATEGORIES: Dict[str, str] = {
    "general": "Harmless reads: the time, this PC's specs, the process list.",
    "web": "Search the web and open web pages.",
    "files.read": "Read files and folders on this computer.",
    "files.write": "Create, edit, move and copy files and folders.",
    "files.delete": "Delete files and folders (to the Recycle Bin unless told otherwise).",
    "shell": "Run PowerShell and Command Prompt commands.",
    "code": "Write and run Python code.",
    "apps": "Open apps, files and links, and show notifications.",
    "windows": "List, focus, resize and close windows.",
    "computer": "See the screen and use the mouse and keyboard, with a visible cursor.",
    "system": "Volume, media keys, locking, sleep or restart, ending processes.",
    "clipboard": "Read and set the clipboard.",
    "email.read": "Read your email.",
    "email.send": "Send email on your behalf.",
    "network": "Download files and call web services.",
    "ui": "Redesign this app: theme, tabs, layout.",
    "agents": "Create agents and hand them work.",
    "memory": "Remember and forget things about you.",
    "finance": "Read your trading account and propose orders (every order still follows your trading rules).",
}

#: Categories an invited (non-admin) account does not get by default.
ACCOUNT_RESTRICTED = frozenset({
    "shell", "code", "files.write", "files.delete", "apps", "windows",
    "computer", "system", "email.send", "finance",
})

_TRUSTED_ROLES = frozenset({"local", "owner", "admin"})

#: Credential stores kept out of model context unless the owner clears them.
DEFAULT_PROTECTED_PATHS: List[str] = [
    "*.env.local",
    "*/.env",
    "*.secrets.json",
    "*/auth.json",
    "*/.ssh/*",
    "*/.aws/credentials",
    "*/.gnupg/*",
    "*.pem",
    "*/id_rsa*",
    "*/id_ed25519*",
    "*/Login Data",
    "*/Local State",
]

#: How long an "ask" waits for the owner before treating silence as a no.
APPROVAL_TIMEOUT_SECONDS = 180.0


class PermissionDenied(Exception):
    """A tool was refused. The message is written for the model to relay."""


class PermissionPolicy:
    """Persisted per-category modes plus the protected-path list."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else data_path("permissions.json")
        self._lock = threading.Lock()
        self._modes: Dict[str, str] = {category: "allow" for category in CATEGORIES}
        self._protected: List[str] = list(DEFAULT_PROTECTED_PATHS)
        self._accounts_inherit = False
        self._load()

    # --- persistence --------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        for category, mode in (raw.get("categories") or {}).items():
            if category in CATEGORIES and mode in MODES:
                self._modes[category] = mode
        if isinstance(raw.get("protected_paths"), list):
            self._protected = [str(p) for p in raw["protected_paths"] if str(p).strip()]
        self._accounts_inherit = bool(raw.get("accounts_inherit", False))

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "categories": self._modes,
                "protected_paths": self._protected,
                "accounts_inherit": self._accounts_inherit,
            }
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    # --- reads --------------------------------------------------------------

    def mode_for(self, category: str, role: str = "local") -> str:
        """The effective mode for ``category`` when ``role`` is asking."""
        with self._lock:
            mode = self._modes.get(category, "allow")
            inherit = self._accounts_inherit
        if role not in _TRUSTED_ROLES and category in ACCOUNT_RESTRICTED and not inherit:
            return "block"
        return mode

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "categories": dict(self._modes),
                "descriptions": dict(CATEGORIES),
                "modes": list(MODES),
                "protected_paths": list(self._protected),
                "accounts_inherit": self._accounts_inherit,
                "account_restricted": sorted(ACCOUNT_RESTRICTED),
            }

    def protected_patterns(self) -> List[str]:
        with self._lock:
            return list(self._protected)

    # --- writes -------------------------------------------------------------

    def update(
        self,
        categories: Optional[Dict[str, str]] = None,
        protected_paths: Optional[List[str]] = None,
        accounts_inherit: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Apply the owner's changes. Unknown categories or modes are refused."""
        with self._lock:
            for category, mode in (categories or {}).items():
                if category == "*":
                    if mode not in MODES:
                        raise ValueError(f"Unknown mode {mode!r}. Use allow, ask or block.")
                    for known in CATEGORIES:
                        self._modes[known] = mode
                    continue
                if category not in CATEGORIES:
                    raise ValueError(f"Unknown permission category {category!r}.")
                if mode not in MODES:
                    raise ValueError(f"Unknown mode {mode!r}. Use allow, ask or block.")
                self._modes[category] = mode
            if protected_paths is not None:
                self._protected = [str(p).strip() for p in protected_paths if str(p).strip()]
            if accounts_inherit is not None:
                self._accounts_inherit = bool(accounts_inherit)
            self._save()
        return self.snapshot()


POLICY = PermissionPolicy()


def is_protected_path(path: str) -> bool:
    """Whether ``path`` is on the owner's protected list (credential stores)."""
    if not path:
        return False
    try:
        normalised = str(Path(path).expanduser().resolve()).replace("\\", "/")
    except (OSError, RuntimeError, ValueError):
        normalised = str(path).replace("\\", "/")
    lowered = normalised.lower()
    for pattern in POLICY.protected_patterns():
        candidate = pattern.replace("\\", "/").lower()
        if fnmatch.fnmatch(lowered, candidate) or fnmatch.fnmatch(lowered, f"*/{candidate.lstrip('*/')}"):
            return True
    return False


# ---------------------------------------------------------------------------
# Approvals ("ask" mode)
# ---------------------------------------------------------------------------


class _Pending:
    def __init__(self, category: str, summary: str, detail: str, turn_id: str) -> None:
        self.id = uuid.uuid4().hex[:10]
        self.category = category
        self.summary = summary
        self.detail = detail
        self.turn_id = turn_id
        self.created = time.time()
        self.event = threading.Event()
        self.approved = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "summary": self.summary,
            "detail": self.detail,
            "turn_id": self.turn_id,
            "created": self.created,
        }


_pending: Dict[str, _Pending] = {}
_pending_lock = threading.Lock()


def pending_approvals() -> List[Dict[str, Any]]:
    with _pending_lock:
        return [p.as_dict() for p in _pending.values()]


def resolve_approval(approval_id: str, approve: bool) -> bool:
    """Answer a waiting approval. False when it no longer exists."""
    with _pending_lock:
        pending = _pending.get(approval_id)
    if pending is None:
        return False
    pending.approved = bool(approve)
    pending.event.set()
    return True


def require(category: str, summary: str, detail: str = "") -> None:
    """Enforce the owner's setting for one action, or raise PermissionDenied."""
    from tool_context import current

    ctx = current()
    role = ctx.role if ctx is not None else "local"
    category = category if category in CATEGORIES else "general"
    mode = POLICY.mode_for(category, role)

    if mode == "allow":
        return

    if mode == "block":
        if role not in _TRUSTED_ROLES and category in ACCOUNT_RESTRICTED:
            raise PermissionDenied(
                f"Blocked: '{category}' is not available to invited accounts on this "
                "install. The owner can enable it in Permissions."
            )
        raise PermissionDenied(
            f"Blocked: the owner has turned off '{category}' ({CATEGORIES.get(category, '')}). "
            "Tell the user it is blocked in Permissions rather than trying another way."
        )

    # mode == "ask": somebody has to be watching to answer.
    if ctx is None or ctx.sink is None:
        raise PermissionDenied(
            f"'{category}' is set to ask first, and nobody is watching this session to "
            "approve it. Ask the user to approve it in the app, or change the setting."
        )

    pending = _Pending(category, summary[:200], detail[:1500], ctx.turn_id)
    with _pending_lock:
        _pending[pending.id] = pending
    try:
        ctx.emit("approval.request", **pending.as_dict())
        try:
            from agent_events import publish_ui

            publish_ui("approval.request", **pending.as_dict())
        except Exception:
            pass

        deadline = time.monotonic() + APPROVAL_TIMEOUT_SECONDS
        while not pending.event.wait(timeout=0.5):
            if ctx.cancelled.is_set() or time.monotonic() > deadline:
                break

        approved = pending.event.is_set() and pending.approved
        ctx.emit("approval.resolved", id=pending.id, approved=approved)
        if not approved:
            reason = "declined" if pending.event.is_set() else "not answered in time"
            raise PermissionDenied(f"The user {reason} this action: {summary[:160]}")
    finally:
        with _pending_lock:
            _pending.pop(pending.id, None)
