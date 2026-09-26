"""Adaptive mode: one switch, and the AI chooses every setting the owner left blank — again on every scan.

The owner: "a single button which turns it on … it goes hands off and I can really only
halt or stop the trader … it chooses all values, adds stocks and researches stocks on its
own. It can do as many trades as it wants … makes its own budget if the user does not
add one and can invest however much if the user does not say how much. If something is
not input it will adaptively choose it each scan and will scan faster."

How each value is chosen (``resolve``) — all from things it can measure, all explained:

* **Budget** — up to 97% of the money it may use (free cash + what it already holds),
  scaled down while the broad market (SPY) trends down, while its predictions or its real
  trades have been losing, or after a drawdown. It never counts the owner's own holdings.
* **Spread** — how many positions to hold grows with the account; the per-symbol cap
  follows from it, so a $50 account still holds ~4 names, not one.
* **Confidence bar** — stricter after losses, looser when it has been right.
* **Stop-loss / take-profit** — from the watchlist's current volatility: calm stocks get
  tight stops, jumpy ones wider stops so noise doesn't shake them out.
* **Pace** — scans every 5 minutes while the market is open; trades per day unlimited
  (a 10,000/day backstop exists only to stop a software fault from looping).

Live accounts stay protected by ``guard.check`` whatever this chooses: real money needs
the typed live switch, and live orders above ``ask_above`` still ask first.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from trading import store

UNLIMITED_TRADES = 10_000


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def resolve(*, cash: float, ai_invested: float, ranked: List[Dict[str, Any]], track: Dict[str, Any],
            lesson_summary: Dict[str, Any], market_open: bool, account_pl_pct: Optional[float] = None
            ) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Pure: the values adaptive mode would use now, and a sentence of why for each."""
    values: Dict[str, Any] = {}
    why: Dict[str, str] = {}
    capital = max(0.0, float(cash or 0) + float(ai_invested or 0))

    exposure, notes = 0.95, []
    hit, graded = track.get("hit_rate"), int(track.get("graded") or 0)
    if graded >= 10 and hit is not None and hit < 0.45:
        exposure -= 0.2
        notes.append(f"its signals were right only {hit:.0%} of the time")
    win_rate, closed = lesson_summary.get("win_rate"), int(lesson_summary.get("exits") or 0)
    if closed >= 5 and win_rate is not None and win_rate < 0.4:
        exposure -= 0.15
        notes.append(f"only {win_rate:.0%} of its recent trades made money")
    if int(lesson_summary.get("losing_streak") or 0) >= 3:
        exposure -= 0.15
        notes.append(f"{lesson_summary['losing_streak']} losing trades in a row")
    spy = next((s for s in ranked if s.get("symbol") == "SPY" and "error" not in s), None)
    if spy and spy.get("signal") == "sell":
        exposure -= 0.25
        notes.append("the broad market (SPY) is trending down")
    if account_pl_pct is not None and account_pl_pct <= -10:
        exposure -= 0.15
        notes.append(f"the account is down {abs(account_pl_pct):.0f}%")
    exposure = _clamp(exposure, 0.3, 0.97)
    values["max_invested"] = max(1.0, round(capital * exposure, 2))
    why["max_invested"] = (f"{exposure:.0%} of the ${capital:,.2f} it can use"
                           + (f" — held back because {', '.join(notes)}." if notes else " — conditions look normal."))

    tier = 4 if capital < 150 else 5 if capital < 1_000 else 7 if capital < 10_000 else 9 if capital < 100_000 else 12
    values["target_positions"] = tier
    values["max_position_pct"] = round(_clamp(1.6 / tier, 0.12, 0.4), 3)
    values["max_per_trade"] = max(1.0, round(values["max_invested"] * values["max_position_pct"], 2))
    why["target_positions"] = f"Spread across up to {tier} stocks for a ${capital:,.0f} account."
    why["max_per_trade"] = f"No single stock gets more than {values['max_position_pct']:.0%} of the budget (${values['max_per_trade']:,.2f})."

    confidence, conf_notes = 0.62, []
    if graded >= 10 and hit is not None:
        if hit >= 0.6:
            confidence -= 0.04
            conf_notes.append(f"its signals have been right {hit:.0%} of the time")
        elif hit < 0.45:
            confidence += 0.08
            conf_notes.append(f"its signals have been right only {hit:.0%} of the time")
    if int(lesson_summary.get("losing_streak") or 0) >= 2:
        confidence += 0.04
        conf_notes.append("recent trades lost")
    values["min_confidence"] = round(_clamp(confidence, 0.55, 0.8), 2)
    why["min_confidence"] = f"Needs {values['min_confidence']:.0%} confidence" + (f" because {', '.join(conf_notes)}." if conf_notes else ".")

    vols = [float(s["indicators"]["volatility"]) for s in ranked
            if "error" not in s and (s.get("indicators") or {}).get("volatility")]
    typical = median(vols) if vols else 30.0
    values["stop_loss_pct"] = round(_clamp(typical / 4, 4.0, 15.0), 1)
    values["take_profit_pct"] = round(_clamp(values["stop_loss_pct"] * 2.5, 8.0, 45.0), 1)
    why["stop_loss_pct"] = (f"Watchlist moves about {typical:.0f}% a year, so it cuts a loser at -{values['stop_loss_pct']}% "
                            f"and takes profit at +{values['take_profit_pct']}% (2.5× the risk).")

    values["scan_minutes"] = 5 if market_open else 15
    why["scan_minutes"] = "Every 5 minutes while the market is open." if market_open else "Every 15 minutes while it's closed (orders wait for the open)."
    values["research_per_day"] = 60
    values["daily_loss_stop_pct"] = 15.0
    why["daily_loss_stop_pct"] = "Stops new buys for the day after a 15% drop — a brake against bad data, not a trade limit."
    values["max_trades_per_day"] = UNLIMITED_TRADES
    why["max_trades_per_day"] = "No daily trade limit."
    values["discover_minutes"] = 45 if market_open else 120
    values["discover_max_add"] = 4
    why["discover_minutes"] = f"Looks for new stocks every {values['discover_minutes']} minutes."
    return values, why


def current() -> Dict[str, Any]:
    """The values chosen at the last scan (computing them now if there never was one)."""
    saved = store.read("adaptive", lambda: {}).get("values")
    if saved:
        return dict(saved)
    try:
        return refresh([])["values"]
    except Exception:  # noqa: BLE001 - a broker hiccup must not block the rules; be cautious instead
        return {"max_invested": 1.0, "max_per_trade": 1.0, "max_position_pct": 0.25, "target_positions": 4,
                "min_confidence": 0.7, "stop_loss_pct": 6.0, "take_profit_pct": 15.0, "scan_minutes": 15,
                "research_per_day": 20, "daily_loss_stop_pct": 10.0, "max_trades_per_day": UNLIMITED_TRADES,
                "discover_minutes": 120, "discover_max_add": 2}


def refresh(ranked: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Measure everything ``resolve`` needs from the live account and save the choice."""
    from trading import brokers, guard, lessons, market, signals

    rules = guard.settings()
    broker = brokers.get(rules["active_broker"])
    account = broker.account()
    invested = guard.ai_invested(broker)
    try:
        track = signals.score_track_record()
    except Exception:  # noqa: BLE001 - grading needs prices; a missing one mustn't stop the choice
        track = {}
    values, why = resolve(cash=float(account.get("cash") or 0), ai_invested=invested, ranked=ranked, track=track,
                          lesson_summary=lessons.summary(), market_open=market.us_market_open(),
                          account_pl_pct=account.get("pl_pct"))
    choice = {"values": values, "why": why, "at": time.time(), "capital": round(float(account.get("cash") or 0) + invested, 2)}
    store.write("adaptive", choice)
    return choice


def status() -> Dict[str, Any]:
    from trading import guard

    ai = guard.settings()["ai"]
    saved = store.read("adaptive", lambda: {})
    pins = ai.get("adaptive_pins") or {}
    chosen = {k: v for k, v in (saved.get("values") or {}).items() if k not in pins}
    return {"on": bool(ai.get("adaptive")), "pins": pins, "chosen": chosen, "why": saved.get("why") or {},
            "at": saved.get("at"), "capital": saved.get("capital"), "schedule": ai.get("schedule"),
            "schedule_state": schedule_state(ai.get("schedule"))}


# --- The owner's on/off schedule ------------------------------------------------------------


def _minutes(text: str) -> int:
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def schedule_state(schedule: Optional[Dict[str, Any]], now: Optional[float] = None) -> Dict[str, Any]:
    """Whether ``now`` (this PC's clock) is inside the owner's on-hours, and when that next changes.

    Windows may cross midnight (start 22:00, end 06:00 = on overnight).
    """
    if not schedule or not schedule.get("enabled"):
        return {"active": False, "inside": True, "next_start": None, "next_end": None, "words": ""}
    moment = datetime.fromtimestamp(now or time.time())
    start, end = _minutes(schedule["start"]), _minutes(schedule["end"])
    days = set(int(d) for d in schedule.get("days") or [])
    minute, weekday = moment.hour * 60 + moment.minute, moment.weekday()
    if start < end:
        inside = weekday in days and start <= minute < end
    else:
        inside = (weekday in days and minute >= start) or (((weekday - 1) % 7) in days and minute < end)
    next_start = None
    for offset in range(0, 9):
        candidate = (moment + timedelta(days=offset)).replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)
        if candidate.weekday() in days and candidate > moment:
            next_start = candidate
            break
    next_end = None
    if inside:
        next_end = moment.replace(hour=end // 60, minute=end % 60, second=0, microsecond=0)
        if next_end <= moment:
            next_end += timedelta(days=1)
    if inside:
        words = f"On by your schedule until {next_end:%a %H:%M}."
    elif next_start:
        words = f"Off by your schedule — back on {next_start:%a %H:%M}."
    else:
        words = "Off by your schedule (no on-days picked)."
    return {"active": True, "inside": inside, "next_start": next_start.timestamp() if next_start else None,
            "next_end": next_end.timestamp() if next_end else None, "words": words}
