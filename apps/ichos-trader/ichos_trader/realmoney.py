"""The switch between practice money and real money.

The owner: the trader "needs both practice/training mode and the real money mode", with the same
kind of switch the old Trading tab had, "but of course more automatic". So practice stays the
default, and switching to real money takes three things together, so a slip of the mouse can't do it:

* Alpaca's **real-money keys**, separate from the practice keys;
* a **budget**: the most money the bots may use (plus what they earn), however big the account is;
* the owner typing the **confirmation**, stored with the time it was agreed.

After that it is as automatic as practice: no order waits for a click. The safety is in the limits
instead: the budget, a **daily loss limit** that stops it for the day, and the usual shut-down
rules. Switching either way stops the engine, so the next trade only happens after the owner
presses Start and can see which money it is about to use.
"""

from __future__ import annotations

import time
from typing import Any, Dict

from . import settings as settings_mod, store
from .access import secrets
from .connectors.alpaca import KEYS

CONFIRMATION = "I understand this uses real money"
MAX_BUDGET = 1_000_000.0
DAILY_LOSS_LIMITS = (0.5, 50.0)


def status() -> Dict[str, Any]:
    real = settings_mod.load()["real_money"]
    return {"on": bool(real.get("on")), "budget": float(real.get("budget") or 0),
            "daily_loss_pct": float(real.get("daily_loss_pct") or 5.0), "agreed_at": float(real.get("agreed_at") or 0),
            "confirmation": CONFIRMATION, "keys": all(secrets.get(name) for name in KEYS["real"]),
            "max_budget": MAX_BUDGET}


def switch_on(budget: Any, confirmation: str, daily_loss_pct: Any = None) -> Dict[str, Any]:
    if " ".join(str(confirmation or "").split()).lower() != CONFIRMATION.lower():
        raise ValueError(f'To switch to real money, type exactly: {CONFIRMATION}')
    try:
        amount = float(budget)
        limit = float(daily_loss_pct if daily_loss_pct not in (None, "") else status()["daily_loss_pct"])
    except (TypeError, ValueError) as error:
        raise ValueError("The budget and the daily loss limit must be numbers.") from error
    if not 1 <= amount <= MAX_BUDGET:
        raise ValueError(f"The budget must be between 1 and {MAX_BUDGET:,.0f}.")
    if not status()["keys"]:
        raise ValueError("Add Alpaca's real-money (live) keys first.")
    current = settings_mod.load()
    current["real_money"] = {"on": True, "budget": round(amount, 2), "agreed_at": time.time(),
                             "daily_loss_pct": round(min(DAILY_LOSS_LIMITS[1], max(DAILY_LOSS_LIMITS[0], limit)), 2)}
    current["broker"] = "alpaca"
    current["running"] = False
    store.write("settings", current)
    return status()


def switch_off() -> Dict[str, Any]:
    """Back to practice. Real positions stay in the account; the bots just stop trading them."""
    current = settings_mod.load()
    current["real_money"] = {**current["real_money"], "on": False}
    current["running"] = False
    store.write("settings", current)
    return status()
