"""Several API keys per provider, what each key's API said, and failover between them.

Request H8: "allow me to add multiple api keys for one so if one fails it can be stored as
failed and can be retried every 5 attempts or so while the other ones are stored as working.
Then the user is alerted after a while that it failed and asks if it can disregard only the
one that doesn't work."

Request H11: "When I try to change to a 'paid' model it says it's paid but I do have an API key
for free ... only have it as paid if the API responds with that." A key is marked as needing
payment here only when its API answered with a payment error (402, insufficient balance,
insufficient_quota, "credit balance is too low"). A free-tier rate limit is not a payment error.

Nothing that could be used as a key is written by this module. Keys stay in ``.env.local`` /
``secret_store``; the health file holds a fingerprint (12 hex chars of SHA-256), the kind of
failure, and the API's message with any key scrubbed out.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

from paths import data_path

#: A failed key is tried again on every fifth request to its provider.
RETRY_EVERY = 5
#: The owner is asked about a key once it has failed this many times in a row ...
ALERT_AFTER_FAILS = 3
#: ... over at least this long (one bad minute is not worth a question).
ALERT_AFTER_SECONDS = 20 * 60

BUILTIN_KEY_NAMES: Dict[str, str] = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "kimi": "KIMI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "qwen": "QWEN_API_KEY",
}

_PAYMENT_RE = re.compile(
    r"\b402\b|payment required|insufficient[_ ]?(?:quota|balance|funds|credits?)|credit balance"
    r"|out of credits|no credits|add (?:more )?credits|purchase credits|requires? (?:a )?paid plan"
    r"|billing (?:is )?not (?:enabled|active)|account is not active",
    re.IGNORECASE,
)
_AUTH_RE = re.compile(
    r"\b401\b|\b403\b|unauthori[sz]ed|invalid[_ ](?:api[_ ])?key|incorrect api key|invalid authentication"
    r"|api key not valid|api_key_invalid|permission[_ ]denied|forbidden|authentication",
    re.IGNORECASE,
)
_QUOTA_RE = re.compile(
    r"\b429\b|rate.?limit|too many requests|resource[_ ]exhausted|quota|per ?(?:minute|day)|retry in",
    re.IGNORECASE,
)
_SECRETISH_RE = re.compile(r"(key=|bearer\s+|x-api-key[:=]\s*)[^\s&\"']+", re.IGNORECASE)

_LOCK = threading.RLock()


def classify(error: str) -> str:
    """What a failure says about the key: ``payment``, ``auth``, ``quota`` or ``other``.

    ``other`` (timeouts, 5xx, empty replies) is the provider's problem, not the key's, so it
    never marks a key failed and never triggers a switch to another key.
    """
    text = str(error or "")
    if _PAYMENT_RE.search(text):
        return "payment"
    if _AUTH_RE.search(text):
        return "auth"
    if _QUOTA_RE.search(text):
        return "quota"
    return "other"


def fingerprint(key: str) -> str:
    return hashlib.sha256((key or "").strip().encode("utf-8")).hexdigest()[:12]


def last4(key: str) -> str:
    key = (key or "").strip()
    return key[-4:] if len(key) >= 8 else ""


def key_name_for(provider: str) -> str:
    """The key variable a provider reads (ANTHROPIC_API_KEY for claude, a spec's own for custom)."""
    name = (provider or "").strip().lower()
    if name in BUILTIN_KEY_NAMES:
        return BUILTIN_KEY_NAMES[name]
    try:
        from provider_specs import PROVIDER_SPECS

        spec = PROVIDER_SPECS.get(name)
        return spec.api_key_name if spec is not None else ""
    except Exception:  # pragma: no cover - a broken spec store means no custom keys
        return ""


def _settings():
    from config import SETTINGS

    return SETTINGS


def current_key(key_name: str) -> str:
    """The key requests use right now (the live settings value)."""
    value = getattr(_settings(), key_name.lower(), "") if key_name else ""
    return str(value or "").strip()


def all_keys(key_name: str) -> List[Dict[str, str]]:
    """Every key known for a variable, as ``{"key", "source"}``, environment first."""
    if not key_name:
        return []
    found: List[Dict[str, str]] = []
    seen = set()

    def add(value: str, source: str) -> None:
        value = (value or "").strip()
        if value and value not in seen:
            seen.add(value)
            found.append({"key": value, "source": source})

    add(os.getenv(key_name, ""), "env")
    try:
        from secret_store import get_keys

        for value in get_keys(key_name):
            add(value, "stored")
    except Exception:  # pragma: no cover
        pass
    add(current_key(key_name), "live")
    return found


def _path():
    return data_path("key_health.json")


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: Dict[str, Any]) -> None:
    path = _path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _scrub(text: str, key: str = "") -> str:
    cleaned = str(text or "")
    if key and len(key) >= 6:
        cleaned = cleaned.replace(key, "[key]")
    return _SECRETISH_RE.sub(r"\1[key]", cleaned)[:300]


def plan(key_name: str) -> List[str]:
    """The keys to try for one request, in order.

    Working keys first (the one in use leads, so a provider does not flip between keys).
    A failed key is left out, except on every ``RETRY_EVERY``-th request, when it is tried
    last to see whether it recovered. When every key has failed, all of them are tried.
    """
    keys = [k["key"] for k in all_keys(key_name)]
    if len(keys) <= 1:
        return keys
    with _LOCK:
        data = _load()
        health = data.setdefault(key_name, {})
        live = current_key(key_name)
        working, retry = [], []
        for key in keys:
            entry = health.get(fingerprint(key)) or {}
            if entry.get("state") != "failed":
                working.append(key)
                continue
            entry["skips"] = int(entry.get("skips", 0)) + 1
            if entry["skips"] >= RETRY_EVERY:
                entry["skips"] = 0
                retry.append(key)
            health[fingerprint(key)] = entry
        _save(data)
    if live in working:
        working.remove(live)
        working.insert(0, live)
    ordered = working + retry
    return ordered or keys


def use(key_name: str, key: str) -> None:
    """Make ``key`` the live key for its provider (providers read settings at call time)."""
    if key_name and key:
        setattr(_settings(), key_name.lower(), key)


def report(key_name: str, key: str, ok: bool, error: str = "") -> str:
    """Record how a request with ``key`` went. Returns the failure kind ("" on success)."""
    if not key_name or not key:
        return "" if ok else classify(error)
    kind = "" if ok else classify(error)
    if not ok and kind == "other":
        return kind
    with _LOCK:
        data = _load()
        health = data.setdefault(key_name, {})
        fp = fingerprint(key)
        entry = health.get(fp) or {}
        now = time.time()
        if ok:
            entry = {"state": "working", "last_ok": now, "keep": bool(entry.get("keep"))}
        else:
            if entry.get("state") != "failed":
                entry["first_failed"] = now
                entry["fails"] = 0
                entry["alerted"] = False
            entry.update({
                "state": "failed",
                "kind": kind,
                "fails": int(entry.get("fails", 0)) + 1,
                "last_failed": now,
                "last_error": _scrub(error, key),
                "skips": 0,
            })
        health[fp] = entry
        _save(data)
    return kind


def payment_problem(provider: str) -> Optional[str]:
    """Why a provider needs payment — only when its API said so for every key it has."""
    key_name = key_name_for(provider)
    keys = all_keys(key_name)
    if not keys:
        return None
    health = _load().get(key_name, {})
    reasons = []
    for item in keys:
        entry = health.get(fingerprint(item["key"])) or {}
        if entry.get("state") != "failed" or entry.get("kind") != "payment":
            return None
        reasons.append(entry.get("last_error") or "payment required")
    return reasons[0] if reasons else None


def summary(provider: str) -> Dict[str, Any]:
    """Every key for a provider, masked, with what its API last said."""
    key_name = key_name_for(provider)
    health = _load().get(key_name, {})
    live = current_key(key_name)
    rows = []
    for item in all_keys(key_name):
        fp = fingerprint(item["key"])
        entry = health.get(fp) or {}
        rows.append({
            "fingerprint": fp,
            "last4": last4(item["key"]),
            "source": item["source"],
            "in_use": item["key"] == live,
            "state": entry.get("state") or "untested",
            "kind": entry.get("kind") or "",
            "fails": int(entry.get("fails", 0)),
            "last_error": entry.get("last_error") or "",
            "last_ok": entry.get("last_ok") or 0,
            "last_failed": entry.get("last_failed") or 0,
        })
    return {"provider": provider, "key_name": key_name, "keys": rows,
            "needs_payment": payment_problem(provider)}


def alerts(now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Keys that have kept failing long enough to ask the owner about."""
    now = now or time.time()
    data = _load()
    by_key_name = {v: k for k, v in BUILTIN_KEY_NAMES.items()}
    found = []
    for key_name, health in data.items():
        if not isinstance(health, dict):
            continue
        live_keys = {fingerprint(k["key"]): k for k in all_keys(key_name)}
        for fp, entry in health.items():
            if not isinstance(entry, dict) or entry.get("state") != "failed" or entry.get("alerted") or entry.get("keep"):
                continue
            if fp not in live_keys:
                continue
            long_enough = now - float(entry.get("first_failed") or now) >= ALERT_AFTER_SECONDS
            if int(entry.get("fails", 0)) >= ALERT_AFTER_FAILS and long_enough:
                found.append({
                    "provider": by_key_name.get(key_name, key_name.lower().replace("_api_key", "")),
                    "key_name": key_name,
                    "fingerprint": fp,
                    "last4": last4(live_keys[fp]["key"]),
                    "source": live_keys[fp]["source"],
                    "kind": entry.get("kind") or "",
                    "fails": int(entry.get("fails", 0)),
                    "since": entry.get("first_failed"),
                    "last_error": entry.get("last_error") or "",
                    "others_working": sum(
                        1 for other_fp in live_keys
                        if other_fp != fp and (health.get(other_fp) or {}).get("state") != "failed"
                    ),
                })
    return found


def resolve(key_name: str, fp: str, action: str) -> Dict[str, Any]:
    """The owner's answer to an alert: ``drop`` removes only that key, ``keep`` stops asking."""
    matches = [k for k in all_keys(key_name) if fingerprint(k["key"]) == fp]
    if not matches:
        raise KeyError("That key is no longer configured.")
    item = matches[0]
    with _LOCK:
        data = _load()
        health = data.setdefault(key_name, {})
        if action == "keep":
            entry = health.get(fp) or {}
            entry.update({"keep": True, "alerted": True})
            health[fp] = entry
            _save(data)
            return {"kept": True}
        if action != "drop":
            raise ValueError("action must be 'drop' or 'keep'")
        if item["source"] == "env":
            raise ValueError("That key comes from .env.local or the environment; remove it there.")
        from secret_store import get_keys, set_keys

        remaining = [k for k in get_keys(key_name) if fingerprint(k) != fp]
        set_keys(key_name, remaining)
        health.pop(fp, None)
        _save(data)
    if current_key(key_name) == item["key"]:
        replacement = next((k["key"] for k in all_keys(key_name) if fingerprint(k["key"]) != fp), "")
        setattr(_settings(), key_name.lower(), replacement)
    return {"dropped": True, "remaining": len(remaining)}
