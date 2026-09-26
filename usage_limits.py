"""Usage limits the providers themselves report — the bar under the model menu (Request G6).

The owner: "add a bar if the specific api has a usage limit and if not don't have it."

Only numbers a provider actually gave are shown, never a guessed quota:

* **Rate-limit headers** on every reply — Groq and OpenAI (``x-ratelimit-*``),
  Anthropic (``anthropic-ratelimit-*``), and the generic ``ratelimit-*`` form.
* **Quota errors** — Gemini sends no headers, but a 429 names the quota it hit
  and its value ("GenerateRequestsPerDayPerProjectPerModel-FreeTier", 1000).
  From then on Nyx counts that day's requests against the learned number, and
  says the figure is counted.
* **Balance APIs** — DeepSeek and Moonshot (Kimi) report the money left on the key.

A provider with none of these gets no bar.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from paths import atomic_replace, data_path

_LOCK = threading.Lock()
_STATE: Dict[str, Any] = {"loaded": False, "providers": {}}
_BALANCE_TTL = 600.0

#: (limit header, remaining header, reset header, kind, window)
HEADER_SETS = [
    ("x-ratelimit-limit-requests", "x-ratelimit-remaining-requests", "x-ratelimit-reset-requests", "requests", ""),
    ("x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens", "tokens", ""),
    ("anthropic-ratelimit-requests-limit", "anthropic-ratelimit-requests-remaining", "anthropic-ratelimit-requests-reset", "requests", "minute"),
    ("anthropic-ratelimit-tokens-limit", "anthropic-ratelimit-tokens-remaining", "anthropic-ratelimit-tokens-reset", "tokens", "minute"),
    ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset", "requests", ""),
    ("ratelimit-limit", "ratelimit-remaining", "ratelimit-reset", "requests", ""),
]


def _path():
    return data_path("usage_limits.json")


def _load() -> None:
    if _STATE["loaded"]:
        return
    _STATE["loaded"] = True
    try:
        _STATE["providers"] = json.loads(_path().read_text(encoding="utf-8")).get("providers", {})
    except (OSError, ValueError):
        _STATE["providers"] = {}


def _save() -> None:
    try:
        temp = _path().with_suffix(".json.tmp")
        temp.write_text(json.dumps({"providers": _STATE["providers"]}, indent=1), encoding="utf-8")
        atomic_replace(temp, _path())
    except OSError:  # pragma: no cover - the bar is a convenience
        pass


def _number(value: Any) -> Optional[float]:
    try:
        return float(str(value).split(",")[0].strip())
    except (TypeError, ValueError):
        return None


def parse_reset(value: Any, now: Optional[float] = None) -> Optional[float]:
    """Epoch seconds when a limit resets, from "2m59.5s", "7.66s", "30", an epoch, or an ISO time."""
    now = now or time.time()
    text = str(value or "").strip()
    if not text:
        return None
    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", text)
    if parts and "".join(n + u for n, u in parts) == text.replace(" ", ""):
        seconds = sum(float(n) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[u] for n, u in parts)
        return now + seconds
    number = _number(text)
    if number is not None:
        return number if number > 1_000_000_000 else now + number
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _window_from_reset(reset_at: Optional[float], now: float) -> str:
    if reset_at is None:
        return ""
    left = reset_at - now
    return "minute" if left <= 90 else "hour" if left <= 5400 else "day"


def record_headers(provider: str, headers: Any, model: str = "", now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Store every limit the reply's headers carry. Returns what was found."""
    now = now or time.time()
    lowered = {str(k).lower(): v for k, v in dict(headers or {}).items()}
    found = []
    for limit_h, remaining_h, reset_h, kind, window in HEADER_SETS:
        limit, remaining = _number(lowered.get(limit_h)), _number(lowered.get(remaining_h))
        if limit is None or remaining is None or limit <= 0:
            continue
        if any(f["kind"] == kind for f in found):
            continue  # the specific header set already covered this kind
        reset_at = parse_reset(lowered.get(reset_h), now)
        found.append({"kind": kind, "window": window or _window_from_reset(reset_at, now), "limit": limit,
                      "remaining": max(0.0, remaining), "reset_at": reset_at, "source": "headers", "model": model,
                      "updated_at": now})
    if found:
        with _LOCK:
            _load()
            entry = _STATE["providers"].setdefault(provider, {})
            for item in found:
                entry[f"{item['kind']}:{item['window']}"] = item
            _save()
    return found


def _next_pacific_midnight(now: float) -> float:
    # Google's daily quotas reset at midnight Pacific time; PDT is UTC-7 for most of the year.
    pacific = timezone(timedelta(hours=-7))
    local = datetime.fromtimestamp(now, pacific)
    return (local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp()


def record_quota_error(provider: str, body: str, model: str = "", now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Learn a quota from a 429 body (Gemini's QuotaFailure details)."""
    now = now or time.time()
    try:
        details = json.loads(body).get("error", {}).get("details", [])
    except (ValueError, AttributeError):
        return None
    retry_at = None
    learned = None
    for detail in details if isinstance(details, list) else []:
        if not isinstance(detail, dict):
            continue
        if str(detail.get("@type", "")).endswith("RetryInfo"):
            retry_at = parse_reset(detail.get("retryDelay"), now)
        for violation in detail.get("violations", []) or []:
            value = _number(violation.get("quotaValue"))
            quota_id = str(violation.get("quotaId", ""))
            if value is None or value <= 0:
                continue
            daily = "PerDay" in quota_id
            learned = {"kind": "tokens" if "Token" in quota_id else "requests", "window": "day" if daily else "minute",
                       "limit": value, "remaining": 0.0, "used": value, "day": _day_key(now),
                       "reset_at": _next_pacific_midnight(now) if daily else None, "source": "quota error",
                       "quota_id": quota_id, "model": str((violation.get("quotaDimensions") or {}).get("model") or model),
                       "updated_at": now}
    if learned is None:
        return None
    if learned["window"] == "minute":
        learned["reset_at"] = retry_at or now + 60
    with _LOCK:
        _load()
        _STATE["providers"].setdefault(provider, {})[f"{learned['kind']}:{learned['window']}:{learned['model']}"] = learned
        _save()
    return learned


def _day_key(now: float) -> str:
    return datetime.fromtimestamp(now, timezone(timedelta(hours=-7))).strftime("%Y-%m-%d")


def count_request(provider: str, model: str = "", now: Optional[float] = None) -> None:
    """Count a successful request against a daily quota learned earlier (Gemini)."""
    now = now or time.time()
    with _LOCK:
        _load()
        entry = _STATE["providers"].get(provider)
        if not entry:
            return
        changed = False
        for key, item in entry.items():
            if item.get("source") not in ("quota error", "counted") or item.get("window") != "day" or item.get("kind") != "requests":
                continue
            if item.get("model") and model and item["model"] != model:
                continue
            if item.get("day") != _day_key(now):
                item.update(day=_day_key(now), used=0.0, reset_at=_next_pacific_midnight(now))
            item["used"] = float(item.get("used", 0)) + 1
            item["remaining"] = max(0.0, float(item["limit"]) - item["used"])
            item["source"] = "counted"
            item["updated_at"] = now
            changed = True
        if changed:
            _save()


def observe(provider: str, response: Any, model: str = "") -> None:
    """Call with every provider HTTP response. Never raises."""
    try:
        record_headers(provider, getattr(response, "headers", {}) or {}, model)
        status = getattr(response, "status_code", 0)
        if status == 429:
            record_quota_error(provider, getattr(response, "text", "") or "", model)
        elif 200 <= status < 300:
            count_request(provider, model)
    except Exception:  # noqa: BLE001 - measuring must never break a reply
        pass


def _balance(provider: str) -> Optional[Dict[str, Any]]:
    import requests

    import model_hub

    key = model_hub.api_key_for(provider)
    if not key:
        return None
    headers = {"Authorization": f"Bearer {key}"}
    if provider == "deepseek":
        data = requests.get("https://api.deepseek.com/user/balance", headers=headers, timeout=6).json()
        info = (data.get("balance_infos") or [{}])[0]
        amount = _number(info.get("total_balance"))
        return None if amount is None else {"amount": amount, "currency": info.get("currency", "USD"),
                                             "available": bool(data.get("is_available", amount > 0))}
    if provider == "kimi":
        for base in ("https://api.moonshot.ai", "https://api.moonshot.cn"):
            response = requests.get(f"{base}/v1/users/me/balance", headers=headers, timeout=6)
            if response.status_code == 200:
                data = response.json().get("data", {})
                amount = _number(data.get("available_balance"))
                if amount is not None:
                    return {"amount": amount, "currency": "CNY" if base.endswith(".cn") else "USD", "available": amount > 0}
    return None


def balance(provider: str, refresh: bool = False) -> Optional[Dict[str, Any]]:
    if provider not in ("deepseek", "kimi"):
        return None
    now = time.time()
    with _LOCK:
        _load()
        cached = _STATE["providers"].get(provider, {}).get("balance")
    if cached and not refresh and now - cached.get("updated_at", 0) < _BALANCE_TTL:
        return cached
    try:
        fresh = _balance(provider)
    except Exception:  # noqa: BLE001 - no balance shown rather than a wrong one
        fresh = None
    if fresh is None:
        return cached
    fresh["updated_at"] = now
    with _LOCK:
        _STATE["providers"].setdefault(provider, {})["balance"] = fresh
        _save()
    return fresh


def snapshot(provider: str, refresh_balance: bool = False, now: Optional[float] = None) -> Dict[str, Any]:
    """Known limits for one provider — empty when it reports none (then no bar is shown)."""
    now = now or time.time()
    with _LOCK:
        _load()
        entry = dict(_STATE["providers"].get(provider, {}))
    limits = []
    for key, item in entry.items():
        if key == "balance" or not isinstance(item, dict):
            continue
        item = dict(item)
        if item.get("reset_at") and item["reset_at"] <= now:
            if item.get("source") in ("quota error", "counted") and item.get("window") == "day":
                item.update(remaining=item["limit"], used=0.0, reset_at=_next_pacific_midnight(now))
            elif item.get("window") in ("minute", "hour"):
                item["remaining"] = item["limit"]  # the window rolled over since the last reply
        if now - float(item.get("updated_at", now)) > 2 * 86400:
            continue
        limits.append(item)
    order = {"day": 0, "hour": 1, "minute": 2, "": 3}
    limits.sort(key=lambda i: (order.get(i.get("window", ""), 3), i.get("kind") != "requests"))
    return {"provider": provider, "limits": limits[:3], "balance": balance(provider, refresh=refresh_balance)}
