"""The trader's own ranking: how easy a market is to trade, and how good a trade looks right now.

Shagnik: "It should have its own ranking based on liquidity, spread, market depth, and order flow."
Each of the four becomes a number from 0 to 1 (flow from -1 to 1), with a sentence for the
dashboard:

* **Liquidity** - dollars traded in a day, on a log scale: $100 k scores 0, $10 B scores 1.
* **Spread** - the bid-ask gap. Read from the feed when it gives bid and ask (crypto); otherwise
  estimated from the last weeks' highs and lows with the Corwin-Schultz method. 1 bp scores 1,
  100 bp (1%) scores 0.
* **Depth** - dollars resting within 1% of the price in the order book. Free stock feeds have no
  book, so there it is estimated as a small slice of daily volume and marked "estimated".
* **Order flow** - who is pushing: the book's bid/ask imbalance, or without a book, where each
  recent bar closed inside its range, weighted by volume (closing near the high on big volume is
  buying pressure).

**Tradability** mixes liquidity, spread and depth: it is the cost and the risk of getting in and
out. **Opportunity** is the price signal (``core.indicators``) nudged by order flow. The final
**score** is half each, so a great-looking signal on a market you cannot get out of does not rank
first. Pure functions: no network, easy to test.
"""

from __future__ import annotations

import math
from statistics import mean
from typing import Any, Dict, List, Optional

from .core import clock, indicators
from .models import Book, Candle, Snapshot


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def dollar_volume(snap: Snapshot) -> float:
    """Dollars traded in a day: from the quote when it has a day's volume, else from daily candles."""
    q = snap.quote
    if q and q.volume_24h and q.price:
        return float(q.volume_24h) * float(q.price)
    recent = [c.volume * c.close for c in snap.candles[-20:] if c.volume > 0]
    return mean(recent) if recent else 0.0


def corwin_schultz_bps(candles: List[Candle]) -> Optional[float]:
    """Spread estimated from two-day highs and lows (Corwin & Schultz, 2012), in basis points.

    The idea: a day's high is usually a buy at the ask and its low a sell at the bid, so the
    high-low range holds both volatility and the spread. Volatility grows with the window and the
    spread does not, so comparing one-day and two-day ranges separates the two.
    """
    k = 3 - 2 * math.sqrt(2)
    estimates = []
    for a, b in zip(candles[-21:-1], candles[-20:]):
        if min(a.low, b.low) <= 0:
            continue
        beta = math.log(a.high / a.low) ** 2 + math.log(b.high / b.low) ** 2
        gamma = math.log(max(a.high, b.high) / min(a.low, b.low)) ** 2
        alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / k - math.sqrt(gamma / k)
        estimates.append(max(0.0, 2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha))))
    return mean(estimates) * 10_000 if estimates else None


def _near(book: Book, mid: float, band: float = 0.01) -> Dict[str, float]:
    bids = sum(p * s for p, s in book.bids if p >= mid * (1 - band))
    asks = sum(p * s for p, s in book.asks if p <= mid * (1 + band))
    return {"bids": bids, "asks": asks}


def microstructure(snap: Snapshot) -> Dict[str, Any]:
    """The four measures for one market, each with its score and a plain note."""
    q = snap.quote
    price = q.price if q else (snap.candles[-1].close if snap.candles else 0.0)
    notes: List[str] = []

    volume = dollar_volume(snap)
    liquidity = _clamp((math.log10(volume) - 5) / 5) if volume > 0 else 0.0

    spread = q.spread_bps if q else None
    spread_source = "quote"
    if spread is None:
        spread = corwin_schultz_bps(snap.candles)
        spread_source = "estimated"
    spread = max(0.5, spread) if spread is not None else 50.0
    spread_score = _clamp(1 - math.log10(max(spread, 1.0)) / 2)

    book = snap.book
    if book and book.bids and book.asks and price:
        mid = (book.bids[0][0] + book.asks[0][0]) / 2
        near = _near(book, mid)
        depth = near["bids"] + near["asks"]
        total = depth or 1.0
        flow = (near["bids"] - near["asks"]) / total
        depth_source = "book"
    else:
        depth = volume * 0.002
        flow = _bar_flow(snap.candles)
        depth_source = "estimated"
    depth_score = _clamp((math.log10(depth) - 4) / 3) if depth > 0 else 0.0

    if spread > 30:
        notes.append(f"Wide spread ({spread:.0f} bp): each round trip costs about {spread / 100:.2f}%.")
    if liquidity < 0.3:
        notes.append(f"Thin market: about ${volume:,.0f} traded a day.")
    if abs(flow) > 0.3:
        notes.append(f"{'Buyers' if flow > 0 else 'Sellers'} are pushing ({flow:+.2f}).")

    tradability = 0.4 * liquidity + 0.3 * spread_score + 0.3 * depth_score
    return {"liquidity": round(liquidity, 3), "dollar_volume": round(volume, 2), "spread_bps": round(spread, 2),
            "spread_source": spread_source, "spread_score": round(spread_score, 3), "depth_usd": round(depth, 2),
            "depth_source": depth_source, "depth_score": round(depth_score, 3), "flow": round(_clamp(flow, -1, 1), 3),
            "tradability": round(tradability, 3), "notes": notes}


def _bar_flow(candles: List[Candle], bars: int = 10) -> float:
    """Volume-weighted close location over recent bars: +1 every bar closed at its high, -1 at its low."""
    weighted, total = 0.0, 0.0
    for c in candles[-bars:]:
        if c.high > c.low:
            location = ((c.close - c.low) - (c.high - c.close)) / (c.high - c.low)
            weight = c.volume or 1.0
            weighted += location * weight
            total += weight
    return weighted / total if total else 0.0


def assess(snap: Snapshot) -> Optional[Dict[str, Any]]:
    """Everything the dashboard and the bots need about one market, or None if it has no price."""
    if snap.error or not (snap.quote or snap.candles):
        return None
    inst = snap.instrument
    closes = snap.closes
    signal = indicators.analyse(closes, [c.volume for c in snap.candles], clock.periods_per_year(inst.asset_class))
    micro = microstructure(snap)
    opportunity = _clamp(signal["score"] * signal["confidence"] * 1.4 + 0.25 * micro["flow"], -1.0, 1.0)
    score = 0.5 * micro["tradability"] + 0.5 * (opportunity + 1) / 2
    price = snap.quote.price if snap.quote else closes[-1]
    return {
        "symbol": inst.symbol, "name": inst.name or inst.symbol, "asset_class": inst.asset_class, "price": price,
        "change_pct": snap.quote.change_pct if snap.quote else None, "score": round(score, 3),
        "signal": signal["signal"], "confidence": signal["confidence"], "reasons": signal["reasons"],
        "opportunity": round(opportunity, 3), "open": clock.is_open(inst.asset_class),
        "sparkline": [round(c, 6) for c in closes[-40:]], **micro,
    }


def rank(snapshots: List[Snapshot]) -> List[Dict[str, Any]]:
    """Every market that has a price, best score first."""
    rows = [row for row in (assess(s) for s in snapshots) if row]
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows
