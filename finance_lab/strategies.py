"""The strategy library: every common way of reading a price series, in one place.

The owner: "make sure it know all strategies". Nobody knows *all* of them, so
what this does instead is honest: it holds the classic families, each in a few
lines that can be read and argued with, each backtestable on the same footing,
and each saying *why* in words the owner can check.

    trend_sma        the 20/50 crossover — the oldest trend follower there is
    momentum         has it been going up for three months
    mean_reversion   RSI: too far, too fast, expect a snap back
    bollinger        the same idea against a volatility band
    breakout         Donchian channel: new highs beget new highs
    volatility_target smaller when the market is wild, bigger when it is calm
    buy_and_hold     the benchmark everything has to beat to be worth running
    dca              buy a little, always — the "do nothing clever" baseline

Every one is long or flat. None of them can short, use leverage, or spend money
the capital guard has not cleared, because signals here are opinions, not orders.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Sequence

from . import node_map

Signal = Dict[str, Any]


def _closes(history: Sequence[Any]) -> List[float]:
    out: List[float] = []
    for row in history:
        value = row.get("close") if isinstance(row, dict) else row
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if price > 0:
            out.append(price)
    return out


def _sma(values: Sequence[float], window: int) -> float:
    if len(values) < window:
        return sum(values) / max(len(values), 1)
    return sum(values[-window:]) / window


def _rsi(values: Sequence[float], window: int = 14) -> float:
    if len(values) < window + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(len(values) - window, len(values)):
        change = values[i] - values[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    if losses == 0:
        return 100.0
    rs = (gains / window) / (losses / window)
    return 100 - 100 / (1 + rs)


def _sd(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def _hold(action: str, strength: float, why: str) -> Signal:
    return {"action": action, "strength": round(max(0.0, min(1.0, strength)), 2), "why": why}


# --- the strategies ---------------------------------------------------------------


def trend_sma(prices: Sequence[float]) -> Signal:
    fast, slow = _sma(prices, 20), _sma(prices, 50)
    gap = (fast / slow - 1) * 100 if slow else 0
    if fast > slow:
        return _hold("buy", min(1.0, abs(gap) / 4), f"The 20-day average is {gap:+.1f}% above the 50-day: an uptrend.")
    return _hold("sell", min(1.0, abs(gap) / 4), f"The 20-day average is {gap:+.1f}% below the 50-day: the trend turned.")


def momentum(prices: Sequence[float]) -> Signal:
    if len(prices) < 64:
        return _hold("hold", 0.2, "Not enough history for a three-month read.")
    change = (prices[-1] / prices[-63] - 1) * 100
    if change > 3:
        return _hold("buy", min(1.0, change / 20), f"Up {change:.1f}% over three months, and still rising.")
    if change < -3:
        return _hold("sell", min(1.0, abs(change) / 20), f"Down {change:.1f}% over three months.")
    return _hold("hold", 0.3, f"Only {change:+.1f}% over three months — no momentum either way.")


def mean_reversion(prices: Sequence[float]) -> Signal:
    rsi = _rsi(prices)
    if rsi < 30:
        return _hold("buy", (30 - rsi) / 30, f"RSI {rsi:.0f}: sold off hard, which usually bounces.")
    if rsi > 70:
        return _hold("sell", (rsi - 70) / 30, f"RSI {rsi:.0f}: bought up hard, which usually cools.")
    return _hold("hold", 0.25, f"RSI {rsi:.0f} — nothing stretched.")


def bollinger(prices: Sequence[float]) -> Signal:
    window = prices[-20:]
    if len(window) < 20:
        return _hold("hold", 0.2, "Not enough history for a band.")
    mid = sum(window) / len(window)
    sd = _sd(window) or 1e-9
    z = (prices[-1] - mid) / sd
    if z < -2:
        return _hold("buy", min(1.0, abs(z) / 3), f"{abs(z):.1f} standard deviations below the 20-day mean.")
    if z > 2:
        return _hold("sell", min(1.0, abs(z) / 3), f"{z:.1f} standard deviations above the 20-day mean.")
    return _hold("hold", 0.25, f"Inside the band ({z:+.1f} sd).")


def breakout(prices: Sequence[float]) -> Signal:
    window = prices[-55:]
    if len(window) < 25:
        return _hold("hold", 0.2, "Not enough history for a channel.")
    high, low = max(window[:-1]), min(window[:-1])
    if prices[-1] >= high:
        return _hold("buy", 0.8, f"New {len(window)}-day high at {prices[-1]:.2f}.")
    if prices[-1] <= low:
        return _hold("sell", 0.8, f"New {len(window)}-day low at {prices[-1]:.2f}.")
    return _hold("hold", 0.3, "Inside the recent range.")


def volatility_target(prices: Sequence[float]) -> Signal:
    rets = [prices[i] / prices[i - 1] - 1 for i in range(1, len(prices))][-40:]
    vol = _sd(rets) * math.sqrt(252) * 100 if rets else 0
    if vol <= 0:
        return _hold("hold", 0.2, "No volatility to size against.")
    size = max(0.1, min(1.0, 15 / vol))
    trend_row = trend_sma(prices)
    if trend_row["action"] == "buy":
        return _hold("buy", size, f"Volatility is {vol:.0f}% a year, so size at {size * 100:.0f}% of normal, trend up.")
    return _hold("hold", size * 0.5, f"Volatility {vol:.0f}% a year and no uptrend — stay small.")


def buy_and_hold(prices: Sequence[float]) -> Signal:
    return _hold("buy", 1.0, "Own it and wait. This is the bar everything else has to clear.")


def dca(prices: Sequence[float]) -> Signal:
    return _hold("buy", 0.25, "A little, regularly, whatever the price is doing.")


STRATEGIES: Dict[str, Dict[str, Any]] = {
    "trend_sma": {"fn": trend_sma, "title": "Trend (20/50)", "family": "trend"},
    "momentum": {"fn": momentum, "title": "Momentum (3 months)", "family": "trend"},
    "mean_reversion": {"fn": mean_reversion, "title": "Mean reversion (RSI)", "family": "reversion"},
    "bollinger": {"fn": bollinger, "title": "Bands (Bollinger)", "family": "reversion"},
    "breakout": {"fn": breakout, "title": "Breakout (Donchian)", "family": "trend"},
    "volatility_target": {"fn": volatility_target, "title": "Volatility target", "family": "risk"},
    "buy_and_hold": {"fn": buy_and_hold, "title": "Buy and hold", "family": "baseline"},
    "dca": {"fn": dca, "title": "Little and often", "family": "baseline"},
}


def names() -> List[str]:
    return list(STRATEGIES)


def read(name: str, history: Sequence[Any]) -> Signal:
    """One strategy's opinion of right now."""
    prices = _closes(history)
    entry = STRATEGIES.get(name)
    if entry is None:
        return _hold("hold", 0.0, f"There is no strategy called {name}.")
    if len(prices) < 10:
        return _hold("hold", 0.0, "Too little price history to say anything.")
    node_map.light("strategies", name)
    signal = entry["fn"](prices)
    signal["strategy"] = name
    signal["title"] = entry["title"]
    return signal


def read_all(history: Sequence[Any]) -> List[Signal]:
    """Every strategy's read, strongest first."""
    rows = [read(name, history) for name in STRATEGIES]
    rows.sort(key=lambda row: -row["strength"])
    return rows


def backtest(name: str, history: Sequence[Any], *, fee_pct: float = 0.05) -> Dict[str, Any]:
    """Walk the history day by day, long or flat, and see what it would have done."""
    prices = _closes(history)
    entry = STRATEGIES.get(name)
    if entry is None or len(prices) < 60:
        return {"ok": False, "error": "Not enough history to test on."}
    node_map.light("simulator", name)

    equity = 1.0
    holding = False
    trades = 0
    peak = 1.0
    worst = 0.0
    curve: List[float] = []
    for day in range(50, len(prices)):
        window = prices[: day + 1]
        signal = entry["fn"](window)
        want = signal["action"] == "buy" and signal["strength"] >= 0.25
        if want != holding:
            equity *= 1 - fee_pct / 100                    # crossing the spread costs something
            trades += 1
            holding = want
        if holding and day + 1 < len(prices):
            equity *= prices[day + 1] / prices[day]
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak)
        curve.append(round(equity, 5))

    held = prices[-1] / prices[50]
    days = len(prices) - 50
    years = max(days / 252, 0.1)
    return {
        "ok": True,
        "strategy": name,
        "title": entry["title"],
        "return_pct": round((equity - 1) * 100, 2),
        "buy_hold_pct": round((held - 1) * 100, 2),
        "beat_holding_pct": round((equity - held) * 100, 2),
        "worst_drawdown_pct": round(worst * 100, 2),
        "trades": trades,
        "per_year_pct": round(((equity ** (1 / years)) - 1) * 100, 2),
        "days": days,
        "curve": curve[-120:],
    }


def backtest_all(history: Sequence[Any]) -> List[Dict[str, Any]]:
    rows = [backtest(name, history) for name in STRATEGIES]
    good = [row for row in rows if row.get("ok")]
    good.sort(key=lambda row: -row["return_pct"])
    return good
