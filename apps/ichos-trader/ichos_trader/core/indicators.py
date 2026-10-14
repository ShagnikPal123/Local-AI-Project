"""Transparent indicators: trend, momentum, RSI, volatility and volume, every reason in words.

Copied from the main app's ``trading/signals.py`` (the pure part only: no network, no store), so
the trader can read a price series exactly the way the old Trading tab did. A signal is an estimate
about the next few bars, not a promise.

``periods_per_year`` is 252 for stocks and 365 for crypto (it never closes), so "very volatile"
means the same thing for both.
"""

from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional


def sma(values: List[float], n: int) -> Optional[float]:
    return mean(values[-n:]) if len(values) >= n else None


def rsi(values: List[float], n: int = 14) -> Optional[float]:
    if len(values) <= n:
        return None
    gains, losses = [], []
    for a, b in zip(values[-n - 1:-1], values[-n:]):
        change = b - a
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain, avg_loss = mean(gains), mean(losses)
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def analyse(closes: List[float], volumes: Optional[List[float]] = None, periods_per_year: int = 252) -> Dict[str, Any]:
    """Score from -1 (sell) to +1 (buy) with the reasons. Pure — unit tested without the network."""
    if len(closes) < 25:
        return {"signal": "hold", "score": 0.0, "confidence": 0.5, "reasons": ["Not enough price history yet."], "indicators": {}}
    price = closes[-1]
    s20, s50 = sma(closes, 20), sma(closes, 50)
    r = rsi(closes)
    ret5 = price / closes[-6] - 1
    ret20 = price / closes[-21] - 1
    daily = [b / a - 1 for a, b in zip(closes[-21:-1], closes[-20:])]
    vol = pstdev(daily) * math.sqrt(periods_per_year) if len(daily) > 2 else 0.0
    score, reasons = 0.0, []

    if s20 and price > s20:
        score += 0.2; reasons.append(f"Above its 20-day average (${s20:,.2f}).")
    elif s20:
        score -= 0.2; reasons.append(f"Below its 20-day average (${s20:,.2f}).")
    if s50:
        if s20 and s20 > s50:
            score += 0.2; reasons.append("20-day average is above the 50-day (uptrend).")
        elif s20:
            score -= 0.2; reasons.append("20-day average is below the 50-day (downtrend).")
    if ret20 > 0.05:
        score += 0.2; reasons.append(f"Up {ret20:.1%} over 20 days (momentum).")
    elif ret20 < -0.05:
        score -= 0.2; reasons.append(f"Down {abs(ret20):.1%} over 20 days.")
    if ret5 > 0.03:
        score += 0.1; reasons.append(f"Up {ret5:.1%} this week.")
    elif ret5 < -0.03:
        score -= 0.1; reasons.append(f"Down {abs(ret5):.1%} this week.")
    if r is not None:
        if r > 72:
            score -= 0.25; reasons.append(f"RSI {r:.0f}: stretched — pullbacks are common from here.")
        elif r < 30:
            score += 0.2; reasons.append(f"RSI {r:.0f}: oversold — bounces are common from here.")
    if volumes and len(volumes) >= 21 and volumes[-1] > 0:
        avg_volume = mean(volumes[-21:-1]) or 1
        if volumes[-1] > 2 * avg_volume:
            reasons.append(f"Volume {volumes[-1] / avg_volume:.1f}× normal — something is moving it; check the news.")
    if vol > 0.6:
        score *= 0.7; reasons.append(f"Very volatile ({vol:.0%} a year), so confidence is lowered.")

    score = max(-1.0, min(1.0, score))
    signal = "buy" if score >= 0.35 else "sell" if score <= -0.35 else "hold"
    confidence = round(0.5 + min(0.45, abs(score) * 0.5), 2)
    return {"signal": signal, "score": round(score, 2), "confidence": confidence, "reasons": reasons,
            "indicators": {"price": price, "sma20": s20, "sma50": s50, "rsi14": round(r, 1) if r is not None else None,
                           "return_5d": round(ret5 * 100, 2), "return_20d": round(ret20 * 100, 2), "volatility": round(vol * 100, 1)}}
