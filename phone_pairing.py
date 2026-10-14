"""Connect a phone to this PC with a key that lives for one minute.

Owner (2026-10-13): "for connecting computer to phone if the phone number doesn't work, make it have a secret temp key
which expires after a minute so the computer first actively looks for this and then connects."

How it works:
  1. At the PC the owner presses "Show a key". The PC makes a short random key and starts listening for it. Only one
     key exists at a time, it is single use, and it stops working 60 seconds after it was made.
  2. On the phone the owner opens the page the PC shows, types the key and a name for the phone.
  3. The PC checks the key, and if it matches it hands the phone a long private token. The phone keeps that token and
     uses it from then on, so the key is only ever needed once. The token can be taken back from the PC at any time.

What it keeps, and what it never keeps:
  * The key is held in memory only, as a hash, and is never written to disk or logged.
  * The token is shown to the phone once. The PC stores only its hash, so reading ``phone_devices.json`` does not let
    anyone act as the phone.
  * Wrong keys are rationed (5 a minute per phone address, 20 a minute overall) so a key cannot be guessed in its minute.

Nothing here opens a network port; ``phone_gateway`` does that, and only when the owner turns it on.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from paths import data_path

KEY_SECONDS = 60
#: No 0/O, 1/I/L or U: a key read off a screen and typed on a phone must not be ambiguous.
ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
KEY_LENGTH = 8
TRIES_PER_SOURCE = 5
TRIES_OVERALL = 20
TRY_WINDOW = 60.0
#: A phone that has not been used for this long has to be paired again.
TOKEN_IDLE_SECONDS = 90 * 24 * 3600
MAX_DEVICES = 8
DEVICES_FILE = "phone_devices.json"


class PairingError(ValueError):
    """Why a phone was not connected, in words the phone's owner can read."""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def clean_key(raw: str) -> str:
    """Accept the key the way people type it: any case, with or without the dash or spaces."""
    return "".join(ch for ch in str(raw or "").upper() if ch in ALPHABET)


def show_key(key: str) -> str:
    return f"{key[:KEY_LENGTH // 2]}-{key[KEY_LENGTH // 2:]}"


class PhoneBook:
    """The one live key, the phones that are connected, and the rate limit. ``clock`` is swapped in tests."""

    def __init__(self, path: Optional[Any] = None, clock=time.time) -> None:
        self._path = path
        self._clock = clock
        self._lock = threading.RLock()
        self._key_hash = ""
        self._key_expires = 0.0
        self._tries: Dict[str, List[float]] = {}

    # -- the key --------------------------------------------------------------

    def mint(self) -> Dict[str, Any]:
        """Make a new key, replacing any earlier one. Returns the key (shown once) and when it stops working."""
        with self._lock:
            key = "".join(secrets.choice(ALPHABET) for _ in range(KEY_LENGTH))
            self._key_hash = _hash(key)
            self._key_expires = self._clock() + KEY_SECONDS
            return {"key": show_key(key), "expires_in": KEY_SECONDS}

    def key_seconds_left(self) -> int:
        with self._lock:
            left = self._key_expires - self._clock()
            return math.ceil(left) if self._key_hash and left > 0 else 0

    def cancel_key(self) -> None:
        with self._lock:
            self._key_hash = ""
            self._key_expires = 0.0

    def _refund_try(self, source: str) -> None:
        """A phone that got in did not guess; its try does not count against the next one."""
        if self._tries.get(source):
            self._tries[source].pop()

    def _spend_try(self, source: str) -> None:
        now = self._clock()
        recent = [t for t in self._tries.get(source, []) if now - t < TRY_WINDOW]
        overall = sum(1 for times in self._tries.values() for t in times if now - t < TRY_WINDOW)
        if len(recent) >= TRIES_PER_SOURCE or overall >= TRIES_OVERALL:
            self._tries[source] = recent
            raise PairingError("Too many wrong keys. Wait a minute and ask for a new key at the PC.")
        recent.append(now)
        self._tries[source] = recent

    def redeem(self, key: str, device_name: str, source: str = "") -> Dict[str, Any]:
        """Swap a correct, unexpired key for this phone's token. The key is used up either way it is matched."""
        with self._lock:
            self._spend_try(source or "unknown")
            typed = clean_key(key)
            live = bool(self._key_hash) and self._clock() < self._key_expires
            same = hmac.compare_digest(_hash(typed), self._key_hash) if self._key_hash else False
            if not live or len(typed) != KEY_LENGTH or not same:
                if self._key_hash and not live:
                    self.cancel_key()
                raise PairingError("That key is wrong or has run out. Ask for a new one at the PC.")
            self.cancel_key()                                # single use
            self._refund_try(source or "unknown")
            devices = self._read()
            if len(devices) >= MAX_DEVICES:
                raise PairingError(f"{MAX_DEVICES} phones are already connected. Remove one at the PC first.")
            token = secrets.token_urlsafe(32)
            now = self._clock()
            record = {"id": uuid.uuid4().hex[:10], "name": (device_name or "Phone").strip()[:40] or "Phone",
                      "token_hash": _hash(token), "created": now, "last_seen": now}
            devices.append(record)
            self._write(devices)
            return {"token": token, "device": self._public(record)}

    # -- the phones -----------------------------------------------------------

    def authenticate(self, token: str) -> Optional[Dict[str, Any]]:
        """The phone this token belongs to, or None. A phone idle for 90 days is dropped."""
        if not token:
            return None
        wanted = _hash(token)
        with self._lock:
            devices = self._read()
            now = self._clock()
            for record in devices:
                if hmac.compare_digest(record.get("token_hash", ""), wanted):
                    if now - float(record.get("last_seen", 0)) > TOKEN_IDLE_SECONDS:
                        self._write([d for d in devices if d is not record])
                        return None
                    if now - float(record.get("last_seen", 0)) > 60:      # not a disk write on every request
                        record["last_seen"] = now
                        self._write(devices)
                    return self._public(record)
        return None

    def devices(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [self._public(d) for d in self._read()]

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            devices = self._read()
            left = [d for d in devices if d.get("id") != device_id]
            if len(left) == len(devices):
                return False
            self._write(left)
            return True

    @staticmethod
    def _public(record: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": record["id"], "name": record.get("name", "Phone"), "created": record.get("created", 0),
                "last_seen": record.get("last_seen", 0)}

    # -- storage --------------------------------------------------------------

    def _file(self):
        return self._path or data_path(DEVICES_FILE)

    def _read(self) -> List[Dict[str, Any]]:
        try:
            saved = json.loads(self._file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [d for d in saved if isinstance(d, dict) and d.get("id") and d.get("token_hash")] if isinstance(saved, list) else []

    def _write(self, devices: List[Dict[str, Any]]) -> None:
        path = self._file()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(devices), encoding="utf-8")
        temp.replace(path)


_BOOK: Optional[PhoneBook] = None
_BOOK_LOCK = threading.Lock()


def book() -> PhoneBook:
    global _BOOK
    with _BOOK_LOCK:
        if _BOOK is None:
            _BOOK = PhoneBook()
        return _BOOK
