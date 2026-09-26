"""Accounts: separate spaces on one PC for different things ("user1", "NIS", …).

The owner (2026-09-26): "add an accounts next to the logout place … it locally creates a separate file division
between accounts if the user wants different accounts for different things. Add a account creation with password
if wanted, name of account (user1, NIS, or whatever the user wishes) and add a purpose to semi feed the AI to make
sure it knows why this account is special."

An account is a folder (``paths.account_dir``). Its chats, memory, notes, Second Brain, uploads, research and
offices live there (``paths.ACCOUNT_SCOPED``); keys, sign-in, settings, models, tabs, skills, trading and Nyx's own
training stay shared. "main" is the data that existed before accounts, so nothing moved when they arrived.

The engine works in one account for its whole life, because nearly every store opens its file once. Switching
therefore saves which account opens next and restarts the engine (``routes_accounts``).

A password is optional. It stops anyone switching into, changing or removing that account inside Nyx; the files
themselves are not encrypted, and the Accounts sheet says so. Only a scrypt hash is kept (``auth.hash_password``).
The purpose reaches the model as context in its standing instructions (``chat_service``), not as orders.

Nothing here deletes an account's files: removing one moves its folder to ``accounts/_removed/``.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import paths

MAX_NAME = 40
MAX_PURPOSE = 600
MIN_PASSWORD = 6

#: One colour per account, from the app's cluster palette, so the header dot tells them apart.
COLORS = ("#a594ff", "#64d2ff", "#30d158", "#ffd60a", "#ff9f0a", "#ff6fae", "#5ac8fa")

#: Wrong passwords before the account refuses for a while, and how long it refuses.
MAX_FAILS = 5
LOCKOUT_SECONDS = 60
_FAIL_WINDOW = 300

_LOCK = threading.RLock()
_FAILS: Dict[str, List[float]] = {}


class AccountError(Exception):
    """Something the owner can fix; the message says how."""

    status = 400


class PasswordError(AccountError):
    status = 403


class AccountNotFound(AccountError):
    status = 404


# --- the index --------------------------------------------------------------------------


def _main_record() -> Dict[str, Any]:
    return {"id": paths.MAIN_ACCOUNT, "name": "Main", "purpose": "", "color": COLORS[0], "created_at": 0}


def _read() -> Dict[str, Any]:
    try:
        data = json.loads(paths.accounts_index_path().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except (OSError, ValueError):
        data = {}
    records = [r for r in data.get("accounts", [])
               if isinstance(r, dict) and paths.valid_account_id(str(r.get("id") or ""))]
    if not any(r["id"] == paths.MAIN_ACCOUNT for r in records):
        records.insert(0, _main_record())
    data["accounts"] = records
    data["active"] = str(data.get("active") or paths.MAIN_ACCOUNT)
    return data


def _write(data: Dict[str, Any]) -> None:
    target = paths.accounts_index_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    paths.atomic_replace(temp, target)


def _find(data: Dict[str, Any], account_id: str) -> Dict[str, Any]:
    for record in data["accounts"]:
        if record["id"] == account_id:
            return record
    raise AccountNotFound("There is no account like that any more — reopen Accounts.")


def _public(record: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    account_id = record["id"]
    return {
        "id": account_id,
        "name": record.get("name") or account_id,
        "purpose": record.get("purpose") or "",
        "color": record.get("color") or COLORS[0],
        "locked": bool(record.get("password_hash")),
        "created_at": record.get("created_at") or 0,
        "main": account_id == paths.MAIN_ACCOUNT,
        "running": account_id == paths.ACTIVE_ACCOUNT,
        "opens_next": account_id == data["active"],
        "folder": str(paths.account_dir(account_id)),
    }


def list_accounts() -> Dict[str, Any]:
    with _LOCK:
        data = _read()
        return {
            "accounts": [_public(r, data) for r in data["accounts"]],
            "running": paths.ACTIVE_ACCOUNT,
            "opens_next": data["active"],
            "switch_pending": data["active"] != paths.ACTIVE_ACCOUNT,
            "shared": "Keys, sign-in, settings, models, tabs, skills and trading are shared by every account.",
        }


def current() -> Dict[str, Any]:
    """The account this engine is working in."""
    with _LOCK:
        data = _read()
        try:
            return _public(_find(data, paths.ACTIVE_ACCOUNT), data)
        except AccountNotFound:  # removed underneath a running engine: say so rather than crash
            return _public({"id": paths.ACTIVE_ACCOUNT, "name": paths.ACTIVE_ACCOUNT}, data)


# --- checks -----------------------------------------------------------------------------


def _clean_name(name: str, data: Dict[str, Any], keep_id: str = "") -> str:
    name = " ".join(str(name or "").split())
    if not name:
        raise AccountError("Give the account a name — anything, like user1 or NIS.")
    if len(name) > MAX_NAME:
        raise AccountError(f"Keep the name under {MAX_NAME} characters.")
    if any(ord(ch) < 32 for ch in name):
        raise AccountError("The name can't contain control characters.")
    for record in data["accounts"]:
        if record["id"] != keep_id and str(record.get("name", "")).casefold() == name.casefold():
            raise AccountError(f"There is already an account called {record.get('name')}.")
    return name


def _clean_purpose(purpose: str) -> str:
    purpose = str(purpose or "").strip()
    if len(purpose) > MAX_PURPOSE:
        raise AccountError(f"Keep the purpose under {MAX_PURPOSE} characters — a sentence or two is plenty.")
    return purpose


def _check_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AccountError(f"Use at least {MIN_PASSWORD} characters for the password, or leave it empty.")
    if len(password) > 200:
        raise AccountError("That password is too long.")


def _slug(name: str, data: Dict[str, Any]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32].strip("-") or "account"
    if not base[0].isalnum():
        base = "account"
    taken = {r["id"] for r in data["accounts"]} | {paths.MAIN_ACCOUNT, "_removed"}
    candidate, n = base, 2
    while candidate in taken or (paths.DATA_DIR / "accounts" / candidate).exists():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _verify(record: Dict[str, Any], password: str) -> None:
    """Pass when the account has no password or this is it; count and slow down wrong ones."""
    if not record.get("password_hash"):
        return
    import auth

    account_id = record["id"]
    now = time.time()
    fails = [t for t in _FAILS.get(account_id, []) if now - t < _FAIL_WINDOW]
    if len(fails) >= MAX_FAILS and now - fails[-1] < LOCKOUT_SECONDS:
        wait = int(LOCKOUT_SECONDS - (now - fails[-1])) + 1
        raise PasswordError(f"Too many wrong passwords. Try again in {wait} seconds.")
    if not password:
        raise PasswordError(f"{record.get('name')} has a password. Type it to continue.")
    if not auth.verify_password(password, record.get("password_hash", ""), record.get("password_salt", "")):
        fails.append(now)
        _FAILS[account_id] = fails
        raise PasswordError("That password isn't right.")
    _FAILS.pop(account_id, None)


def _set_password(record: Dict[str, Any], password: str) -> None:
    import auth

    _check_new_password(password)
    record["password_hash"], record["password_salt"] = auth.hash_password(password)


# --- changes ----------------------------------------------------------------------------


_README = """This folder is the Nyx account "{name}".

Nyx keeps this account's chats, memory, notes, Second Brain, uploads, research and offices here, apart from
every other account. Keys, sign-in, settings, models, tabs and skills are shared with the others.

What it is for: {purpose}
"""


def create(name: str, purpose: str = "", password: str = "") -> Dict[str, Any]:
    with _LOCK:
        data = _read()
        clean = _clean_name(name, data)
        record: Dict[str, Any] = {
            "id": _slug(clean, data),
            "name": clean,
            "purpose": _clean_purpose(purpose),
            "color": COLORS[len(data["accounts"]) % len(COLORS)],
            "created_at": time.time(),
        }
        if password:
            _set_password(record, password)
        folder = paths.account_dir(record["id"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "README.txt").write_text(
            _README.format(name=clean, purpose=record["purpose"] or "(not given)"), encoding="utf-8")
        data["accounts"].append(record)
        _write(data)
        return _public(record, data)


def update(account_id: str, *, password: str = "", name: Optional[str] = None, purpose: Optional[str] = None,
           new_password: Optional[str] = None, remove_password: bool = False) -> Dict[str, Any]:
    with _LOCK:
        data = _read()
        record = _find(data, account_id)
        _verify(record, password)
        if name is not None:
            record["name"] = _clean_name(name, data, keep_id=account_id)
        if purpose is not None:
            record["purpose"] = _clean_purpose(purpose)
        if new_password:
            _set_password(record, new_password)
        elif remove_password:
            record.pop("password_hash", None)
            record.pop("password_salt", None)
        _write(data)
        return _public(record, data)


def switch(account_id: str, password: str = "") -> Dict[str, Any]:
    """Choose the account that opens next. Returns whether the engine must restart for it."""
    with _LOCK:
        data = _read()
        record = _find(data, account_id)
        if account_id != paths.ACTIVE_ACCOUNT:  # going back to the one already open needs no password
            _verify(record, password)
        data["active"] = account_id
        _write(data)
        return {"account": _public(record, data), "restart_needed": account_id != paths.ACTIVE_ACCOUNT}


def remove(account_id: str, password: str = "") -> Dict[str, Any]:
    """Take an account off the list. Its folder is moved aside, never deleted."""
    with _LOCK:
        data = _read()
        record = _find(data, account_id)
        if account_id == paths.MAIN_ACCOUNT:
            raise AccountError("Main can't be removed — it holds everything from before accounts existed.")
        if account_id == paths.ACTIVE_ACCOUNT:
            raise AccountError("Switch to another account before removing this one.")
        _verify(record, password)
        kept: Optional[Path] = None
        folder = paths.account_dir(account_id)
        if folder.exists():
            kept = paths.DATA_DIR / "accounts" / "_removed" / f"{account_id}-{time.strftime('%Y%m%d-%H%M%S')}"
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(folder), str(kept))
        data["accounts"] = [r for r in data["accounts"] if r["id"] != account_id]
        if data["active"] == account_id:
            data["active"] = paths.ACTIVE_ACCOUNT
        _write(data)
        _FAILS.pop(account_id, None)
        return {"removed": account_id, "kept_at": str(kept) if kept else ""}


# --- for the model ----------------------------------------------------------------------


def purpose_note() -> str:
    """What the model is told about the account it is working in; empty when there is nothing to say."""
    try:
        with _LOCK:
            data = _read()
            record = _find(data, paths.ACTIVE_ACCOUNT)
    except Exception:  # noqa: BLE001 - an unreadable index must never stop a chat turn
        return ""
    purpose = " ".join(str(record.get("purpose") or "").split())[:MAX_PURPOSE]
    several = len(data["accounts"]) > 1
    if not purpose and not several:
        return ""
    lines = [f"You are working in the account \"{record.get('name') or record['id']}\"."]
    if several:
        lines.append("It is one of several separate accounts on this PC: its chats, memory, notes and files are kept "
                     "apart from the others', which you cannot see from here.")
    if purpose:
        lines.append(f"What the owner made it for, in their words: {purpose}")
        lines.append("Let that shape what you suggest, remember and emphasise; still answer anything they ask.")
    return "\n".join(lines)
