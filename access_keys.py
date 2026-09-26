"""Signed beta/dev access keys, and the stores behind the owner's admin console.

Nyx is local-first: every tester runs their own copy, with no shared server and
no phone-home. That rules out the usual "call our API to check the license"
model, so this module does the opposite: the owner mints a small signed token
on his own machine (Ed25519), ships the *public* half of the keypair inside
every build, and any install can verify a key completely offline. Nothing
about redemption ever needs to reach the owner's machine again.

Ed25519 was picked over anything requiring `pip install` because AGENTS.md is
explicit about not adding a dependency for this kind of thing, and the
reference algorithm (RFC 8032 section 5.1) is short enough to vendor directly
and pin down with the RFC's own test vectors (see tests/test_access_keys.py).

Every store here is a small JSON file resolved through ``paths.py`` (never a
bare relative path - see AGENTS.md section 2) and written with
``atomic_replace`` so a crash mid-write cannot corrupt the owner's key
registry. The one secret in the whole system - the 32-byte Ed25519 seed - lives
only in ``secret_store`` and is never logged, returned from a function, or
serialised into any of these files.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import secret_store
from paths import atomic_replace, data_path, project_path

# ---------------------------------------------------------------------------
# Ed25519 (RFC 8032 section 5.1) - pure Python, no dependency.
#
# This is the standard reference algorithm (Bernstein et al.): field inverses
# via Fermat's little theorem, Edwards-curve point addition, and recursive
# double-and-add scalar multiplication. It is slower than a native crypto
# library, but keys are minted and verified rarely enough (an owner minting an
# invite, an install checking a key at startup) that this is nowhere near a
# hot path. Exactness is what matters here, which is why the RFC's own test
# vectors are wired into the test suite rather than trusted by inspection.
# ---------------------------------------------------------------------------

_ED_B = 256
_ED_Q = 2**255 - 19
_ED_L = 2**252 + 27742317777372353535851937790883648493


def _ed_sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _ed_expmod(base: int, exponent: int, modulus: int) -> int:
    """Modular exponentiation by repeated squaring (recursive is fine here)."""
    if exponent == 0:
        return 1
    half = _ed_expmod(base, exponent // 2, modulus) ** 2 % modulus
    return (half * base) % modulus if exponent & 1 else half


def _ed_inv(x: int) -> int:
    """Modular inverse mod the field prime, via Fermat's little theorem."""
    return _ed_expmod(x, _ED_Q - 2, _ED_Q)


_ED_D = -121665 * _ed_inv(121666) % _ED_Q
_ED_I = _ed_expmod(2, (_ED_Q - 1) // 4, _ED_Q)


def _ed_x_recover(y: int) -> int:
    xx = (y * y - 1) * _ed_inv(_ED_D * y * y + 1)
    x = _ed_expmod(xx, (_ED_Q + 3) // 8, _ED_Q)
    if (x * x - xx) % _ED_Q != 0:
        x = (x * _ED_I) % _ED_Q
    if x % 2 != 0:
        x = _ED_Q - x
    return x


_ED_BY = 4 * _ed_inv(5)
_ED_BX = _ed_x_recover(_ED_BY)
_ED_BASE = (_ED_BX % _ED_Q, _ED_BY % _ED_Q)


def _ed_add(p: Tuple[int, int], other: Tuple[int, int]) -> Tuple[int, int]:
    x1, y1 = p
    x2, y2 = other
    x3 = (x1 * y2 + x2 * y1) * _ed_inv(1 + _ED_D * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _ed_inv(1 - _ED_D * x1 * x2 * y1 * y2)
    return (x3 % _ED_Q, y3 % _ED_Q)


def _ed_scalar_mult(p: Tuple[int, int], e: int) -> Tuple[int, int]:
    if e == 0:
        return (0, 1)
    half = _ed_scalar_mult(p, e // 2)
    half = _ed_add(half, half)
    return _ed_add(half, p) if e & 1 else half


def _ed_encode_int(y: int) -> bytes:
    return y.to_bytes(_ED_B // 8, "little")


def _ed_encode_point(point: Tuple[int, int]) -> bytes:
    x, y = point
    encoded = bytearray(y.to_bytes(_ED_B // 8, "little"))
    encoded[-1] = (encoded[-1] & 0x7F) | ((x & 1) << 7)
    return bytes(encoded)


def _ed_bit(data: bytes, i: int) -> int:
    return (data[i // 8] >> (i % 8)) & 1


def _ed_clamp_scalar(seed_hash: bytes) -> int:
    """RFC 8032's "clamping": fixes the scalar into the prime-order subgroup."""
    a = 2 ** (_ED_B - 2)
    for i in range(3, _ED_B - 2):
        a += (2**i) * _ed_bit(seed_hash, i)
    return a


def _ed_public_key(seed: bytes) -> bytes:
    h = _ed_sha512(seed)
    a = _ed_clamp_scalar(h)
    return _ed_encode_point(_ed_scalar_mult(_ED_BASE, a))


def _ed_hash_int(data: bytes) -> int:
    return int.from_bytes(_ed_sha512(data), "little")


def _ed_sign_raw(message: bytes, seed: bytes, public_key: bytes) -> bytes:
    h = _ed_sha512(seed)
    a = _ed_clamp_scalar(h)
    prefix = h[_ED_B // 8 : _ED_B // 4]
    r = _ed_hash_int(prefix + message) % _ED_L
    r_point_bytes = _ed_encode_point(_ed_scalar_mult(_ED_BASE, r))
    s = (r + _ed_hash_int(r_point_bytes + public_key + message) * a) % _ED_L
    return r_point_bytes + _ed_encode_int(s)


def _ed_is_on_curve(point: Tuple[int, int]) -> bool:
    x, y = point
    return (-x * x + y * y - 1 - _ED_D * x * x * y * y) % _ED_Q == 0


def _ed_decode_point(data: bytes) -> Tuple[int, int]:
    y = int.from_bytes(data, "little") & ((1 << (_ED_B - 1)) - 1)
    x = _ed_x_recover(y)
    if (x & 1) != _ed_bit(data, _ED_B - 1):
        x = _ED_Q - x
    point = (x, y)
    if not _ed_is_on_curve(point):
        raise ValueError("Point is not on the Ed25519 curve.")
    return point


def _ed_check_valid(signature: bytes, message: bytes, public_key: bytes) -> None:
    if len(signature) != _ED_B // 4:
        raise ValueError("Signature has the wrong length.")
    if len(public_key) != _ED_B // 8:
        raise ValueError("Public key has the wrong length.")
    r_point = _ed_decode_point(signature[: _ED_B // 8])
    a_point = _ed_decode_point(public_key)
    s = int.from_bytes(signature[_ED_B // 8 : _ED_B // 4], "little")
    h = _ed_hash_int(_ed_encode_point(r_point) + public_key + message)
    left = _ed_scalar_mult(_ED_BASE, s)
    right = _ed_add(r_point, _ed_scalar_mult(a_point, h))
    if left != right:
        raise ValueError("Signature verification failed.")


def ed25519_keypair_from_seed(seed: bytes) -> Tuple[bytes, bytes]:
    """Return ``(public_key, seed)`` for a 32-byte seed (RFC 8032 5.1.5)."""
    if len(seed) != 32:
        raise ValueError("An Ed25519 seed must be exactly 32 bytes.")
    return _ed_public_key(seed), seed


def ed25519_public_key(seed: bytes) -> bytes:
    return _ed_public_key(seed)


def ed25519_sign(message: bytes, seed: bytes) -> bytes:
    return _ed_sign_raw(message, seed, _ed_public_key(seed))


def ed25519_verify(message: bytes, signature: bytes, public_key: bytes) -> bool:
    """Never raises: any malformed input is simply an invalid signature."""
    try:
        _ed_check_valid(signature, message, public_key)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Access keys - format, minting, and verification
# ---------------------------------------------------------------------------

_KEY_PREFIX = "NYX1-"
_SIGNING_KEY_NAME = "NYX_ACCESS_SIGNING_KEY"
_VALID_ROLES = frozenset({"beta", "dev"})
_ROLE_RANK = {"beta": 1, "dev": 2}
_MAX_APPLICATIONS = 500
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccessKeyError(Exception):
    """One error type for the whole module.

    routes_access.py turns every instance into an HTTP 400 with ``str(error)``
    as the reason - which is exactly what "malformed / unknown kid / bad
    signature / expired / revoked" wants: a human-readable sentence, not a
    machine code nobody outside this file needs to branch on.
    """


def _b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A fresh copy every time - callers mutate the returned dict, and a
        # shared literal default would leak state between calls.
        return json.loads(json.dumps(default))


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    atomic_replace(tmp, path)


# --- per-store helpers (paths resolved at call time, not import time, so
# tests can monkeypatch `access_keys.data_path` / `access_keys.project_path`
# to a tmp_path and never touch a real store) --------------------------------


def _read_minted() -> Dict[str, Any]:
    return _read_json(data_path("access_minted.json"), {"minted": []})


def _write_minted(data: Dict[str, Any]) -> None:
    _write_json_atomic(data_path("access_minted.json"), data)


def _read_access() -> Dict[str, Any]:
    return _read_json(data_path("access.json"), {"keys": []})


def _write_access(data: Dict[str, Any]) -> None:
    _write_json_atomic(data_path("access.json"), data)


def _read_revoked() -> Dict[str, Any]:
    return _read_json(data_path("access_revoked.json"), {"revoked": []})


def _write_revoked(data: Dict[str, Any]) -> None:
    _write_json_atomic(data_path("access_revoked.json"), data)


def _read_applications() -> Dict[str, Any]:
    return _read_json(data_path("access_applications.json"), {"applications": []})


def _write_applications(data: Dict[str, Any]) -> None:
    _write_json_atomic(data_path("access_applications.json"), data)


def _read_flags() -> Dict[str, Any]:
    return _read_json(data_path("feature_flags.json"), {"flags": {}})


def _write_flags(data: Dict[str, Any]) -> None:
    _write_json_atomic(data_path("feature_flags.json"), data)


def _read_public_keys() -> Dict[str, Any]:
    return _read_json(project_path("access_public_keys.json"), {"keys": []})


def _write_public_keys(data: Dict[str, Any]) -> None:
    _write_json_atomic(project_path("access_public_keys.json"), data)


def _find_public_key(kid: str) -> Optional[bytes]:
    if not kid:
        return None
    for entry in _read_public_keys().get("keys", []):
        if entry.get("kid") == kid:
            try:
                return bytes.fromhex(entry["public_key"])
            except (ValueError, TypeError, KeyError):
                return None
    return None


def _register_public_key(kid: str, public_key: bytes) -> None:
    store = _read_public_keys()
    if any(entry.get("kid") == kid for entry in store.get("keys", [])):
        return
    store.setdefault("keys", []).append(
        {"kid": kid, "public_key": public_key.hex(), "created": time.time()}
    )
    _write_public_keys(store)


def _is_revoked(key_id: str) -> bool:
    if not key_id:
        return False
    if key_id in _read_revoked().get("revoked", []):
        return True
    for record in _read_minted().get("minted", []):
        if record.get("id") == key_id and record.get("revoked"):
            return True
    return False


def _kid_for(public_key: bytes) -> str:
    # Derived, not random, so ensure_signing_key() is idempotent: calling it
    # again with the same seed always names the same public-key entry rather
    # than accumulating duplicates.
    return hashlib.sha256(public_key).hexdigest()[:12]


def _load_seed() -> bytes:
    seeds = secret_store.get_keys(_SIGNING_KEY_NAME)
    if not seeds:
        raise AccessKeyError("No signing key yet - call ensure_signing_key() first.")
    return bytes.fromhex(seeds[0])


def ensure_signing_key() -> Dict[str, str]:
    """Create the Ed25519 signing key on first use, and keep it stable after.

    The seed lives only in secret_store, exactly like every provider API key
    in this project. The public half is the one thing that ever leaves this
    module: it is written into ``access_public_keys.json`` (a project-level,
    shippable file) so a packaged build carries the owner's real public key
    and every tester's install can verify a key with no network call at all.
    """
    seeds = secret_store.get_keys(_SIGNING_KEY_NAME)
    if seeds:
        seed = bytes.fromhex(seeds[0])
    else:
        seed = secrets.token_bytes(32)
        secret_store.set_keys(_SIGNING_KEY_NAME, [seed.hex()])
    public_key = _ed_public_key(seed)
    kid = _kid_for(public_key)
    _register_public_key(kid, public_key)
    return {"kid": kid, "public_key": public_key.hex()}


def mint(
    role: str,
    name: str,
    email: str = "",
    days: int = 90,
    features: Optional[List[str]] = None,
    notes: str = "",
    actor: str = "",
) -> Dict[str, Any]:
    """Mint a signed access key the owner can hand to a beta tester or developer.

    The raw key string is kept in the minted registry (alongside the metadata
    the contract asks for) so "copy invite" still works from the admin console
    after a restart. That is not a secret in the auth.py sense - it is a
    capability token like an invite link, not a provider credential - so
    storing it plainly here matches how invites already work in auth.json.
    """
    role = (role or "").strip().lower()
    if role not in _VALID_ROLES:
        raise AccessKeyError(f"Role must be 'beta' or 'dev', not {role!r}.")
    name = (name or "").strip()
    if not name:
        raise AccessKeyError("A name is required to mint an access key.")
    if len(name) > 200:
        raise AccessKeyError("Name is too long.")

    identity = ensure_signing_key()
    seed = _load_seed()

    key_id = secrets.token_hex(8)
    iat = int(time.time())
    exp = 0 if days <= 0 else iat + int(days) * 86400

    payload: Dict[str, Any] = {
        "v": 1,
        "kid": identity["kid"],
        "id": key_id,
        "role": role,
        "name": name,
        "iat": iat,
        "exp": exp,
    }
    email = (email or "").strip()
    if email:
        payload["email"] = email
    if features:
        payload["features"] = list(features)

    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = ed25519_sign(payload_bytes, seed)
    key = f"{_KEY_PREFIX}{_b64u_encode(payload_bytes)}.{_b64u_encode(signature)}"

    registry = _read_minted()
    registry.setdefault("minted", []).append({
        "id": key_id,
        "role": role,
        "name": name,
        "email": email,
        "notes": notes,
        "iat": iat,
        "exp": exp,
        "revoked": False,
        "revoked_at": None,
        "redemptions": [],
        "key": key,
    })
    _write_minted(registry)
    audit(actor, "mint", key_id, f"role={role} name={name}")

    redeem_link = f"nyx://redeem?key={key}"
    expiry_text = (
        "never expires" if exp == 0 else f"expires {time.strftime('%Y-%m-%d', time.gmtime(exp))}"
    )
    invite_text = (
        f"You're invited to Nyx Ichos as a {role} tester.\n\n"
        f"Your access key ({expiry_text}):\n{key}\n\n"
        "Paste it into Nyx's Access panel, or open this link on the machine "
        f"running Nyx:\n{redeem_link}"
    )
    return {
        "key": key,
        "id": key_id,
        "payload": payload,
        "redeem_link": redeem_link,
        "invite_text": invite_text,
    }


def verify(key: str) -> Dict[str, Any]:
    """Verify a key string and return its payload, or raise AccessKeyError.

    Deliberately checks in order malformed -> unknown kid -> bad signature ->
    expired -> revoked, so the reason reported is always the first real
    problem rather than a confusing later one (e.g. a key with an unknown kid
    should never be reported as "expired" just because its embedded exp
    happens to be in the past).
    """
    if not isinstance(key, str) or not key.startswith(_KEY_PREFIX):
        raise AccessKeyError("Malformed access key.")
    body = key[len(_KEY_PREFIX) :]
    parts = body.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise AccessKeyError("Malformed access key.")

    try:
        payload_bytes = _b64u_decode(parts[0])
        signature = _b64u_decode(parts[1])
        payload = json.loads(payload_bytes)
    except Exception as error:  # noqa: BLE001 - any decode failure is "malformed"
        raise AccessKeyError("Malformed access key.") from error
    if not isinstance(payload, dict) or not payload.get("kid") or not payload.get("id"):
        raise AccessKeyError("Malformed access key.")

    public_key = _find_public_key(str(payload["kid"]))
    if public_key is None:
        raise AccessKeyError("This key was signed by an unknown signing key.")

    if not ed25519_verify(payload_bytes, signature, public_key):
        raise AccessKeyError("This key's signature does not match its contents.")

    exp = payload.get("exp") or 0
    if exp and time.time() > exp:
        raise AccessKeyError("This access key has expired.")

    if _is_revoked(str(payload["id"])):
        raise AccessKeyError("This access key has been revoked.")

    return payload


def redeem(key: str) -> Dict[str, Any]:
    """Verify a key and record it as redeemed on this install.

    Raises AccessKeyError (unchanged from verify()) on an invalid key, so a
    caller never has to redeem() and then separately re-verify to find out
    what went wrong.
    """
    payload = verify(key)
    key_id = payload.get("id")

    store = _read_access()
    entries = store.setdefault("keys", [])
    for entry in entries:
        if entry.get("id") == key_id:
            entry.update({
                "role": payload.get("role"),
                "name": payload.get("name"),
                "email": payload.get("email", ""),
                "exp": payload.get("exp", 0),
                "key": key,
                "redeemed_at": time.time(),
            })
            break
    else:
        entries.append({
            "id": key_id,
            "role": payload.get("role"),
            "name": payload.get("name"),
            "email": payload.get("email", ""),
            "iat": payload.get("iat"),
            "exp": payload.get("exp", 0),
            "key": key,
            "redeemed_at": time.time(),
        })
    _write_access(store)

    # The only way this install can ever observe a redemption: if the key was
    # minted here too (the owner testing his own key, or a single-machine
    # dev loop), note it on the minted registry's record.
    registry = _read_minted()
    for record in registry.get("minted", []):
        if record.get("id") == key_id:
            record.setdefault("redemptions", []).append({"redeemed_at": time.time()})
            _write_minted(registry)
            break

    audit("local", "redeem", str(key_id), f"role={payload.get('role')}")
    return payload


def _features_for_level(level: str) -> Dict[str, bool]:
    has_beta = level in ("beta", "dev", "owner")
    has_dev = level in ("dev", "owner")
    return {
        "feedback": has_beta,
        "labs": has_beta,
        "developer_panel": has_dev,
        "api_explorer": has_dev,
        "tool_runner": has_dev,
        "event_log": has_dev,
    }


def status(owner: bool = False) -> Dict[str, Any]:
    """Compute this install's access level.

    ``owner`` is supplied by the HTTP layer (server_auth knows who is signed
    in; this module deliberately does not import it) - true when the install
    is claimed and the caller is the owner, or when the install is unclaimed
    and the caller is on loopback (owner of their own machine either way).
    Otherwise the level comes from the highest still-valid redeemed key: dev
    outranks beta outranks nothing.
    """
    signing_ready = bool(secret_store.get_keys(_SIGNING_KEY_NAME))

    keys_view: List[Dict[str, Any]] = []
    best_role: Optional[str] = None
    for record in _read_access().get("keys", []):
        valid = False
        try:
            verify(record.get("key", ""))
            valid = True
        except AccessKeyError:
            valid = False
        role = record.get("role")
        if valid and role in _ROLE_RANK:
            if best_role is None or _ROLE_RANK[role] > _ROLE_RANK[best_role]:
                best_role = role
        keys_view.append({
            "id": record.get("id"),
            "role": role,
            "name": record.get("name"),
            "exp": record.get("exp"),
            "valid": valid,
        })

    level = "owner" if owner else (best_role or "standard")
    return {
        "level": level,
        "keys": keys_view,
        "features": _features_for_level(level),
        "signing_ready": signing_ready,
    }


def list_minted() -> Dict[str, Any]:
    return {"keys": _read_minted().get("minted", [])}


def revoke(key_id: str, actor: str = "") -> Dict[str, Any]:
    revoked = _read_revoked()
    ids = revoked.setdefault("revoked", [])
    if key_id not in ids:
        ids.append(key_id)
        _write_revoked(revoked)

    registry = _read_minted()
    for record in registry.get("minted", []):
        if record.get("id") == key_id:
            record["revoked"] = True
            record["revoked_at"] = time.time()
            _write_minted(registry)
            break

    audit(actor, "revoke", key_id, "")
    return {"id": key_id, "revoked": True}


# ---------------------------------------------------------------------------
# Tester / developer applications (the public intake behind admin_server /apply)
# ---------------------------------------------------------------------------


def submit_application(
    name: str, email: str, role: str, reason: str = "", links: str = "", source_ip: str = ""
) -> Dict[str, Any]:
    name = (name or "").strip()
    email = (email or "").strip().lower()
    role = (role or "").strip().lower()
    reason = (reason or "").strip()
    links = (links or "").strip()

    if not name or len(name) > 200:
        raise AccessKeyError("Name is required and must be under 200 characters.")
    if len(email) > 320 or not _EMAIL_RE.match(email):
        raise AccessKeyError("A valid email address is required.")
    if role not in _VALID_ROLES:
        raise AccessKeyError("Role must be 'beta' or 'dev'.")
    if len(reason) > 4000:
        raise AccessKeyError("Reason is too long.")
    if len(links) > 2000:
        raise AccessKeyError("Links field is too long.")

    store = _read_applications()
    apps = store.setdefault("applications", [])

    # Dedupe: a second application from the same still-pending address updates
    # the existing record instead of piling up duplicates for the owner to sort.
    for existing in apps:
        if existing.get("email") == email and existing.get("status") == "pending":
            existing.update({"name": name, "role": role, "reason": reason, "links": links})
            _write_applications(store)
            return existing

    if len(apps) >= _MAX_APPLICATIONS:
        raise AccessKeyError("Applications are temporarily full - please try again later.")

    record = {
        "id": secrets.token_hex(8),
        "name": name,
        "email": email,
        "role": role,
        "reason": reason,
        "links": links,
        "source_ip": source_ip,
        "status": "pending",
        "created_at": time.time(),
        "decided_at": None,
        "decided_by": "",
        "minted_id": None,
    }
    apps.append(record)
    _write_applications(store)
    return record


def list_applications() -> Dict[str, Any]:
    return {"applications": _read_applications().get("applications", [])}


def decide_application(
    app_id: str, approve: bool, actor: str = "", days: int = 90
) -> Dict[str, Any]:
    store = _read_applications()
    record = None
    for candidate in store.get("applications", []):
        if candidate.get("id") == app_id:
            record = candidate
            break
    if record is None:
        raise AccessKeyError("No such application.")
    if record.get("status") != "pending":
        raise AccessKeyError(f"That application was already {record.get('status')}.")

    minted: Optional[Dict[str, Any]] = None
    if approve:
        minted = mint(
            record["role"], record["name"], email=record.get("email", ""), days=days,
            notes=f"approved application {app_id}", actor=actor,
        )
        record["minted_id"] = minted["id"]
        record["status"] = "approved"
    else:
        record["status"] = "rejected"
    record["decided_at"] = time.time()
    record["decided_by"] = actor
    _write_applications(store)
    audit(actor, "decide_application", app_id, record["status"])
    return {"application": record, "mint": minted}


# ---------------------------------------------------------------------------
# Feature flags and the audit log
# ---------------------------------------------------------------------------


def get_flags() -> Dict[str, bool]:
    return dict(_read_flags().get("flags", {}))


def set_flags(updates: Dict[str, bool], actor: str = "") -> Dict[str, bool]:
    store = _read_flags()
    flags = store.setdefault("flags", {})
    for name, value in (updates or {}).items():
        flags[str(name)] = bool(value)
    _write_flags(store)
    audit(actor, "set_flags", ",".join((updates or {}).keys()), "")
    return dict(flags)


def audit(actor: str, action: str, target: str, detail: str = "") -> None:
    """Append one line to the admin audit log. Never raises: a logging failure
    must not be allowed to break the admin action it is merely recording."""
    entry = {
        "ts": time.time(),
        "actor": actor or "unknown",
        "action": action,
        "target": target,
        "detail": detail,
    }
    try:
        path = data_path("admin_audit.jsonl")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_audit(limit: int = 100) -> List[Dict[str, Any]]:
    path = data_path("admin_audit.jsonl")
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: List[Dict[str, Any]] = []
    for line in lines[-max(limit, 0) :] if limit > 0 else []:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    out.reverse()  # newest first, matching how an audit log is normally read
    return out
