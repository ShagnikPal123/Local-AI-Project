"""Accounts, roles, and beta invites for Nyx Ichos (ROADMAP AA1-AA5).

Security rules this module exists to enforce:

* **No credential is ever hardcoded.** There is no default password anywhere in
  this file or in seed data. The owner account is created empty and claimed by
  whoever runs the bootstrap, who chooses the secret at that moment.
* **Passwords are stored only as scrypt hashes with a per-user salt.** scrypt is
  memory-hard, so a stolen store is expensive to attack offline. The plaintext is
  never written to disk, never logged, and never returned by any function here.
* **Deny by default.** `has_permission` returns False for anything it does not
  explicitly recognise, and unknown roles get nothing.
* **Comparisons are constant-time.** Password and token checks use
  `hmac.compare_digest` so they do not leak length or prefix by timing.

Machine control (ROADMAP V) is deliberately owner-only. An account that can drive
the user's filesystem, desktop, and browser is the most dangerous object in this
product; beta testers do not get it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass, asdict, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from paths import atomic_replace, data_path

# scrypt parameters. n is the cost factor; 2**15 keeps a single hash in the tens
# of milliseconds on a modern laptop while making bulk offline cracking painful.
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SALT_BYTES = 16
# scrypt needs 128 * n * r bytes = 32 MiB at these parameters, which is exactly
# OpenSSL's default ceiling, so the call fails with "memory limit exceeded".
# Raise the ceiling rather than weakening the cost factor — the memory hardness
# is the entire point of choosing scrypt.
_SCRYPT_MAXMEM = 64 * 1024 * 1024

_SESSION_TTL_SECONDS = 60 * 60 * 12
_INVITE_TTL_SECONDS = 60 * 60 * 24 * 14

_MIN_PASSWORD_LENGTH = 12


class Role(str, Enum):
    """Roles, ordered from most to least privileged."""

    OWNER = "owner"      # Shagnik. Full control including machine access.
    ADMIN = "admin"      # Can develop features and review changes.
    BETA = "beta"        # Beta tester. Uses the app, sends feedback.
    USER = "user"        # Ordinary account.


class Permission(str, Enum):
    """Capability names checked at every privileged entry point."""

    CHAT = "chat"
    MANAGE_OWN_SETTINGS = "manage_own_settings"
    VIEW_ADMIN = "view_admin"
    REVIEW_CHANGES = "review_changes"
    PUBLISH_CHANGES = "publish_changes"
    MODIFY_BASE_AI = "modify_base_ai"
    INVITE_TESTERS = "invite_testers"
    GRANT_ADMIN = "grant_admin"
    MACHINE_CONTROL = "machine_control"


# Deny by default: a role gets exactly what is listed and nothing more.
_ROLE_PERMISSIONS: Dict[Role, frozenset[Permission]] = {
    Role.OWNER: frozenset(Permission),
    Role.ADMIN: frozenset({
        Permission.CHAT,
        Permission.MANAGE_OWN_SETTINGS,
        Permission.VIEW_ADMIN,
        Permission.REVIEW_CHANGES,
        Permission.PUBLISH_CHANGES,
        Permission.INVITE_TESTERS,
    }),
    Role.BETA: frozenset({Permission.CHAT, Permission.MANAGE_OWN_SETTINGS}),
    Role.USER: frozenset({Permission.CHAT, Permission.MANAGE_OWN_SETTINGS}),
}


class AuthError(Exception):
    """Raised for any authentication or authorisation failure."""


class UnknownAccountError(AuthError):
    """Raised when the target account does not exist.

    Split out from AuthError so the HTTP layer can answer 404 for "no such
    account" while a real permission refusal stays 403. Collapsing the two would
    make a missing user look like a forbidden one, which is the wrong signal for
    an admin trying to grant a role.
    """


class WeakPasswordError(AuthError):
    """Raised when a proposed password does not meet the minimum policy."""


@dataclass
class User:
    email: str
    role: Role
    password_hash: str = ""
    password_salt: str = ""
    google_subject: str = ""      # set when the account signs in with Google
    created_at: float = field(default_factory=time.time)
    invited_by: str = ""

    @property
    def has_password(self) -> bool:
        return bool(self.password_hash and self.password_salt)

    def public(self) -> Dict[str, Any]:
        """Serialisable view with every secret removed."""
        return {
            "email": self.email,
            "role": self.role.value,
            "created_at": self.created_at,
            "invited_by": self.invited_by,
            "auth_methods": [
                m for m, on in
                (("password", self.has_password), ("google", bool(self.google_subject)))
                if on
            ],
        }


@dataclass
class Invite:
    token: str
    role: Role
    created_by: str
    created_at: float
    expires_at: float
    email: str = ""          # optional: pin the invite to one address
    redeemed_by: str = ""

    @property
    def redeemed(self) -> bool:
        return bool(self.redeemed_by)

    def is_valid(self, now: Optional[float] = None) -> bool:
        return not self.redeemed and (now or time.time()) < self.expires_at


def hash_password(password: str, salt: Optional[bytes] = None) -> tuple[str, str]:
    """Return (hash_hex, salt_hex). The plaintext is never retained."""
    if salt is None:
        salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
        maxmem=_SCRYPT_MAXMEM,
    )
    return derived.hex(), salt.hex()


def verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
    """Constant-time password check. False on any malformed stored value."""
    if not hash_hex or not salt_hex:
        return False
    try:
        candidate, _ = hash_password(password, bytes.fromhex(salt_hex))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, hash_hex)


def check_password_policy(password: str) -> None:
    """Raise WeakPasswordError if the password is unacceptable.

    Deliberately minimal: length carries far more entropy than character-class
    rules, which mostly teach people to write Password1!.
    """
    if len(password or "") < _MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"Password must be at least {_MIN_PASSWORD_LENGTH} characters."
        )


def has_permission(role: Role, permission: Permission) -> bool:
    """Deny by default: unknown roles get nothing."""
    return permission in _ROLE_PERMISSIONS.get(role, frozenset())


class AuthStore:
    """File-backed account, session, and invite store."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else data_path("auth.json")
        self.users: Dict[str, User] = {}
        self.invites: Dict[str, Invite] = {}
        self.sessions: Dict[str, tuple[str, float]] = {}  # token -> (email, expires)
        self._load()

    # --- persistence ----------------------------------------------------------

    @staticmethod
    def _normalise(email: str) -> str:
        return (email or "").strip().lower()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt store must not take the app down; start empty and let the
            # bootstrap path recreate the owner.
            return
        for record in raw.get("users", []):
            try:
                record["role"] = Role(record["role"])
                self.users[record["email"]] = User(**record)
            except (ValueError, TypeError, KeyError):
                continue
        for record in raw.get("invites", []):
            try:
                record["role"] = Role(record["role"])
                self.invites[record["token"]] = Invite(**record)
            except (ValueError, TypeError, KeyError):
                continue

    def _save(self) -> None:
        payload = {
            "users": [asdict(u) | {"role": u.role.value} for u in self.users.values()],
            "invites": [asdict(i) | {"role": i.role.value} for i in self.invites.values()],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        # Retrying replace: on Windows a scanner holding the target for a
        # moment makes this fail, and a lost auth.json write means a lost
        # password change. See paths.atomic_replace.
        atomic_replace(tmp, self.path)
        # Sessions are deliberately in-memory only: a restart logs everyone out,
        # which is the safe default for a tool with machine access.
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass  # best-effort on filesystems without POSIX permissions

    # --- accounts -------------------------------------------------------------

    def get_user(self, email: str) -> Optional[User]:
        return self.users.get(self._normalise(email))

    def bootstrap_owner(self, email: str) -> User:
        """Create the owner account with **no** password set.

        The account cannot be logged into until `set_password` is called, so no
        credential exists in code or on disk at creation time. This is what makes
        it safe to commit and ship the bootstrap.
        """
        normalised = self._normalise(email)
        if not normalised or "@" not in normalised:
            raise AuthError("A valid email address is required.")
        existing = self.users.get(normalised)
        if existing is not None:
            return existing
        if any(u.role is Role.OWNER for u in self.users.values()):
            raise AuthError("An owner account already exists.")
        user = User(email=normalised, role=Role.OWNER)
        self.users[normalised] = user
        self._save()
        return user

    def set_password(self, email: str, password: str) -> None:
        """Set or change a password. Enforces the policy before hashing."""
        user = self.get_user(email)
        if user is None:
            raise AuthError("No such account.")
        check_password_policy(password)
        user.password_hash, user.password_salt = hash_password(password)
        self._save()

    def authenticate(self, email: str, password: str) -> str:
        """Return a session token, or raise AuthError.

        The error message never distinguishes "no such user" from "wrong
        password" — that difference is an account-enumeration oracle.
        """
        user = self.get_user(email)
        if user is None or not user.has_password:
            # Spend comparable time so absence is not detectable by timing.
            hash_password(password or "")
            raise AuthError("Invalid email or password.")
        if not verify_password(password, user.password_hash, user.password_salt):
            raise AuthError("Invalid email or password.")
        return self._issue_session(user.email)

    def authenticate_google(self, email: str, google_subject: str) -> str:
        """Sign in a verified Google identity.

        The caller must have already verified the ID token with Google. This
        function trusts its arguments, so never call it with unverified input.
        """
        normalised = self._normalise(email)
        if not normalised or not google_subject:
            raise AuthError("Google sign-in requires a verified email and subject.")
        user = self.users.get(normalised)
        if user is None:
            raise AuthError("No account for that address. Ask for an invite first.")
        if user.google_subject and not hmac.compare_digest(user.google_subject, google_subject):
            raise AuthError("Google account mismatch for that address.")
        if not user.google_subject:
            user.google_subject = google_subject
            self._save()
        return self._issue_session(user.email)

    # --- sessions -------------------------------------------------------------

    def _issue_session(self, email: str) -> str:
        token = secrets.token_urlsafe(32)
        self.sessions[token] = (email, time.time() + _SESSION_TTL_SECONDS)
        return token

    def resolve_session(self, token: str) -> Optional[User]:
        """Return the signed-in user, or None if the token is bad or expired."""
        entry = self.sessions.get(token or "")
        if entry is None:
            return None
        email, expires_at = entry
        if time.time() >= expires_at:
            self.sessions.pop(token, None)
            return None
        return self.get_user(email)

    def logout(self, token: str) -> None:
        self.sessions.pop(token or "", None)

    # --- authorisation --------------------------------------------------------

    def require(self, token: str, permission: Permission) -> User:
        """Authorise a request, or raise. Every privileged route calls this."""
        user = self.resolve_session(token)
        if user is None:
            raise AuthError("Not signed in.")
        if not has_permission(user.role, permission):
            raise AuthError(f"Your role ({user.role.value}) cannot {permission.value}.")
        return user

    def require_user(self, user: Optional[User], permission: Permission) -> User:
        """Authorise an already-resolved user, or raise.

        For call sites that have the user in hand — a FastAPI dependency has
        already validated the token — and need a second, narrower check on top.
        """
        if user is None:
            raise AuthError("Not signed in.")
        if not has_permission(user.role, permission):
            raise AuthError(f"Your role ({user.role.value}) cannot {permission.value}.")
        return user

    def grant_role_as(self, actor: Optional[User], email: str, role: Role) -> User:
        """Change an account's role for an actor that is already resolved.

        The HTTP layer authenticates first and holds a User, not a token. Before
        this existed the route re-implemented the owner rules inline and called
        the private _save(), so the same policy lived in two places and could
        drift. Both entry points now share this one body.
        """
        self.require_user(actor, Permission.GRANT_ADMIN)
        target = self.get_user(email)
        if target is None:
            raise UnknownAccountError("No such account.")
        if target.role is Role.OWNER:
            raise AuthError("The owner role cannot be changed.")
        if role is Role.OWNER:
            raise AuthError("There can only be one owner.")
        target.role = role
        self._save()
        return target

    def grant_role(self, actor_token: str, email: str, role: Role) -> User:
        """Change an account's role. Only the owner may create admins."""
        return self.grant_role_as(
            self.require(actor_token, Permission.GRANT_ADMIN), email, role
        )

    # --- invites --------------------------------------------------------------

    def mint_invite(
        self,
        actor: User,
        role: Role = Role.BETA,
        email: str = "",
        ttl_seconds: int = _INVITE_TTL_SECONDS,
    ) -> Invite:
        """Mint an invite for an already-authorised actor.

        Split out from `create_invite` so the HTTP layer, which has already
        authorised via a FastAPI dependency, does not have to re-present a token.
        The role rules are enforced here so both callers get them.
        """
        if role is Role.OWNER:
            raise AuthError("The owner cannot be invited.")
        if role is Role.ADMIN and not has_permission(actor.role, Permission.GRANT_ADMIN):
            raise AuthError("Only the owner can invite admins.")
        now = time.time()
        invite = Invite(
            token=secrets.token_urlsafe(24),
            role=role,
            created_by=actor.email,
            created_at=now,
            expires_at=now + ttl_seconds,
            email=self._normalise(email),
        )
        self.invites[invite.token] = invite
        self._save()
        return invite

    def create_invite(
        self,
        actor_token: str,
        role: Role = Role.BETA,
        email: str = "",
        ttl_seconds: int = _INVITE_TTL_SECONDS,
    ) -> Invite:
        """Mint a single-use invite token, authorising by session token."""
        actor = self.require(actor_token, Permission.INVITE_TESTERS)
        return self.mint_invite(actor, role, email, ttl_seconds)

    def redeem_invite(self, token: str, email: str, password: str = "") -> User:
        """Create an account from an invite. Single use."""
        invite = self.invites.get(token or "")
        if invite is None or not invite.is_valid():
            raise AuthError("That invite is invalid, already used, or expired.")
        normalised = self._normalise(email)
        if invite.email and invite.email != normalised:
            raise AuthError("That invite was issued to a different address.")
        if normalised in self.users:
            raise AuthError("An account already exists for that address.")
        if password:
            check_password_policy(password)
        user = User(email=normalised, role=invite.role, invited_by=invite.created_by)
        if password:
            user.password_hash, user.password_salt = hash_password(password)
        self.users[normalised] = user
        invite.redeemed_by = normalised
        self._save()
        return user

    def revoke_invite(self, actor_token: str, token: str) -> None:
        self.require(actor_token, Permission.INVITE_TESTERS)
        self.invites.pop(token, None)
        self._save()

    def list_invites(self, actor_token: str) -> List[Dict[str, Any]]:
        self.require(actor_token, Permission.INVITE_TESTERS)
        return [
            {
                "token": i.token,
                "role": i.role.value,
                "email": i.email,
                "created_by": i.created_by,
                "expires_at": i.expires_at,
                "redeemed_by": i.redeemed_by,
                "valid": i.is_valid(),
            }
            for i in self.invites.values()
        ]

    def list_users(self, actor_token: str) -> List[Dict[str, Any]]:
        self.require(actor_token, Permission.VIEW_ADMIN)
        return [u.public() for u in self.users.values()]


def invite_link(base_url: str, token: str) -> str:
    """Build the shareable redemption URL for an invite."""
    return f"{base_url.rstrip('/')}/join?invite={token}"
