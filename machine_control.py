"""Permission-gated machine control (ROADMAP V1-V8).

The highest-risk surface in the product. `connectors/system_control.py` and
friends can already read the clipboard, take screenshots, list processes and open
URLs; this module decides *whether they may*, and records that they did.

Four rules, in order of importance:

1. **Deny by default.** No capability is available until it is explicitly
   granted. A grant names one capability, optionally narrowed to a scope, and
   expires.
2. **Destructive actions need confirmation even when granted.** A standing grant
   to write files is not consent to delete a directory. Irreversibility is a
   separate question from permission, and conflating them is how an agent with a
   reasonable grant does something unreasonable.
3. **Everything privileged is logged**, allowed or refused. An audit trail that
   only records successes cannot answer "what did it try to do".
4. **There is always a kill switch.** `revoke_all()` drops every grant
   immediately, and nothing can re-grant on the agent's own initiative.
"""

from __future__ import annotations

import fnmatch
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Capability(Enum):
    """What the agent may reach. Deliberately coarse — a long list of narrow
    capabilities reads as safer while being harder to reason about."""

    FILES_READ = "files_read"
    FILES_WRITE = "files_write"
    DESKTOP = "desktop"       # clipboard, screenshots, lock
    BROWSER = "browser"       # opening URLs, browser automation
    PROCESS = "process"       # listing and inspecting processes
    APPS = "apps"             # launching applications


# Actions that cannot be undone. These require confirmation on every call,
# regardless of any standing grant.
DESTRUCTIVE_ACTIONS = frozenset({
    "delete", "delete_file", "delete_folder", "remove", "rmtree",
    "overwrite", "format", "kill_process", "shutdown", "restart",
    "uninstall", "purge", "truncate",
})

# Never reachable, granted or not. A capability the user cannot switch on is
# stronger than one they can, and these have no legitimate use from an assistant.
FORBIDDEN_TARGETS = (
    "*/System32/config/*", "*/Windows/System32/*",
    "*/.ssh/*", "*/.aws/credentials", "*/.gnupg/*",
    "*.env.local", "*auth.json", "*/etc/shadow", "*/etc/passwd",
)

_DEFAULT_TTL_SECONDS = 60 * 60  # one hour


class MachineControlError(Exception):
    """Raised when an action is refused."""


class ConfirmationRequired(MachineControlError):
    """Raised when an action needs explicit confirmation before proceeding."""


@dataclass
class Grant:
    capability: Capability
    # Glob narrowing the grant, e.g. "C:/Users/shagn/Projects/*". Empty means
    # the whole capability, which is deliberately harder to read as safe.
    scope: str = ""
    granted_by: str = ""
    granted_at: float = field(default_factory=time.time)
    expires_at: float = 0.0

    def is_valid(self) -> bool:
        return time.time() < self.expires_at

    def covers(self, target: str) -> bool:
        if not self.is_valid():
            return False
        if not self.scope:
            return True
        return fnmatch.fnmatch((target or "").replace("\\", "/"), self.scope.replace("\\", "/"))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "capability": self.capability.value,
            "scope": self.scope or "(everything)",
            "granted_by": self.granted_by,
            "granted_at": self.granted_at,
            "expires_at": self.expires_at,
            "expires_in_seconds": max(0, round(self.expires_at - time.time())),
            "valid": self.is_valid(),
        }


@dataclass
class AuditEntry:
    entry_id: str
    capability: str
    action: str
    target: str
    allowed: bool
    reason: str
    actor: str
    at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.entry_id,
            "capability": self.capability,
            "action": self.action,
            "target": self.target,
            "allowed": self.allowed,
            "reason": self.reason,
            "actor": self.actor,
            "at": self.at,
            "time": time.strftime("%H:%M:%S", time.localtime(self.at)),
        }


class MachineControl:
    """Holds grants, decides on actions, and records what happened."""

    _MAX_AUDIT = 500

    def __init__(self) -> None:
        self._grants: Dict[Capability, Grant] = {}
        self._audit: List[AuditEntry] = []
        self._lock = threading.Lock()

    # --- grants (V1, V5, V8) ------------------------------------------------

    def grant(
        self,
        capability: Capability,
        scope: str = "",
        granted_by: str = "",
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> Grant:
        """Grant one capability, optionally scoped, always expiring.

        Grants expire because a permission the user forgot they gave is a
        permission they did not really give.
        """
        if ttl_seconds <= 0:
            raise MachineControlError("A grant must have a positive lifetime.")

        entry = Grant(
            capability=capability,
            scope=(scope or "").strip(),
            granted_by=granted_by,
            expires_at=time.time() + ttl_seconds,
        )
        with self._lock:
            self._grants[capability] = entry
        self._record(capability.value, "grant", entry.scope or "(everything)",
                     True, f"granted for {ttl_seconds}s", granted_by)
        return entry

    def revoke(self, capability: Capability, actor: str = "") -> bool:
        with self._lock:
            existed = self._grants.pop(capability, None) is not None
        self._record(capability.value, "revoke", "", existed,
                     "revoked" if existed else "no such grant", actor)
        return existed

    def revoke_all(self, actor: str = "") -> int:
        """The kill switch (V8). Drops every grant immediately."""
        with self._lock:
            count = len(self._grants)
            self._grants.clear()
        self._record("*", "revoke_all", "", True, f"{count} grants dropped", actor)
        return count

    def active_grants(self) -> List[Dict[str, Any]]:
        with self._lock:
            grants = list(self._grants.values())
        return [g.as_dict() for g in grants if g.is_valid()]

    # --- the decision (V2-V7) -----------------------------------------------

    def check(
        self,
        capability: Capability,
        action: str,
        target: str = "",
        confirmed: bool = False,
        actor: str = "",
    ) -> None:
        """Authorise one action, or raise.

        Order matters: forbidden targets are refused before anything else, so a
        grant can never open one. Confirmation is checked after the grant, so the
        user is not asked to confirm something they were never allowed to do.
        """
        normalised = (target or "").replace("\\", "/")

        for pattern in FORBIDDEN_TARGETS:
            if fnmatch.fnmatch(normalised, pattern):
                self._record(capability.value, action, target, False,
                             "target is permanently off limits", actor)
                raise MachineControlError(
                    f"{target} is off limits — this path cannot be reached even with a grant."
                )

        with self._lock:
            grant = self._grants.get(capability)

        if grant is None or not grant.is_valid():
            reason = "no grant" if grant is None else "grant expired"
            self._record(capability.value, action, target, False, reason, actor)
            raise MachineControlError(
                f"{capability.value} is not granted. Ask the user to enable it first."
            )

        if not grant.covers(normalised):
            self._record(capability.value, action, target, False,
                         f"outside the granted scope {grant.scope}", actor)
            raise MachineControlError(
                f"{target} is outside the granted scope ({grant.scope})."
            )

        if action.lower() in DESTRUCTIVE_ACTIONS and not confirmed:
            self._record(capability.value, action, target, False,
                         "destructive, awaiting confirmation", actor)
            raise ConfirmationRequired(
                f"{action} on {target or 'this'} cannot be undone. Confirm to proceed."
            )

        self._record(capability.value, action, target, True, "allowed", actor)

    def is_allowed(self, capability: Capability, action: str = "read", target: str = "") -> bool:
        """Non-raising check, for a UI that wants to grey something out."""
        try:
            self.check(capability, action, target, confirmed=True)
            return True
        except MachineControlError:
            return False

    # --- audit (V6) ---------------------------------------------------------

    def _record(self, capability: str, action: str, target: str,
                allowed: bool, reason: str, actor: str) -> None:
        """Record an attempt. Never raises — an audit failure must not become a
        way to perform an unlogged action."""
        try:
            entry = AuditEntry(
                entry_id=uuid.uuid4().hex[:8],
                capability=capability,
                action=str(action)[:40],
                target=str(target)[:200],
                allowed=allowed,
                reason=reason,
                actor=actor,
            )
            with self._lock:
                self._audit.append(entry)
                if len(self._audit) > self._MAX_AUDIT:
                    del self._audit[: len(self._audit) - self._MAX_AUDIT]
        except Exception:  # pragma: no cover - defensive
            pass

        # Mirror refusals into the system log so they surface in the HUD.
        try:
            from event_log import info, warn

            message = f"{action} {target}".strip()[:120]
            if allowed:
                info(f"machine: {message}", source="machine")
            else:
                warn(f"machine refused: {message} ({reason})", source="machine")
        except Exception:
            pass

    def audit(self, limit: int = 100, refused_only: bool = False) -> List[Dict[str, Any]]:
        with self._lock:
            entries = list(self._audit)
        if refused_only:
            entries = [e for e in entries if not e.allowed]
        return [e.as_dict() for e in entries[-max(1, limit):]]

    def snapshot(self) -> Dict[str, Any]:
        audit = self.audit(limit=50)
        return {
            "grants": self.active_grants(),
            "capabilities": [
                {
                    "id": c.value,
                    "granted": any(g["capability"] == c.value for g in self.active_grants()),
                }
                for c in Capability
            ],
            "audit": audit,
            "refused_recently": sum(1 for e in audit if not e["allowed"]),
            "destructive_actions": sorted(DESTRUCTIVE_ACTIONS),
            "forbidden_targets": list(FORBIDDEN_TARGETS),
        }


MACHINE = MachineControl()
