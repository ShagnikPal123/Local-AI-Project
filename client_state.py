""""The user goes out of the website and comes back" — persistence for that.

Two halves:

* ``ClientCookieMiddleware`` — a pure-ASGI middleware (never
  ``BaseHTTPMiddleware``, which buffers the whole response body and would
  break Server-Sent Events streaming) that makes sure every browser carries a
  long-lived, anonymous ``nyx_client`` cookie, and exposes the id on
  ``request.state.nyx_client``.
* ``get_state``/``put_state``/``patch_state``/``forget`` — small per-device
  JSON documents keyed by that id, so a closed tab or a restarted browser
  still finds its place. When the caller is signed in (``account`` is given),
  the same account's other devices see the same *shared* baseline, with each
  device's own state layered on top — see ``get_state`` for the merge order.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import time
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any, Dict, Optional

from paths import atomic_replace, data_path

_LOG = logging.getLogger("nyx.client_state")

COOKIE_NAME = "nyx_client"
_MAX_AGE_SECONDS = 400 * 24 * 3600  # 400 days: the longest Chrome will honour
_MAX_STATE_BYTES = 256 * 1024

# What secrets.token_urlsafe(32) produces, plus enough room for a hand-typed id
# in a test. Anchored so a client-supplied cookie value can never smuggle a
# path segment ("..", "/", "\") into the filename we build from it.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


class ClientStateError(ValueError):
    """An invalid client id, an oversized document, or a non-object state."""


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


def _parse_cookie(header: str, name: str) -> str:
    if not header:
        return ""
    jar = SimpleCookie()
    try:
        jar.load(header)
    except Exception:  # noqa: BLE001 - a malformed Cookie header must not 500
        return ""
    morsel = jar.get(name)
    return morsel.value if morsel else ""


class ClientCookieMiddleware:
    """Ensures ``nyx_client`` exists; never touches the response body.

    Starlette's ``BaseHTTPMiddleware`` reads the whole response into memory to
    let middleware inspect it, which turns a Server-Sent Events stream into
    "wait for the entire turn, then get it all at once" — exactly what
    ``turn_runner.py`` exists to avoid. This middleware only ever looks at
    headers: it reads the incoming ``Cookie`` header itself (no body access
    needed) and, only when a new id had to be minted, splices one
    ``Set-Cookie`` into the outgoing ``http.response.start`` message before
    forwarding every other ASGI message untouched.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        client_id, is_new = self._resolve_client_id(scope)
        state = scope.setdefault("state", {})
        state["nyx_client"] = client_id

        if not is_new:
            await self.app(scope, receive, send)
            return

        cookie_header = self._cookie_header(client_id, scope)

        async def send_wrapper(message: Dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((b"set-cookie", cookie_header.encode("latin-1")))
                message = dict(message)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)

    @staticmethod
    def _resolve_client_id(scope: Dict[str, Any]) -> tuple[str, bool]:
        raw_headers = scope.get("headers") or []
        cookie_header = ""
        for key, value in raw_headers:
            if key == b"cookie":
                cookie_header = value.decode("latin-1")
                break
        existing = _parse_cookie(cookie_header, COOKIE_NAME)
        if existing and _ID_RE.match(existing):
            return existing, False
        return secrets.token_urlsafe(32), True

    @staticmethod
    def _cookie_header(client_id: str, scope: Dict[str, Any]) -> str:
        parts = [
            f"{COOKIE_NAME}={client_id}", "Path=/", f"Max-Age={_MAX_AGE_SECONDS}",
            "HttpOnly", "SameSite=Lax",
        ]
        # No Secure attribute on plain http localhost — the browser would
        # silently refuse to ever send the cookie back, which for a
        # local-first app on 127.0.0.1 means "cookie never works at all".
        if scope.get("scheme") == "https":
            parts.append("Secure")
        return "; ".join(parts)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _validate_id(client_id: str) -> str:
    if not client_id or not _ID_RE.match(client_id):
        raise ClientStateError("Invalid client id.")
    return client_id


def _device_path(client_id: str) -> Path:
    return data_path(f"client_state/{_validate_id(client_id)}.json")


def _account_path(account: str) -> Path:
    # Hashed rather than the raw email/id: sidesteps filesystem-invalid
    # characters entirely and avoids an account identifier sitting in a
    # filename on disk.
    digest = hashlib.blake2b(account.strip().casefold().encode("utf-8"), digest_size=16).hexdigest()
    return data_path(f"client_state/account_{digest}.json")


def _read_document(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _LOG.warning("could not read %s; treating as empty", path)
        return {}
    return data if isinstance(data, dict) else {}


def _write_document(path: Path, document: Dict[str, Any]) -> None:
    encoded = json.dumps(document, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > _MAX_STATE_BYTES:
        raise ClientStateError(f"State exceeds the {_MAX_STATE_BYTES // 1024} KB cap.")
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(encoded, encoding="utf-8")
        atomic_replace(tmp, path)
    except OSError as error:
        raise ClientStateError(f"Could not save state: {error}") from error


def _require_object(state: Any) -> Dict[str, Any]:
    if not isinstance(state, dict):
        raise ClientStateError("State must be a JSON object.")
    return state


def get_state(client_id: str, account: Optional[str] = None) -> Dict[str, Any]:
    """The account's shared baseline (if any), overlaid by this device's own state.

    Device wins on a key present in both — this device's user has, by
    definition, seen it most recently.
    """
    device = _read_document(_device_path(client_id))
    merged: Dict[str, Any] = {}
    if account:
        shared = _read_document(_account_path(account))
        merged.update(shared.get("state", {}) if isinstance(shared.get("state"), dict) else {})
    merged.update(device.get("state", {}) if isinstance(device.get("state"), dict) else {})
    return merged


def put_state(client_id: str, state: Dict[str, Any], account: Optional[str] = None) -> Dict[str, Any]:
    """Replace this device's state outright. Also folds it into the account's
    shared baseline (a plain update, not a replace) so a second browser signed
    into the same account picks it up via ``get_state``."""
    state = _require_object(state)
    device_path = _device_path(client_id)
    previous = _read_document(device_path).get("state")
    removed = set(previous) - set(state) if isinstance(previous, dict) else set()
    document = {"updated_at": time.time(), "account": account, "state": dict(state)}
    _write_document(device_path, document)

    if account:
        account_path = _account_path(account)
        shared = _read_document(account_path)
        shared_state = shared.get("state") if isinstance(shared.get("state"), dict) else {}
        # Keys this device just dropped must leave the baseline too, or get_state
        # would bring them straight back (a cleared draft reappearing).
        for key in removed:
            shared_state.pop(key, None)
        shared_state.update(state)
        _write_document(account_path, {"updated_at": time.time(), "state": shared_state})

    return get_state(client_id, account=account)


def patch_state(client_id: str, patch: Dict[str, Any], account: Optional[str] = None) -> Dict[str, Any]:
    """Shallow-merge ``patch`` into this device's state; a ``None`` value deletes that key.
    Mirrors the same patch into the account baseline when signed in."""
    patch = _require_object(patch)
    device_path = _device_path(client_id)
    document = _read_document(device_path)
    current = document.get("state") if isinstance(document.get("state"), dict) else {}
    current = _apply_patch(current, patch)
    _write_document(device_path, {"updated_at": time.time(), "account": account, "state": current})

    if account:
        account_path = _account_path(account)
        shared_doc = _read_document(account_path)
        shared_state = shared_doc.get("state") if isinstance(shared_doc.get("state"), dict) else {}
        shared_state = _apply_patch(shared_state, patch)
        _write_document(account_path, {"updated_at": time.time(), "state": shared_state})

    return get_state(client_id, account=account)


def _apply_patch(current: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(current)
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = value
    return result


def forget(client_id: str) -> None:
    """Delete this device's own state. Never touches the account baseline or
    any other device — forgetting one browser must not wipe a signed-in
    account's state everywhere it is used."""
    path = _device_path(client_id)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        _LOG.warning("could not delete %s", path)
