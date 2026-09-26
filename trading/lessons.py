"""What the AI learned from its own closed trades — and the cool-downs that stop it repeating a mistake.

The owner: "learning if it does make a mistake no matter how small". Every exit the AI
makes is written down with its result. A loss, however small, puts that symbol on a
cool-down so the next scan doesn't buy straight back into the same falling stock; a
second loss inside two weeks makes the cool-down longer. The overall win rate of these
real exits also feeds adaptive mode (``adaptive.resolve``), which demands more
confidence while the AI is losing and relaxes again when it is winning.

Signal accuracy (was the 5-day direction right?) is tracked separately in
``signals.symbol_reliability``; this is about money actually made or lost.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from trading import store

DAY = 86400.0
SHORT_COOLDOWN_DAYS = 3.0
LONG_COOLDOWN_DAYS = 7.0
REPEAT_WINDOW_DAYS = 14.0


def _data() -> Dict[str, Any]:
    return store.read("lessons", lambda: {"exits": []})


def record_exit(symbol: str, pl_pct: float, why: str, kind: str, now: Optional[float] = None) -> Dict[str, Any]:
    """Write down one closed (or trimmed) AI position. ``kind``: stop | target | signal | rotate | other."""
    entry = {"symbol": symbol.upper(), "pl_pct": round(float(pl_pct or 0.0), 2), "why": why[:300], "kind": kind,
             "at": now or time.time(), "lesson": _lesson_for(symbol.upper(), float(pl_pct or 0.0), kind)}

    def change(data: Dict[str, Any]) -> None:
        data["exits"] = (data["exits"] + [entry])[-500:]

    store.update("lessons", lambda: {"exits": []}, change)
    return entry


def _lesson_for(symbol: str, pl_pct: float, kind: str) -> str:
    if pl_pct >= 0:
        return f"{symbol}: closed {pl_pct:+.1f}% ({kind}) — that setup worked."
    if kind == "stop":
        return f"{symbol}: stopped out {pl_pct:+.1f}%. Waiting before buying it again instead of catching a falling stock."
    return f"{symbol}: closed at a loss ({pl_pct:+.1f}%, {kind}). Treating its next buy signal with more suspicion."


def exits(limit: int = 50) -> List[Dict[str, Any]]:
    return list(reversed(_data()["exits"][-limit:]))


def cooldowns(now: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
    """Symbols the AI shouldn't buy right now, with until-when and why."""
    now = now or time.time()
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for e in _data()["exits"]:
        if e["pl_pct"] < 0 and now - e["at"] < REPEAT_WINDOW_DAYS * DAY:
            by_symbol.setdefault(e["symbol"], []).append(e)
    out: Dict[str, Dict[str, Any]] = {}
    for symbol, losses in by_symbol.items():
        last = max(losses, key=lambda e: e["at"])
        days = LONG_COOLDOWN_DAYS if len(losses) >= 2 else SHORT_COOLDOWN_DAYS
        until = last["at"] + days * DAY
        if until > now:
            out[symbol] = {"until": until, "losses": len(losses),
                           "why": f"Lost money on {symbol} {len(losses)}× lately (last {last['pl_pct']:+.1f}%) — cooling off."}
    return out


def summary(now: Optional[float] = None, window_days: float = 30.0) -> Dict[str, Any]:
    """Win rate and average result of the AI's own exits over the last ``window_days``."""
    now = now or time.time()
    recent = [e for e in _data()["exits"] if now - e["at"] < window_days * DAY]
    wins = [e for e in recent if e["pl_pct"] > 0]
    return {"exits": len(recent), "wins": len(wins),
            "win_rate": round(len(wins) / len(recent), 3) if recent else None,
            "avg_pl_pct": round(sum(e["pl_pct"] for e in recent) / len(recent), 2) if recent else None,
            "losing_streak": _losing_streak(recent)}


def _losing_streak(recent: List[Dict[str, Any]]) -> int:
    streak = 0
    for e in sorted(recent, key=lambda e: e["at"], reverse=True):
        if e["pl_pct"] >= 0:
            break
        streak += 1
    return streak
