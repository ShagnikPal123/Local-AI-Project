"""A make-believe market that behaves like a real one, for when there is no internet.

Why it exists: the project's whole point is an assistant that works "both on and offline". With
no internet the trader can still run, practise and be tested, and the dashboard says plainly
"simulated market" so nobody mistakes it for real prices. Every test uses it, which is why tests
never touch the network.

How the prices are made: each market's price is a slow wave (a trend that turns), a faster wave
(swings) and a little per-bar noise, all from a seed made from its symbol. The same symbol at the
same moment always gives the same price, so a test can check exact behaviour and two calls a
second apart agree. Spreads, volumes and order books are sized like the real thing: tight and deep
for Bitcoin and Apple, wide and thin for a small coin.
"""

from __future__ import annotations

import hashlib
import math
import random
import time
from typing import Callable, Dict, List, Optional

from ..models import Book, Candle, Instrument, MarketDataError, Quote
from . import universe

_BAR = {"1m": 60, "1h": 3600, "1d": 86400}

#: Rough real prices so the dashboard looks familiar offline.
_PRICES = {"BTC-USD": 67000.0, "ETH-USD": 2500.0, "SOL-USD": 150.0, "SPY": 560.0, "QQQ": 480.0, "AAPL": 225.0,
           "MSFT": 420.0, "NVDA": 120.0, "EUR-USD": 1.09, "GBP-USD": 1.30, "USD-JPY": 148.0}

#: Yearly volatility and typical spread (basis points) by kind of market.
_STYLE = {"crypto": (0.65, 2.0), "stock": (0.32, 2.0), "etf": (0.18, 1.0), "fx": (0.08, 0.6)}


def _seed(*parts: object) -> int:
    return int.from_bytes(hashlib.blake2b("|".join(map(str, parts)).encode(), digest_size=8).digest(), "big")


class SimulatedFeed:
    """Every market in the universe, priced by a deterministic wave-and-noise model."""

    name = "sim"

    def __init__(self, clock: Callable[[], float] = time.time, instruments: Optional[List[Instrument]] = None):
        self._clock = clock
        items = instruments if instruments is not None else universe.everything()
        self._by_symbol: Dict[str, Instrument] = {
            i.symbol: Instrument(i.symbol, i.asset_class, i.name, i.quote_currency, "sim") for i in items}
        # Position inside its own kind of market: earlier entries in each list are the big names.
        counts: Dict[str, int] = {}
        self._rank: Dict[str, int] = {}
        for inst in self._by_symbol.values():
            self._rank[inst.symbol] = counts.get(inst.asset_class, 0)
            counts[inst.asset_class] = self._rank[inst.symbol] + 1

    def instruments(self) -> List[Instrument]:
        return list(self._by_symbol.values())

    def _inst(self, symbol: str) -> Instrument:
        inst = self._by_symbol.get(symbol.upper())
        if not inst:
            raise MarketDataError(f"The simulated market has no {symbol}.")
        return inst

    def _profile(self, symbol: str) -> Dict[str, float]:
        """The fixed character of one market: price level, wave sizes, spread and daily dollar volume."""
        inst = self._inst(symbol)
        rng = random.Random(_seed("profile", symbol))
        vol, spread = _STYLE.get(inst.asset_class, (0.3, 3.0))
        # The big names get more volume and a tighter spread.
        size = 1.0 / (1.0 + self._rank[symbol] / 8.0)
        return {
            "base": _PRICES.get(symbol, math.exp(rng.uniform(math.log(2), math.log(400)))),
            "vol": vol * rng.uniform(0.7, 1.4),
            "slow_period": rng.uniform(20, 60) * 86400, "slow_phase": rng.uniform(0, 2 * math.pi),
            "fast_period": rng.uniform(2, 8) * 86400, "fast_phase": rng.uniform(0, 2 * math.pi),
            # Small coins get far wider spreads than small stocks, as in real life.
            "spread_bps": spread * rng.uniform(0.6, 1.4) / max(size, 0.08 if inst.asset_class == "crypto" else 0.4),
            "dollar_volume": (5e9 if inst.asset_class == "fx" else 2e9) * size * rng.uniform(0.3, 1.5),
        }

    def _price(self, symbol: str, t: float, bar: int) -> float:
        p = self._profile(symbol)
        yearly = p["vol"]
        slow = 0.35 * yearly * math.sin(2 * math.pi * t / p["slow_period"] + p["slow_phase"])
        fast = 0.05 * yearly * math.sin(2 * math.pi * t / p["fast_period"] + p["fast_phase"])
        bar_sd = yearly * math.sqrt(bar / (365 * 86400))
        noise = random.Random(_seed(symbol, int(t // bar), bar)).gauss(0, bar_sd)
        return p["base"] * math.exp(slow + fast + noise)

    def candles(self, symbol: str, interval: str = "1d", limit: int = 200) -> List[Candle]:
        bar = _BAR.get(interval, 86400)
        now = self._clock()
        start = (int(now // bar) - limit + 1) * bar
        p = self._profile(symbol)
        out = []
        for n in range(limit):
            t = start + n * bar
            open_, close = self._price(symbol, t, bar), self._price(symbol, t + bar * 0.999, bar)
            wiggle = abs(random.Random(_seed("hl", symbol, t)).gauss(0, 0.004))
            volume = p["dollar_volume"] * bar / 86400 / close * random.Random(_seed("v", symbol, t)).uniform(0.5, 1.5)
            out.append(Candle(t, open_, max(open_, close) * (1 + wiggle), min(open_, close) * (1 - wiggle), close, volume))
        return out

    def quote(self, symbol: str) -> Quote:
        p = self._profile(symbol)
        now = self._clock()
        price = self._price(symbol, now, 60)
        day_ago = self._price(symbol, now - 86400, 60)
        half = price * p["spread_bps"] / 20_000
        return Quote(symbol.upper(), round(price, 6), round(price - half, 6), round(price + half, 6),
                     p["dollar_volume"] / price, round((price / day_ago - 1) * 100, 2), now)

    def book(self, symbol: str, depth: int = 50) -> Optional[Book]:
        """A book whose lean follows the last hour's move: buyers stack up while it is rising."""
        q = self.quote(symbol)
        p = self._profile(symbol)
        hour_ago = self._price(symbol, self._clock() - 3600, 60)
        lean = max(-0.6, min(0.6, (q.price / hour_ago - 1) * 400))
        rng = random.Random(_seed("book", symbol, int(self._clock() // 60)))
        unit = p["dollar_volume"] / 2_000 / q.price
        bids, asks = [], []
        for level in range(depth):
            step = q.price * (p["spread_bps"] / 20_000) * (1 + level * 0.8)
            bids.append((round(q.price - step, 6), round(unit * (1 + lean) * rng.uniform(0.5, 1.5), 6)))
            asks.append((round(q.price + step, 6), round(unit * (1 - lean) * rng.uniform(0.5, 1.5), 6)))
        return Book(q.symbol, bids, asks, q.at)
