"""Sage, the strategist: learns which strategy works in which kind of market, and keeps learning.

Shagnik: "Add a way or a mode for the ai to first understand how trading works, the current market
and situation ... so that it won't have to learn on the fly." This is that mode.

For each market it studies, Sage backtests every strategy in ``core.strategies`` over that market's
history and files the result under the market's mood (``core.forecast.regime``: rising, falling,
quiet or wild). The **playbook** is the average of all of that: "in a wild market, breakout beat
just holding by 4% on average over 9 studies". The advisor reads it to pick a strategy.

**Learn first:** until it has studied ``LEARN_TARGET`` markets, the engine stays in "learning" and
places no trades. After that it keeps studying a few markets every cycle (oldest study first), so
the playbook follows the market instead of freezing on day one. A study costs a few milliseconds
of arithmetic, so a handful per cycle never slows the cycle down.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from .. import store
from ..core import clock, forecast, strategies
from ..models import Snapshot

LEARN_TARGET = 24
PER_CYCLE = 6
RESTUDY_AFTER = 24 * 3600
MIN_BARS = 80


def _empty() -> Dict[str, Any]:
    return {"studied": {}, "table": {}, "done": False}


def playbook() -> Dict[str, Any]:
    return store.read("playbook", _empty)


def study(snaps: List[Snapshot], team: Any, now: float = 0.0) -> int:
    """Study up to ``PER_CYCLE`` markets that are new or due again. Returns how many were studied."""
    now = now or time.time()
    sage = team.one("strategist")
    book = playbook()
    due = [s for s in snaps if len(s.closes) >= MIN_BARS
           and now - float(book["studied"].get(s.symbol, 0)) > RESTUDY_AFTER]
    done = 0
    for snap in due[:PER_CYCLE]:
        years = clock.periods_per_year(snap.instrument.asset_class)
        mood = forecast.regime(snap.closes, years)
        results = strategies.backtest_all(snap.closes, periods_per_year=years)
        row = book["table"].setdefault(mood, {})
        for result in results:
            cell = row.setdefault(result["strategy"], {"runs": 0, "ret": 0.0, "beat": 0.0})
            n = cell["runs"]
            cell["ret"] = round((cell["ret"] * n + result["return_pct"]) / (n + 1), 3)
            cell["beat"] = round((cell["beat"] * n + result["beat_holding_pct"]) / (n + 1), 3)
            cell["runs"] = n + 1
        book["studied"][snap.symbol] = now
        best = results[0] if results else None
        if best:
            team.notes.add(sage, f"Studied {snap.symbol} ({mood} market): {best['title']} did best, "
                                 f"{best['return_pct']:+.1f}% vs holding {best['buy_hold_pct']:+.1f}%.", "idea", snap.symbol)
        done += 1
    if not book["done"] and len(book["studied"]) >= LEARN_TARGET:
        book["done"] = True
        team.notes.add(sage, f"Finished learning: {len(book['studied'])} markets studied. Trading can start.", "idea")
    team.set_doing(sage, f"Studied {done} markets this cycle; {len(book['studied'])} in the playbook."
                   if done else f"Playbook holds {len(book['studied'])} markets; all fresh.", "working" if done else "idle")
    store.write("playbook", book)
    return done


def learning_status() -> Dict[str, Any]:
    book = playbook()
    studied = len(book["studied"])
    return {"done": bool(book["done"]), "studied": studied, "total": max(LEARN_TARGET, studied),
            "words": ("Studied " if book["done"] else "Learning: studied ") + f"{studied} markets.",
            "best": best_overall()}


def best_for(mood: str, min_runs: int = 2) -> List[Dict[str, Any]]:
    """Strategies for one kind of market, best first by how much they beat holding."""
    row = playbook()["table"].get(mood, {})
    rows = [{"strategy": k, "title": strategies.STRATEGIES[k]["title"], "regime": mood, "edge_pct": v["beat"],
             "runs": v["runs"]} for k, v in row.items() if v["runs"] >= min_runs and k in strategies.STRATEGIES]
    return sorted(rows, key=lambda r: -r["edge_pct"])


def best_overall() -> List[Dict[str, Any]]:
    """The winner in each kind of market, for the dashboard's learning card."""
    out = []
    for mood in ("rising", "falling", "quiet", "wild"):
        rows = [r for r in best_for(mood, 1) if r["strategy"] not in ("buy_and_hold", "dca")]
        if rows:
            out.append(rows[0])
    return out
