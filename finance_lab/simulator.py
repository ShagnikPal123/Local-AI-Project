"""Practice first, then act: walk-forward runs over real history.

The owner: "Add a finance memory simulator and feature so it trains and then
does that."

Training is a walk forward, not a single backtest: the history is cut into
windows, every strategy is tested inside each window, and the result is filed
under the regime that window was in. That is why the memory can say "in a wild
market, breakout beat holding two times out of three" instead of one number for
all weather.

`advise` is the "then does that" half: look at today's regime, ask the memory
what has worked there, and hand back that strategy's current read — with the
memory row attached so the reason survives to the screen.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence

from . import forecast, memory, node_map, strategies

#: Each practice window is about this long, stepping forward by a quarter of it.
WINDOW_DAYS = 180
STEP_DAYS = 45
#: Never spend longer than this on one training call.
MAX_SECONDS = 120


def _history(symbol: str, range_: str = "2y") -> List[Dict[str, Any]]:
    from trading import market

    node_map.light("market", symbol)
    return market.history(symbol, range_)


def train(symbols: Sequence[str], *, range_: str = "2y", history_by_symbol: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Practice on real history and write down what worked where."""
    started = time.time()
    windows = 0
    tested = 0
    problems: List[str] = []
    for symbol in [s.strip().upper() for s in symbols if str(s).strip()][:12]:
        if time.time() - started > MAX_SECONDS:
            problems.append("Stopped early — training has a time budget.")
            break
        try:
            history = (history_by_symbol or {}).get(symbol) or _history(symbol, range_)
        except Exception as error:  # noqa: BLE001 - one bad symbol must not end training
            problems.append(f"{symbol}: {error}")
            continue
        rows = [row for row in history if isinstance(row, dict)]
        if len(rows) < WINDOW_DAYS:
            problems.append(f"{symbol}: only {len(rows)} days of history.")
            continue
        start = 0
        while start + WINDOW_DAYS <= len(rows):
            window = rows[start:start + WINDOW_DAYS]
            kind = forecast.regime(window)
            for name in strategies.names():
                result = strategies.backtest(name, window)
                if result.get("ok"):
                    memory.remember(kind, name, result)
                    tested += 1
            windows += 1
            start += STEP_DAYS
        memory.note_run({"symbol": symbol, "windows": windows, "range": range_})

    return {
        "ok": tested > 0,
        "symbols": len(symbols),
        "windows": windows,
        "tests": tested,
        "seconds": round(time.time() - started, 1),
        "problems": problems[:6],
        "table": memory.table()[:12],
    }


def advise(symbol: str, *, history: Optional[Sequence[Any]] = None, allow_web: bool = False) -> Dict[str, Any]:
    """What it would do with this symbol now, and why — from practice, not a hunch."""
    try:
        rows = list(history) if history is not None else _history(symbol)
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": str(error)}
    if len(rows) < 60:
        return {"ok": False, "error": "Not enough price history to advise on."}

    kind = forecast.regime(rows)
    learned = memory.best_for(kind)
    picked = learned["strategy"] if learned else "trend_sma"
    signal = strategies.read(picked, rows)
    outlook = forecast.predict(rows)
    if allow_web:
        outlook = forecast.with_search(symbol, outlook)
    node_map.light("decision", f"{symbol} {signal['action']}")

    why = [signal["why"]]
    if learned:
        why.append(f"In {kind} markets this beat holding {learned['beat_rate'] * 100:.0f}% of "
                   f"{learned['runs']} practice runs (avg {learned['return_pct']:+.1f}%).")
    else:
        why.append(f"No practice memory for a {kind} market yet, so this is the plain trend read. "
                   "Train the simulator to change that.")
    if outlook.get("ok"):
        why.append(outlook["note"])

    room = 0.0
    try:
        from . import capital_guard

        room = capital_guard.can_spend()
    except Exception:  # noqa: BLE001
        pass

    return {
        "ok": True,
        "symbol": symbol.upper(),
        "regime": kind,
        "strategy": picked,
        "title": strategies.STRATEGIES.get(picked, {}).get("title", picked),
        "action": signal["action"],
        "strength": signal["strength"],
        "from_memory": bool(learned),
        "memory": learned,
        "forecast": outlook,
        "why": " ".join(why),
        "money_available": room,
        "trained_at": memory.trained_at(),
    }


def background_status() -> List[Dict[str, Any]]:
    """Picked up by the feature catalog while a training run is going."""
    return [{"label": "Finance simulator", "running": _training, "detail": _training_detail, "status": "running"}] \
        if _training else []


_training = False
_training_detail = ""


def train_in_background(symbols: Sequence[str], range_: str = "2y") -> Dict[str, Any]:
    """Train without holding up the request that asked for it."""
    global _training, _training_detail
    import threading

    if _training:
        return {"ok": False, "error": "It is already practising."}

    def work() -> None:
        global _training, _training_detail
        _training = True
        _training_detail = f"{len(symbols)} symbols"
        try:
            train(symbols, range_=range_)
        finally:
            _training = False
            _training_detail = ""

    threading.Thread(target=work, name="finance-simulator", daemon=True).start()
    return {"ok": True, "started": True, "symbols": list(symbols)}
