"""Don't go broke: it may only use the money it has and the money it earns.

The owner (2026-09-22): "Make sure there is a don't go broke situation where it
tries to not go into debt if that is even possible and make sure it know all
strategies and also doesn't spend more money than allocated. Essentially it can
only access the money it has and the money it earns to make more money. If it
[fails] it needs to lea[rn]."

The rules, in the order they are checked:

1. **Its own money only.** A pot the owner sets, plus profit it has actually
   realized. Never the owner's other cash, never credit, never margin.
2. **No debt is possible.** Buying costs more than the pot has → refused. There
   is no borrowing path in this code at all, so "going into debt" is not a risk
   it manages, it is a thing it cannot express.
3. **No shorting.** Selling is limited to what it owns (the trading rules check
   the share count; here a short is refused outright).
4. **One name cannot sink it.** A single symbol may hold at most a share of the
   pot.
5. **It brakes as it loses.** Past half the loss stop, every new buy is halved.
   Past the loss stop, buying stops until the owner resets it — and a lesson is
   written, because the owner asked that losing teach it something.

This never places or blocks an order by itself; ``trading/guard.py`` calls
``check_order`` as one more rule alongside the owner's own budgets.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from paths import data_path

from . import node_map

#: Kept small on purpose: the owner reads these.
MAX_LESSONS = 40
MAX_HISTORY = 200

DEFAULTS: Dict[str, Any] = {
    #: What the owner has given the AI to work with. Nothing until they say so.
    "allocated": 0.0,
    #: Profit it has actually realized. This is the only way the pot grows.
    "realized": 0.0,
    #: Stop buying once it is this far below the high-water mark, in percent of the pot.
    "loss_stop_pct": 25.0,
    #: The most of the pot one symbol may take.
    "max_position_pct": 20.0,
    #: Practice money unless the owner switched the broker to live.
    "mode": "practice",
}

_lock = threading.Lock()


def _path():
    return data_path("finance_lab/capital.json")


def _blank() -> Dict[str, Any]:
    return {**DEFAULTS, "invested": 0.0, "peak": 0.0, "positions": {}, "lessons": [], "history": [],
            "stopped": False, "stopped_at": 0.0}


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {**_blank(), **data}
    except (OSError, ValueError):
        pass
    return _blank()


def _save(state: Dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass


def settings() -> Dict[str, Any]:
    state = _load()
    return {key: state[key] for key in DEFAULTS}


def update_settings(**changes: Any) -> Dict[str, Any]:
    with _lock:
        state = _load()
        for key, value in changes.items():
            if key in DEFAULTS and value is not None:
                state[key] = float(value) if key != "mode" else str(value)
        state["allocated"] = max(0.0, float(state["allocated"]))
        state["loss_stop_pct"] = min(90.0, max(1.0, float(state["loss_stop_pct"])))
        state["max_position_pct"] = min(100.0, max(1.0, float(state["max_position_pct"])))
        # The high-water mark moves with the money the owner puts in, so a loss is
        # measured from what it had, not from what is left after it.
        state["peak"] = max(float(state.get("peak", 0.0)), float(state["allocated"]) + float(state.get("realized", 0.0)))
        _save(state)
        return {key: state[key] for key in DEFAULTS}


# ---------------------------------------------------------------------------
# The pot
# ---------------------------------------------------------------------------


def pot() -> Dict[str, Any]:
    """Everything about the money, in one place."""
    state = _load()
    allocated = float(state["allocated"])
    realized = float(state["realized"])
    invested = float(state.get("invested", 0.0))
    total = allocated + realized
    cash = max(0.0, total - invested)
    peak = max(float(state.get("peak", 0.0)), total)
    drawdown = 0.0 if peak <= 0 else max(0.0, (peak - total) / peak * 100)
    stop = float(state["loss_stop_pct"])
    return {
        "allocated": round(allocated, 2),
        "earned": round(realized, 2),
        "total": round(total, 2),
        "invested": round(invested, 2),
        "cash": round(cash, 2),
        "peak": round(peak, 2),
        "drawdown_pct": round(drawdown, 2),
        "loss_stop_pct": stop,
        "braking": drawdown >= stop / 2 and drawdown < stop,
        "stopped": bool(state.get("stopped")) or drawdown >= stop,
        "mode": state["mode"],
        "max_position": round(total * float(state["max_position_pct"]) / 100, 2),
        "positions": dict(state.get("positions", {})),
        "lessons": list(state.get("lessons", []))[:MAX_LESSONS],
    }


def can_spend() -> float:
    """The most it could spend on a new buy right now, after every brake."""
    money = pot()
    if money["stopped"] or money["total"] <= 0:
        return 0.0
    room = money["cash"]
    if money["braking"]:
        room *= 0.5                                   # half size while it is losing
    return round(max(0.0, room), 2)


# ---------------------------------------------------------------------------
# The check trading calls
# ---------------------------------------------------------------------------


def check_order(order: Any, price: float = 0.0, *, live: bool = False) -> Tuple[bool, str]:
    """``(allowed, reason)`` for one AI order. Never raises, never places anything.

    ``order`` is ``trading.brokers.OrderRequest`` (anything with ``symbol``,
    ``side``, ``requested_by`` and ``estimated_cost(price)`` works). The owner's
    own orders are never touched — this is the AI's pocket money, not theirs.
    """
    try:
        return _check(order, price, live)
    except Exception as error:  # noqa: BLE001 - a bug here must not stop the owner trading
        return True, f"(capital guard skipped: {type(error).__name__})"


def _check(order: Any, price: float, live: bool) -> Tuple[bool, str]:
    side = str(getattr(order, "side", "")).lower()
    symbol = str(getattr(order, "symbol", "")).upper()
    if str(getattr(order, "requested_by", "owner")).lower() != "ai":
        return True, "Your own order — the AI's pot doesn't apply."

    node_map.light("capital", f"{side} {symbol}")
    money = pot()

    if side == "sell":
        held = float(money["positions"].get(symbol, 0.0))
        wanted = float(getattr(order, "qty", 0) or 0)
        if wanted and held and wanted > held * 1.000001:
            return False, (f"It would be selling {wanted:g} {symbol} but only bought {held:g}. "
                           "It never sells what it does not own.")
        return True, "Selling what it holds."

    cost = _cost(order, price)
    if money["total"] <= 0:
        # Nothing allocated means the lab is not set up, not that the answer is no:
        # refusing here would silently stop an AI trader the owner already uses, and
        # their own trading budgets are still in force either way.
        return True, ("The finance lab has no money allocated yet, so its own limits are off — "
                      "your trading budgets are what applies. Allocate a pot to turn them on.")
    if money["stopped"]:
        return False, (f"It is {money['drawdown_pct']:.1f}% down from its high, past the "
                       f"{money['loss_stop_pct']:.0f}% stop. Buying is off until you reset it — "
                       "what went wrong is written in its lessons.")
    room = can_spend()
    if cost > room + 0.01:
        if money["braking"]:
            return False, (f"${cost:,.2f} is more than the ${room:,.2f} it may risk while it is "
                           f"{money['drawdown_pct']:.1f}% down — it halves its size when it is losing.")
        return False, (f"${cost:,.2f} is more than the ${money['cash']:,.2f} it has. It only ever uses the "
                       "money you allocated plus what it has earned, so it cannot go into debt.")
    position = float(money["positions"].get(symbol, 0.0)) * max(price, 0.0)
    if money["max_position"] and position + cost > money["max_position"] + 0.01:
        return False, (f"That would put ${position + cost:,.2f} into {symbol}; one name is capped at "
                       f"${money['max_position']:,.2f} so a single mistake cannot sink the pot.")
    if live and money["mode"] != "real":
        return True, "Allowed — note this is real money; the lab is still set to practice."
    return True, f"Inside its own money (${room:,.2f} free)."


def _cost(order: Any, price: float) -> float:
    try:
        return float(order.estimated_cost(price))
    except Exception:  # noqa: BLE001 - duck-typed callers
        qty = float(getattr(order, "qty", 0) or 0)
        notional = float(getattr(order, "notional", 0) or 0)
        return notional or qty * max(price, 0.0)


# ---------------------------------------------------------------------------
# What happened
# ---------------------------------------------------------------------------


def record_fill(symbol: str, side: str, quantity: float, price: float) -> Dict[str, Any]:
    """A filled AI order: the pot moves, and so does what it holds."""
    symbol = (symbol or "").upper()
    amount = abs(float(quantity)) * max(float(price), 0.0)
    with _lock:
        state = _load()
        positions = dict(state.get("positions", {}))
        held = float(positions.get(symbol, 0.0))
        if side.lower() == "buy":
            positions[symbol] = held + abs(float(quantity))
            state["invested"] = float(state.get("invested", 0.0)) + amount
        else:
            sold = min(held, abs(float(quantity)))
            positions[symbol] = max(0.0, held - sold)
            state["invested"] = max(0.0, float(state.get("invested", 0.0)) - amount)
            if not positions[symbol]:
                positions.pop(symbol, None)
        state["positions"] = positions
        state["history"] = ([{"at": time.time(), "symbol": symbol, "side": side, "qty": float(quantity),
                              "price": float(price)}] + list(state.get("history", [])))[:MAX_HISTORY]
        _save(state)
    node_map.light("broker", f"{side} {quantity:g} {symbol}")
    return pot()


def record_result(symbol: str, profit: float, *, why: str = "") -> Dict[str, Any]:
    """A closed trade. Profit grows the pot; a loss has to teach it something."""
    profit = float(profit)
    with _lock:
        state = _load()
        state["realized"] = float(state.get("realized", 0.0)) + profit
        total = float(state["allocated"]) + float(state["realized"])
        state["peak"] = max(float(state.get("peak", 0.0)), total)
        if total <= 0:
            state["stopped"] = True
        _save(state)
    if profit < 0:
        learn(f"Lost ${abs(profit):,.2f} on {symbol.upper()}", why or "The trade went against it.")
    money = pot()
    if money["stopped"] and money["drawdown_pct"] >= money["loss_stop_pct"]:
        learn("Hit the loss stop",
              f"Down {money['drawdown_pct']:.1f}% from ${money['peak']:,.2f}. Buying stops until you reset it.")
    return money


def learn(what: str, lesson: str) -> Dict[str, Any]:
    """Write down what a loss taught it, where the owner can read it."""
    row = {"at": time.time(), "what": str(what)[:200], "lesson": str(lesson)[:400]}
    with _lock:
        state = _load()
        state["lessons"] = ([row] + list(state.get("lessons", [])))[:MAX_LESSONS]
        _save(state)
    try:
        import curiosity

        curiosity.own_mistake(row["what"], learned=row["lesson"], kind="trade")
    except Exception:  # noqa: BLE001 - the third mind is optional
        pass
    return row


def reset_stop() -> Dict[str, Any]:
    """The owner decides it may trade again. The lessons stay."""
    with _lock:
        state = _load()
        state["stopped"] = False
        state["peak"] = float(state["allocated"]) + float(state.get("realized", 0.0))
        _save(state)
    return pot()


def sync_positions(positions: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Take the AI's real holdings from the trading store, when it is there."""
    rows: Dict[str, float] = dict(positions or {})
    if not rows:
        try:
            from trading import store

            rows = {k: float(v) for k, v in store.read("ai_positions", lambda: {"symbols": {}})["symbols"].items()}
        except Exception:  # noqa: BLE001
            return pot()
    with _lock:
        state = _load()
        state["positions"] = {k.upper(): v for k, v in rows.items() if v}
        _save(state)
    return pot()


def lessons() -> List[Dict[str, Any]]:
    return list(_load().get("lessons", []))
