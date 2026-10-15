"""The Connectors page: what can be plugged in, which is recommended, and whether it is connected.

Each entry says in one line why someone would pick it. Keys are saved with ``access.secrets`` and
only ever come back masked. Entries marked ``wired: False`` are recommendations for later: they
show up so the owner can see the plan, but cannot be connected in this version.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from ..access import secrets
from ..models import BrokerError
from . import models
from .alpaca import Alpaca


def _field(key: str, label: str, secret: bool, name: str) -> Dict[str, Any]:
    return {"key": key, "label": label, "secret": secret, "name": name}


CATALOG: List[Dict[str, Any]] = [
    {"id": "alpaca", "kind": "broker", "title": "Alpaca", "recommended": True, "wired": True, "money": "practice",
     "why": "Stocks, ETFs and crypto in one free API, with a free practice account on real prices. The best first broker.",
     "fields": [_field("key_id", "API key ID (practice)", False, "alpaca_key_id"),
                _field("secret_key", "Secret key (practice)", True, "alpaca_secret_key")]},
    {"id": "alpaca_live", "kind": "broker", "title": "Alpaca (real money)", "recommended": False, "wired": True,
     "money": "real", "why": "The same Alpaca with real money. Separate keys, and only used after you switch to "
                             "real money in Setup with a budget.",
     "fields": [_field("key_id", "API key ID (live)", False, "alpaca_live_key_id"),
                _field("secret_key", "Secret key (live)", True, "alpaca_live_secret_key")]},
    {"id": "coinbase", "kind": "data", "title": "Coinbase prices", "recommended": True, "wired": True, "money": "none",
     "why": "Live crypto prices and order books with no key. Used for the crypto scan.", "fields": []},
    {"id": "yahoo", "kind": "data", "title": "Yahoo prices", "recommended": True, "wired": True, "money": "none",
     "why": "Stocks, ETFs and currencies with no key. Fine for a minute-level scan, not for high-speed trading.",
     "fields": []},
    {"id": "kraken", "kind": "broker", "title": "Kraken", "recommended": False, "wired": False, "money": "practice",
     "why": "Low crypto fees and many coins. Planned once crypto-only trading needs it.", "fields": []},
    {"id": "oanda", "kind": "broker", "title": "OANDA", "recommended": False, "wired": False, "money": "practice",
     "why": "Currencies (FX) with a free practice account. Planned for the currency traders.", "fields": []},
    {"id": "ibkr", "kind": "broker", "title": "Interactive Brokers", "recommended": False, "wired": False,
     "money": "practice", "why": "Almost every market in the world, but needs their gateway app running. Later.",
     "fields": []},
    {"id": "ollama", "kind": "model", "title": "Ollama (local, free)", "recommended": True, "wired": True,
     "money": "none", "why": "A free model on this PC. Private, and costs nothing per question.", "fields": []},
    {"id": "claude", "kind": "model", "title": "Claude (only when you ask)", "recommended": False, "wired": True,
     "money": "paid", "why": "Ask Claude why the trader did something. It is never called by itself.",
     "fields": [_field("api_key", "Anthropic API key", True, "anthropic_api_key")]},
    {"id": "google", "kind": "login", "title": "Google sign-in", "recommended": True, "wired": True, "money": "none",
     "why": "Sign in with Google when the trader runs in the cloud. Only owner addresses can change anything.",
     "fields": [_field("client_id", "OAuth client ID", False, "google_client_id"),
                _field("client_secret", "OAuth client secret", True, "google_client_secret")]},
    {"id": "github", "kind": "login", "title": "GitHub sign-in", "recommended": False, "wired": True, "money": "none",
     "why": "Sign in with GitHub instead of Google.",
     "fields": [_field("client_id", "OAuth client ID", False, "github_client_id"),
                _field("client_secret", "OAuth client secret", True, "github_client_secret")]},
    {"id": "passcode", "kind": "login", "title": "Passcode", "recommended": False, "wired": True, "money": "none",
     "why": "The simplest lock: one passcode makes you the owner. Good for a home server.",
     "fields": [_field("passcode", "Passcode (12+ characters)", True, "passcode")]},
]


def _entry(cid: str) -> Dict[str, Any]:
    found = next((c for c in CATALOG if c["id"] == cid), None)
    if found is None:
        raise KeyError(cid)
    return found


def _status(entry: Dict[str, Any], claude_on: bool) -> Dict[str, Any]:
    masked = {f["key"]: secrets.masked(f["name"]) for f in entry["fields"] if secrets.masked(f["name"])}
    connected = bool(entry["fields"]) and len(masked) == len(entry["fields"])
    if entry["kind"] == "data":
        connected, status = True, "Ready, no key needed"
    elif entry["id"] == "ollama":
        status = models.ollama_status()
        connected = status.startswith("Running")
    elif not entry["wired"]:
        status = "Planned"
    elif entry["id"] == "claude":
        status = ("On: used only when you press Ask" if claude_on else "Key saved, switched off") if connected \
            else "Not connected"
    else:
        status = "Connected" if connected else "Not connected"
    fields = [{k: f[k] for k in ("key", "label", "secret")} for f in entry["fields"]]
    return {**{k: entry[k] for k in ("id", "kind", "title", "recommended", "wired", "money", "why")},
            "fields": fields, "connected": connected, "status": status, "masked": masked}


def describe(claude_on: bool = False) -> List[Dict[str, Any]]:
    return [_status(c, claude_on) for c in CATALOG]


def connect(cid: str, values: Dict[str, str], tester: Optional[Callable[[], str]] = None) -> Dict[str, Any]:
    """Save the keys, test them where a free test exists, and forget them again if the test fails."""
    entry = _entry(cid)
    if not entry["wired"]:
        raise ValueError(f"{entry['title']} is planned but not wired up yet.")
    missing = [f["label"] for f in entry["fields"] if not str(values.get(f["key"], "")).strip()
               and not secrets.get(f["name"])]
    if missing:
        raise ValueError("Missing: " + ", ".join(missing) + ".")
    if cid == "passcode" and len(str(values.get("passcode", ""))) < 12:
        raise ValueError("Use a passcode of 12 characters or more.")
    for f in entry["fields"]:
        if str(values.get(f["key"], "")).strip():
            secrets.put(f["name"], str(values[f["key"]]))
    note = "Saved."
    if cid in ("alpaca", "alpaca_live"):  # a look at the account only: connecting never places an order
        try:
            live = cid == "alpaca_live"
            note = (tester or Alpaca(money="real" if live else "practice", allow_real=live).test)()
        except BrokerError as error:
            disconnect(cid)
            raise ValueError(str(error)) from error
    return {**_status(entry, cid == "claude"), "note": note}


def disconnect(cid: str) -> None:
    for f in _entry(cid)["fields"]:
        secrets.forget(f["name"])
