"""Real prices from free, keyless sources: Coinbase for crypto, Yahoo for stocks and currencies.

Why these two: both answer without an account or a key, so the trader can see the real market from
the first minute. Coinbase also gives the bid, the ask and the full order book for free, which is
exactly what ranking on spread, depth and order flow needs. Free stock feeds do not give a book, so
for stocks ranking estimates spread and depth from prices and volume instead (``ranking.py``).

Every call has a short timeout and every failure becomes a ``MarketDataError`` with a plain
sentence, so one slow market costs that market, never the whole scan. ``session`` can be swapped
for a fake in tests: nothing here is called from the test suite with a real network.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import requests

from ..models import Book, Candle, Instrument, MarketDataError, Quote
from . import universe

TIMEOUT = 6.0
HEADERS = {"User-Agent": "IchosTrader/0.1 (+https://github.com/ShagnikPal123/Local-AI-Project)"}


def _get(session: Any, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    try:
        response = session.get(url, params=params, timeout=TIMEOUT, headers=HEADERS)
    except Exception as error:  # noqa: BLE001 - any network trouble is "no price right now"
        raise MarketDataError(f"Could not reach {url.split('/')[2]}: {type(error).__name__}.") from error
    if response.status_code != 200:
        raise MarketDataError(f"{url.split('/')[2]} answered {response.status_code}.")
    try:
        return response.json()
    except ValueError as error:
        raise MarketDataError(f"{url.split('/')[2]} sent something that is not JSON.") from error


class CoinbaseFeed:
    """Coinbase Exchange's public market data: every USD pair, with bid/ask and a level-2 book."""

    name = "coinbase"
    BASE = "https://api.exchange.coinbase.com"

    def __init__(self, session: Any = None):
        self.session = session or requests.Session()
        self._products: Optional[List[Instrument]] = None

    def instruments(self) -> List[Instrument]:
        """Every online USD pair. Falls back to the built-in list when Coinbase cannot be reached."""
        if self._products is None:
            known = universe.CRYPTO
            try:
                rows = _get(self.session, f"{self.BASE}/products")
                self._products = [Instrument(r["id"], "crypto", known.get(r["base_currency"], r["base_currency"]), "USD",
                                             self.name)
                                  for r in rows if r.get("quote_currency") == "USD" and r.get("status") == "online"
                                  and not r.get("trading_disabled")]
            except (MarketDataError, KeyError, TypeError):
                self._products = universe.crypto()
        return list(self._products)

    def quote(self, symbol: str) -> Quote:
        ticker = _get(self.session, f"{self.BASE}/products/{symbol}/ticker")
        try:
            stats = _get(self.session, f"{self.BASE}/products/{symbol}/stats")
            opened = float(stats.get("open") or 0)
        except MarketDataError:
            opened = 0.0
        price = float(ticker.get("price") or 0)
        if price <= 0:
            raise MarketDataError(f"No price for {symbol} right now.")
        return Quote(symbol, price, float(ticker.get("bid") or 0) or None, float(ticker.get("ask") or 0) or None,
                     float(ticker.get("volume") or 0), round((price / opened - 1) * 100, 2) if opened else None,
                     time.time())

    def candles(self, symbol: str, interval: str = "1d", limit: int = 200) -> List[Candle]:
        granularity = {"1m": 60, "1h": 3600, "1d": 86400}.get(interval, 86400)
        rows = _get(self.session, f"{self.BASE}/products/{symbol}/candles", {"granularity": granularity})
        # Coinbase sends [time, low, high, open, close, volume], newest first.
        out = [Candle(float(r[0]), float(r[3]), float(r[2]), float(r[1]), float(r[4]), float(r[5])) for r in rows]
        return sorted(out, key=lambda c: c.t)[-limit:]

    def book(self, symbol: str, depth: int = 50) -> Optional[Book]:
        data = _get(self.session, f"{self.BASE}/products/{symbol}/book", {"level": 2})
        bids = [(float(p), float(s)) for p, s, *_ in data.get("bids", [])[:depth]]
        asks = [(float(p), float(s)) for p, s, *_ in data.get("asks", [])[:depth]]
        return Book(symbol, bids, asks, time.time())


class YahooFeed:
    """Yahoo's chart endpoint: stocks, ETFs and currency pairs, no key. No order book."""

    name = "yahoo"
    BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"

    def __init__(self, instruments: List[Instrument], session: Any = None):
        self.session = session or requests.Session()
        self._items = instruments

    def instruments(self) -> List[Instrument]:
        return list(self._items)

    @staticmethod
    def ticker(symbol: str) -> str:
        """EUR-USD is EURUSD=X on Yahoo; stocks keep their symbol (BRK.B becomes BRK-B)."""
        if len(symbol) == 7 and symbol[3] == "-" and symbol.replace("-", "").isalpha():
            return symbol.replace("-", "") + "=X"
        return symbol.replace(".", "-")

    def _chart(self, symbol: str, range_: str, interval: str) -> Dict[str, Any]:
        data = _get(self.session, self.BASE + self.ticker(symbol), {"range": range_, "interval": interval})
        try:
            return data["chart"]["result"][0]
        except (KeyError, IndexError, TypeError) as error:
            raise MarketDataError(f"Yahoo has no chart for {symbol}.") from error

    def quote(self, symbol: str) -> Quote:
        meta = self._chart(symbol, "5d", "1d").get("meta", {})
        price = float(meta.get("regularMarketPrice") or 0)
        previous = float(meta.get("chartPreviousClose") or meta.get("previousClose") or 0)
        if price <= 0:
            raise MarketDataError(f"No price for {symbol} right now.")
        return Quote(symbol, price, None, None, float(meta.get("regularMarketVolume") or 0) or None,
                     round((price / previous - 1) * 100, 2) if previous else None, time.time())

    def candles(self, symbol: str, interval: str = "1d", limit: int = 200) -> List[Candle]:
        range_ = {"1m": "1d", "1h": "1mo"}.get(interval, "1y")
        result = self._chart(symbol, range_, interval if interval in ("1m", "1h", "1d") else "1d")
        stamps = result.get("timestamp") or []
        q = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        out = []
        for n, t in enumerate(stamps):
            row = [q.get(k, [None] * len(stamps))[n] for k in ("open", "high", "low", "close", "volume")]
            if None not in row[:4]:
                out.append(Candle(float(t), float(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4] or 0)))
        return out[-limit:]

    def book(self, symbol: str, depth: int = 50) -> Optional[Book]:
        return None
