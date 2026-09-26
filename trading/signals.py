"""Transparent signals and an honest track record.

A signal is a handful of well-known indicators added up — trend (price vs its 20-
and 50-day averages), momentum (5- and 20-day returns), RSI(14) for stretched
moves, volatility, and unusual volume — with every reason listed. It is an
estimate about the next few days, not a promise and not financial advice.

Each signal is recorded with its price. After its horizon, it is scored against
what the price actually did, so the Trading tab can show how often Nyx's signals
were right instead of just how confident they sounded.
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional

from trading import market, store

HORIZON_DAYS = 5


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


def analyse(closes: List[float], volumes: Optional[List[float]] = None) -> Dict[str, Any]:
    """Score from -1 (sell) to +1 (buy) with the reasons. Pure — unit tested without the network."""
    if len(closes) < 25:
        return {"signal": "hold", "score": 0.0, "confidence": 0.5, "reasons": ["Not enough price history yet."], "indicators": {}}
    price = closes[-1]
    s20, s50 = sma(closes, 20), sma(closes, 50)
    r = rsi(closes)
    ret5 = price / closes[-6] - 1
    ret20 = price / closes[-21] - 1
    daily = [b / a - 1 for a, b in zip(closes[-21:-1], closes[-20:])]
    vol = pstdev(daily) * math.sqrt(252) if len(daily) > 2 else 0.0
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


def signal_for(symbol: str, record: bool = True) -> Dict[str, Any]:
    rows = market.history(symbol, "6mo")
    result = analyse([r["close"] for r in rows], [r["volume"] for r in rows])
    try:
        live = market.quote(symbol)
        result["indicators"]["price"] = live["price"]
        result["change_pct"] = live["change_pct"]
    except market.MarketDataError:
        pass
    result["symbol"] = symbol.upper()
    result["sparkline"] = [round(r["close"], 2) for r in rows[-60:]]
    if record and result["signal"] != "hold":
        _record(result)
    return result


def _record(result: Dict[str, Any]) -> None:
    entry = {"symbol": result["symbol"], "signal": result["signal"], "confidence": result["confidence"],
             "price": result["indicators"]["price"], "at": time.time(), "horizon_days": HORIZON_DAYS, "outcome": None}

    def change(data: Dict[str, Any]) -> None:
        recent = [p for p in data["predictions"] if p["symbol"] == entry["symbol"] and p["outcome"] is None and entry["at"] - p["at"] < 86400]
        if not recent:
            data["predictions"] = (data["predictions"] + [entry])[-2000:]

    store.update("predictions", lambda: {"predictions": []}, change)


def score_track_record(now: Optional[float] = None) -> Dict[str, Any]:
    """Grade predictions whose horizon has passed; return hit rate overall and per signal."""
    now = now or time.time()
    data = store.read("predictions", lambda: {"predictions": []})
    changed = False
    for p in data["predictions"]:
        if p["outcome"] is not None or now - p["at"] < p["horizon_days"] * 86400:
            continue
        try:
            price = market.quote(p["symbol"])["price"]
        except market.MarketDataError:
            continue
        moved = price / p["price"] - 1
        p["outcome"] = {"return_pct": round(moved * 100, 2), "right": (moved > 0) if p["signal"] == "buy" else (moved < 0), "graded_at": now}
        changed = True
    if changed:
        store.write("predictions", data)
    graded = [p for p in data["predictions"] if p["outcome"] is not None]
    right = sum(1 for p in graded if p["outcome"]["right"])
    return {"graded": len(graded), "right": right, "hit_rate": round(right / len(graded), 3) if graded else None,
            "pending": sum(1 for p in data["predictions"] if p["outcome"] is None), "horizon_days": HORIZON_DAYS,
            "recent": list(reversed(graded[-12:]))}


def symbol_reliability(symbol: str) -> Dict[str, Any]:
    """How often past signals for this one symbol were actually right, as a position-sizing multiplier.

    A symbol with no graded history yet (new to the watchlist, or nothing has matured past its
    horizon) gets a neutral 1.0x — it hasn't earned a bigger bet and hasn't made a mistake yet
    either. A small number of graded signals moves the multiplier gently (``weight``); a longer
    track record of being wrong pulls it down harder, so a symbol the AI has been consistently
    wrong about keeps getting smaller positions instead of the same mistake at full size, and a
    symbol it reads well keeps getting a modest boost. Clamped to [0.35, 1.4] so nothing goes to
    zero (one bad week shouldn't blacklist a stock forever) and nothing overweights the account.
    """
    symbol = symbol.upper()
    data = store.read("predictions", lambda: {"predictions": []})
    graded = [p for p in data["predictions"] if p["symbol"] == symbol and p["outcome"] is not None]
    if not graded:
        return {"symbol": symbol, "graded": 0, "hit_rate": None, "multiplier": 1.0}
    right = sum(1 for p in graded if p["outcome"]["right"])
    hit_rate = right / len(graded)
    weight = min(len(graded), 8) / 8.0
    multiplier = max(0.35, min(1.4, 1.0 + (hit_rate - 0.5) * 1.5 * weight))
    return {"symbol": symbol, "graded": len(graded), "hit_rate": round(hit_rate, 3), "multiplier": round(multiplier, 3)}


def rank_watchlist(symbols: List[str], record: bool = False, max_workers: int = 6) -> List[Dict[str, Any]]:
    """Every symbol's signal plus its reliability, best opportunity first.

    This is the "keep looking for the best trade" scan: one pass — fetched in parallel so a
    20-symbol watchlist doesn't mean 20 sequential network round trips — that the autopilot, a
    chat tool, or the UI can all call to see what currently looks best to buy or sell, ranked by
    an ``expected_value`` that discounts a strong-sounding signal on a symbol the AI has a poor
    track record with, so a loud but unreliable pick doesn't outrank a modest but dependable one.
    """
    symbols = [s for s in dict.fromkeys(s.strip().upper() for s in symbols) if s]
    if not symbols:
        return []
    results: Dict[str, Dict[str, Any]] = {}

    def fetch(symbol: str) -> None:
        try:
            signal = signal_for(symbol, record=record)
        except market.MarketDataError as error:
            results[symbol] = {"symbol": symbol, "error": str(error)}
            return
        reliability = symbol_reliability(symbol)
        signal["reliability"] = reliability
        signal["expected_value"] = round(signal["score"] * signal["confidence"] * reliability["multiplier"], 4)
        results[symbol] = signal

    with ThreadPoolExecutor(max_workers=min(max_workers, len(symbols))) as pool:
        list(pool.map(fetch, symbols))
    ordered = [results[s] for s in symbols if s in results]
    ordered.sort(key=lambda s: s.get("expected_value", -99), reverse=True)
    return ordered
