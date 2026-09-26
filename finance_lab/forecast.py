"""Where the price could go, worked out here rather than asked of an API.

The owner wanted a finance brain that does not run out of usage: "most ai need
the usage limits while a local ai and a few unlimited use ai are needed… make a
new one basically local with search so it can predict changes and plot properly."

So the prediction is arithmetic on the price history:

* **Drift and volatility** from log returns, with recent days weighted more
  (EWMA), because last month matters more than last spring.
* **A trend line** fitted to log prices, so the middle of the cone is not just
  "today, forever".
* **A cone**, not a number: the 10th, 50th and 90th percentile paths from a
  lognormal random walk with that drift and volatility. A forecast without a
  band is a guess wearing a suit.
* **A regime**, in words — quiet, trending up, trending down, wild — which is
  what ``memory`` keys its "what worked here before" on.

No key, no quota, no network. `note_search` lets a headline from the search side
shade the confidence without ever moving the numbers themselves.
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Sequence

from . import node_map

#: Trading days ahead, by default.
DEFAULT_HORIZON = 20
#: Paths in the Monte Carlo.
PATHS = 400
#: Weight on the most recent return in the EWMA.
ALPHA = 0.06


def _closes(history: Sequence[Any]) -> List[float]:
    out: List[float] = []
    for row in history:
        if isinstance(row, dict):
            value = row.get("close")
        else:
            value = row
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if price > 0:
            out.append(price)
    return out


def returns(prices: Sequence[float]) -> List[float]:
    return [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices)) if prices[i - 1] > 0]


def ewma_stats(values: Sequence[float], alpha: float = ALPHA) -> Dict[str, float]:
    """Mean and standard deviation that lean on what happened lately."""
    if not values:
        return {"mean": 0.0, "sd": 0.0}
    mean = values[0]
    var = 0.0
    for value in values[1:]:
        delta = value - mean
        mean += alpha * delta
        var = (1 - alpha) * (var + alpha * delta * delta)
    return {"mean": mean, "sd": math.sqrt(max(var, 0.0))}


def trend(prices: Sequence[float]) -> Dict[str, float]:
    """Least squares on log prices: slope per day, and how well it fits."""
    n = len(prices)
    if n < 3:
        return {"slope": 0.0, "fit": 0.0}
    xs = list(range(n))
    ys = [math.log(p) for p in prices]
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs) or 1e-9
    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    slope = sxy / sxx
    fitted = [my + slope * (x - mx) for x in xs]
    ss_res = sum((ys[i] - fitted[i]) ** 2 for i in range(n))
    ss_tot = sum((y - my) ** 2 for y in ys) or 1e-9
    return {"slope": slope, "fit": max(0.0, 1 - ss_res / ss_tot)}


def regime(prices: Sequence[float]) -> str:
    """quiet | rising | falling | wild — the kind of market this is."""
    values = _closes(prices)
    if len(values) < 20:
        return "unknown"
    rets = returns(values[-90:])
    stats = ewma_stats(rets)
    daily_sd = stats["sd"]
    annual = daily_sd * math.sqrt(252)
    line = trend(values[-60:])
    if annual > 0.55:
        return "wild"
    if line["slope"] > 0.0015 and line["fit"] > 0.3:
        return "rising"
    if line["slope"] < -0.0015 and line["fit"] > 0.3:
        return "falling"
    return "quiet"


def predict(history: Sequence[Any], horizon: int = DEFAULT_HORIZON, *, seed: Optional[int] = None) -> Dict[str, Any]:
    """A cone of where this price could be, day by day, with no model call."""
    prices = _closes(history)
    node_map.light("forecast", f"{len(prices)} days in")
    if len(prices) < 20:
        return {"ok": False, "error": "Not enough price history to forecast from (20 days or more)."}

    rets = returns(prices)
    stats = ewma_stats(rets[-250:])
    line = trend(prices[-120:])
    last = prices[-1]
    # Half the drift from the fitted trend, half from the recent mean return: the
    # trend alone over-commits after a strong run.
    drift = 0.5 * line["slope"] + 0.5 * stats["mean"]
    sd = max(stats["sd"], 1e-4)

    rng = random.Random(seed if seed is not None else 12345)
    paths: List[List[float]] = []
    for _ in range(PATHS):
        price = last
        row = []
        for _day in range(horizon):
            price *= math.exp(drift + sd * rng.gauss(0, 1))
            row.append(price)
        paths.append(row)

    days = []
    for day in range(horizon):
        column = sorted(path[day] for path in paths)
        days.append({
            "day": day + 1,
            "low": round(column[int(0.1 * len(column))], 4),
            "mid": round(column[len(column) // 2], 4),
            "high": round(column[int(0.9 * len(column)) - 1], 4),
        })

    end = days[-1]
    change = (end["mid"] / last - 1) * 100
    confidence = round(max(0.05, min(0.95, 0.35 + 0.4 * line["fit"] - 2.5 * sd)), 2)
    kind = regime(prices)
    return {
        "ok": True,
        "last": round(last, 4),
        "horizon": horizon,
        "days": days,
        "expected_change_pct": round(change, 2),
        "band_pct": [round((end["low"] / last - 1) * 100, 2), round((end["high"] / last - 1) * 100, 2)],
        "daily_volatility_pct": round(sd * 100, 3),
        "annual_volatility_pct": round(sd * math.sqrt(252) * 100, 1),
        "trend_fit": round(line["fit"], 3),
        "regime": kind,
        "confidence": confidence,
        "note": _sentence(change, kind, confidence, end, last),
    }


def _sentence(change: float, kind: str, confidence: float, end: Dict[str, float], last: float) -> str:
    direction = "up" if change > 0.5 else "down" if change < -0.5 else "flat"
    low = (end["low"] / last - 1) * 100
    high = (end["high"] / last - 1) * 100
    sure = "worth leaning on" if confidence > 0.6 else "thin" if confidence < 0.35 else "middling"
    return (f"In a {kind} market the middle path is {direction} {abs(change):.1f}% over the horizon, "
            f"with most paths between {low:+.1f}% and {high:+.1f}%. Confidence is {sure} ({confidence:.2f}).")


def with_search(symbol: str, forecast_row: Dict[str, Any], *, allow_web: bool = True) -> Dict[str, Any]:
    """Headlines beside the numbers. They shade the confidence; they never move the cone."""
    if not allow_web or not forecast_row.get("ok"):
        return forecast_row
    node_map.light("search", symbol)
    try:
        import web_access

        results = web_access.search_results(f"{symbol} stock news")[:4]
    except Exception:  # noqa: BLE001 - offline is normal and fine
        return forecast_row
    titles = [str(r.get("title", "")) for r in results if r.get("title")]
    good = sum(1 for t in titles if any(w in t.lower() for w in ("beat", "surge", "record", "upgrade", "rally", "profit")))
    bad = sum(1 for t in titles if any(w in t.lower() for w in ("miss", "fall", "cut", "downgrade", "probe", "lawsuit", "recall")))
    forecast_row["headlines"] = [{"title": t, "url": str(r.get("url", ""))} for t, r in zip(titles, results)]
    if good or bad:
        mood = "positive" if good > bad else "negative" if bad > good else "mixed"
        forecast_row["news_mood"] = mood
        if mood == "mixed" or (mood == "negative" and forecast_row["expected_change_pct"] > 0) or \
                (mood == "positive" and forecast_row["expected_change_pct"] < 0):
            forecast_row["confidence"] = round(max(0.05, forecast_row["confidence"] - 0.1), 2)
            forecast_row["note"] += f" The headlines read {mood}, which argues with the numbers, so confidence is lower."
        else:
            forecast_row["note"] += f" The headlines read {mood}, which agrees with the numbers."
    return forecast_row
