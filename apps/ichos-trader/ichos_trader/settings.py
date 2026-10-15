"""Reading and changing the settings, with auto mode and pins.

The rule Shagnik asked for: fully automatic by default, with a tuning section for anyone who wants
to turn the dials. So:

* ``load()`` - the saved settings over the defaults (``config.default_settings``).
* ``effective()`` - what a cycle actually uses: in auto mode, the manager's latest choices
  (``chosen``) replace every value the owner has **not** pinned.
* ``save(changes, unpin)`` - a number the owner sets in Tuning is **pinned**: auto mode leaves it
  alone until the owner hands it back with "unpin". Every number is clamped to a sane range, so a
  typo cannot set a 900% stop-loss.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Tuple

from . import config, store

LIMITS: Dict[str, Tuple[float, float]] = {
    "risk": (0.0, 1.0), "skeptic": (0.0, 1.0), "max_positions": (1, 40), "max_position_pct": (0.02, 1.0),
    "stop_loss_pct": (0.5, 50.0), "take_profit_pct": (0.5, 200.0), "pace_seconds": (10, 3600),
    "scan_limit": (10, 1000), "start_cash": (1.0, 100_000_000.0), "max_bots": (3, 20), "budget": (0.0, 100_000_000.0),
}
SHUTDOWN_LIMITS: Dict[str, Tuple[float, float]] = {
    "max_drawdown_pct": (1.0, 90.0), "slow_cycle_ms": (500, 600_000), "slow_cycles": (1, 100),
    "losing_hours": (1, 24 * 30), "stale_data_s": (30, 86_400),
}
#: Numbers auto mode may choose. Setting one by hand pins it.
AUTO_KEYS = ("risk",)
INTEGERS = {"max_positions", "pace_seconds", "scan_limit", "max_bots", "slow_cycle_ms", "slow_cycles",
            "losing_hours", "stale_data_s"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
#: Account currencies the practice account can be kept in (prices are converted, see ``currency``).
CURRENCIES = ("USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD", "MXN", "INR", "CNY", "SGD", "HKD", "SEK",
              "NOK", "ZAR")


def load() -> Dict[str, Any]:
    return config.merged(store.read("settings"))


def chosen() -> Dict[str, Any]:
    return store.read("chosen")


def effective() -> Dict[str, Any]:
    current = load()
    if current.get("auto"):
        pins = current.get("pins") or {}
        for key, row in chosen().items():
            if key in AUTO_KEYS and key not in pins and isinstance(row, dict) and "value" in row:
                current[key] = row["value"]
    return current


def _number(key: str, value: Any, limits: Tuple[float, float]) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be a number.") from error
    number = min(limits[1], max(limits[0], number))
    return int(round(number)) if key in INTEGERS else round(number, 4)


def save(changes: Dict[str, Any], unpin: Iterable[str] = ()) -> Dict[str, Any]:
    current = load()
    pins = dict(current.get("pins") or {})
    for key, value in (changes or {}).items():
        if key in LIMITS:
            current[key] = _number(key, value, LIMITS[key])
            if key in AUTO_KEYS:
                pins[key] = current[key]
        elif key in ("auto", "learn_first", "running", "setup_done"):
            current[key] = bool(value)
        elif key == "markets" and isinstance(value, dict):
            current["markets"].update({k: bool(v) for k, v in value.items() if k in current["markets"]})
        elif key == "shutdown" and isinstance(value, dict):
            current["shutdown"].update({k: _number(k, v, SHUTDOWN_LIMITS[k]) for k, v in value.items()
                                        if k in SHUTDOWN_LIMITS})
        elif key == "theme" and isinstance(value, dict):
            if HEX.match(str(value.get("accent", ""))):
                current["theme"]["accent"] = value["accent"]
            if value.get("mode") in ("dark", "light", "system"):
                current["theme"]["mode"] = value["mode"]
            if value.get("sync") in ("none", "nyx", "desktop"):
                current["theme"]["sync"] = value["sync"]
        elif key == "claude" and isinstance(value, dict):
            current["claude"]["enabled"] = bool(value.get("enabled"))
        elif key == "base_currency" and str(value).upper() in CURRENCIES:
            current["base_currency"] = str(value).upper()  # used from the next practice-account reset
        elif key == "broker" and value in ("sim", "alpaca"):
            current["broker"] = value
    for key in unpin or ():
        pins.pop(key, None)
    current["pins"] = pins
    store.write("settings", current)
    return current


def describe() -> Dict[str, Any]:
    """What the Tuning section draws: the settings, auto mode's choices and the ranges."""
    limits = {k: list(v) for k, v in LIMITS.items()}
    limits.update({f"shutdown.{k}": list(v) for k, v in SHUTDOWN_LIMITS.items()})
    return {"settings": load(), "effective": effective(), "chosen": chosen(), "limits": limits,
            "auto_keys": list(AUTO_KEYS), "currencies": list(CURRENCIES)}
